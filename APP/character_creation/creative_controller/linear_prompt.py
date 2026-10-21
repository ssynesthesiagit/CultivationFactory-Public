"""Prompt and response helpers for the bounded linear DCC walk.

The prompt is deliberately split into a run-stable prefix and a small
per-menu suffix.  Only opaque option IDs are authoritative in a model reply;
the parser does not attempt to interpret prose or recover a choice by name.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from collections.abc import Mapping

from app.core import FoundryError

from .linear_menus import (
    MAX_WALK_STEPS,
    CommittedState,
    LinearMenuError,
    StepMenu,
    StepOption,
    validate_step_menu,
)


MAX_PREFIX_LENGTH = 4096
MAX_SUFFIX_LENGTH = 2048
MAX_IDENTITY_LENGTH = 60
MAX_TITLE_LENGTH = 120
MAX_CONCEPT_LENGTH = 240

OPERATOR_CONTRACT = (
    "You are the bounded creative-choice operator for Tianxia Foundry.\n"
    "Use only the presented opaque option IDs. Do not invent IDs, mechanics, "
    "rules, prerequisites, or replacements. Choose exactly one option for "
    "the current step and return one JSON object. A none option is an "
    "explicit stop only when it is presented. The Factory, not this reply, "
    "is authoritative for legality.\n"
)


def _short(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sealed_user_locks(request: Any, envelope: Any) -> list[Mapping[str, Any]]:
    """Collect only owner-lock rows already sealed into this request."""

    request_map = _map(request)
    envelope_map = _map(envelope)
    rows: list[Mapping[str, Any]] = []
    sources = (
        _map(_map(request_map.get("stage1_prompt")).get("envelope")).get("user_locks"),
        _map(request_map.get("typed_choice_snapshot")).get("typed_locks"),
        envelope_map.get("owner_user_locks"),
        request_map.get("owner_user_locks"),
    )
    for source in sources:
        if isinstance(source, (list, tuple)):
            rows.extend(row for row in source if isinstance(row, Mapping))
    return rows


def _sealed_descriptive_value(
    request: Any,
    envelope: Any,
    field: str,
    aliases: tuple[str, ...],
) -> str | None:
    """Resolve an owner-locked descriptive value from frozen authority only."""

    envelope_map = _map(envelope)
    delegated_fields = _map(envelope_map.get("delegated_fields"))
    authority = _map(delegated_fields.get(field))
    contract_keys = {
        "identity.name": ("delegated_name_contract",),
        "identity.title": ("delegated_title_contract",),
    }.get(field, ())
    if authority.get("state") == "owner_locked":
        value = authority.get("owner_value")
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
        for contract_key in contract_keys:
            contract = _map(envelope_map.get(contract_key))
            value = contract.get("owner_locked_value")
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())

    for contract_key in contract_keys:
        contract = _map(envelope_map.get(contract_key))
        value = contract.get("owner_locked_value")
        if contract.get("state") == "owner_locked" and isinstance(value, str) and value.strip():
            return " ".join(value.split())

    for row in _sealed_user_locks(request, envelope):
        if row.get("field") in aliases:
            value = row.get("value")
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())
    return None


def owner_locked_identity_name(request: Any, envelope: Any) -> str | None:
    """Return the exact sealed name when this request owns the identity name."""

    return _sealed_descriptive_value(
        request,
        envelope,
        "identity.name",
        ("character.identity.display_name", "identity.name", "owner_descriptive_fields.identity.name"),
    )


def owner_locked_identity_title(request: Any, envelope: Any) -> str | None:
    """Return the exact sealed title when this request owns the identity title."""

    return _sealed_descriptive_value(
        request,
        envelope,
        "identity.title",
        ("character.identity.title", "identity.title", "owner_descriptive_fields.identity.title"),
    )


def _owner_locked_concept(request: Any, envelope: Any) -> str | None:
    return _sealed_descriptive_value(
        request,
        envelope,
        "concept",
        ("concept", "character.identity.concept", "owner_descriptive_fields.concept"),
    )


def owner_locked_descriptive_fields(request: Any, envelope: Any) -> dict[str, str]:
    """Return every descriptive field already sealed by the active request."""

    fields: dict[str, str] = {}
    for field, aliases in (
        (
            "owner_descriptive_fields.identity.name",
            ("character.identity.display_name", "identity.name", "owner_descriptive_fields.identity.name"),
        ),
        (
            "concept",
            ("concept", "character.identity.concept", "owner_descriptive_fields.concept"),
        ),
        (
            "owner_descriptive_fields.identity.title",
            ("character.identity.title", "identity.title", "owner_descriptive_fields.identity.title"),
        ),
    ):
        authority_field = {
            "owner_descriptive_fields.identity.name": "identity.name",
            "concept": "concept",
            "owner_descriptive_fields.identity.title": "identity.title",
        }[field]
        value = _sealed_descriptive_value(request, envelope, authority_field, aliases)
        if value is not None:
            fields[field] = value
    return fields


def _identity_limit(default: int, locked_value: str | None) -> int:
    """Keep free-field limits while making a sealed value schema-satisfiable."""

    return max(default, len(locked_value)) if locked_value is not None else default


def _owner_revision_notes(request: Any, envelope: Any) -> str | None:
    """Read bounded linked-edit notes without treating them as authority."""

    request_map = _map(request)
    envelope_map = _map(envelope)
    candidates: list[Any] = [request_map.get("owner_notes")]
    for source in (
        request_map.get("revision_request"),
        request_map.get("edit_brief"),
        envelope_map.get("revision_request"),
    ):
        source_map = _map(source)
        candidates.append(source_map.get("owner_notes"))
        candidates.append(_map(source_map.get("brief")).get("owner_notes"))
    for value in candidates:
        text = _short(value, 1200)
        if text:
            return text
    return None


def _first(request: Any, envelope: Any, *keys: str) -> Any:
    for source in (_map(request), _map(envelope)):
        for key in keys:
            if key in source:
                return source[key]
    return None


_DISPLAY_ID_FIELDS = (
    "choice_id",
    "id",
    "value",
    "route_id",
    "ability",
    "ability_id",
    "path_id",
    "subpath_id",
    "method_id",
    "foundation_id",
    "background_id",
    "sphere_id",
    "talent_id",
    "insight_id",
    "item_id",
    "origin_id",
)
_DISPLAY_FIELDS = ("name", "display_name", "sphere_name", "talent_name", "label", "title", "cue", "semantic_cue")
_SLOT_LABELS = {
    "path_choice": "Path",
    "subpath_choice": "Subpath",
    "method_choice": "Method",
    "foundation_choice": "Foundation",
    "background_choice": "Background",
    "background_sphere_choice": "Background Sphere",
    "background_talent_choice": "Background Talent",
    "background_ability": "Background Ability",
    "origin_insight_choice": "Origin Insight",
    "sphere_free_talent_pair": "Sphere/free-Talent pair",
    "sphere_route": "Sphere route",
    "ordinary_talent": "Ordinary Talent",
    "sphere_priorities": "Sphere priority",
    "insight_priorities": "Insight priority",
    "insight_occurrence": "Insight occurrence",
    "asi_or_insight": "Ability Score Improvement or Cultivation Insight",
    "item_priorities": "Item priority",
    "identity": "Identity",
}
# The two printed resolutions of the level milestone "Ability Score Improvement or
# Cultivation Insight".  The walk records which one a level takes in plain text,
# so an owner lock naming that resolution reads to the operator as the printed
# words instead of an internal branch name.
_BRANCH_LABELS = {
    "ability_score_increase": "the normal Ability Score Improvement",
    "cultivation_insight": "a Cultivation Insight",
}


def _display_id(row: Any) -> str | None:
    if isinstance(row, str) and row:
        return row
    if not isinstance(row, Mapping):
        return None
    for key in _DISPLAY_ID_FIELDS:
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _display_text(row: Any) -> str | None:
    if not isinstance(row, Mapping):
        return None
    for key in _DISPLAY_FIELDS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:160]
    return None


def _display_rows(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        if _display_id(value) is not None:
            return [value]
        for key in ("options", "choices", "allowed_values", "values", "items", "ids", "spheres", "talents"):
            if key in value:
                return _display_rows(value[key])
        return [{"id": str(key), **(dict(row) if isinstance(row, Mapping) else {})} for key, row in value.items() if isinstance(key, str)]
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _display_catalog(request: Any, envelope: Any) -> dict[tuple[str, str], str]:
    """Resolve typed IDs to labels; unresolved values stay generic."""

    catalog: dict[tuple[str, str], str] = {}
    for source in (_map(envelope), _map(request)):
        for container_key in ("choices_by_slot", "allowed_choices_by_slot", "allowed_high_level", "choices"):
            slots = source.get(container_key)
            if not isinstance(slots, Mapping):
                continue
            for slot_id, rows in slots.items():
                if not isinstance(slot_id, str):
                    continue
                for row in _display_rows(rows):
                    choice_id = _display_id(row)
                    if choice_id is None:
                        continue
                    label = _display_text(row)
                    if label:
                        catalog.setdefault((slot_id, choice_id), label)
        shortlist = source.get("ordinary_talent_shortlist_by_sphere")
        if isinstance(shortlist, Mapping):
            for rows in shortlist.values():
                for row in _display_rows(rows):
                    choice_id = _display_id(row)
                    label = _display_text(row)
                    if choice_id and label:
                        catalog.setdefault(("ordinary_talent", choice_id), label)
        linkage = source.get("background_package_linkage")
        if isinstance(linkage, Mapping):
            for background_id, background in linkage.items():
                if not isinstance(background_id, str):
                    continue
                for row in _display_rows(background.get("spheres") if isinstance(background, Mapping) else background):
                    choice_id = _display_id(row)
                    label = _display_text(row)
                    if choice_id and label:
                        catalog.setdefault(("background_sphere_choice", choice_id), label)
                if isinstance(background, Mapping):
                    for sphere_id, sphere in background.items():
                        if sphere_id in {"spheres", "sphere_ids", "allowed_spheres"} or not isinstance(sphere_id, str):
                            continue
                        for row in _display_rows(sphere.get("talents") if isinstance(sphere, Mapping) else sphere):
                            choice_id = _display_id(row)
                            label = _display_text(row)
                            if choice_id and label:
                                catalog.setdefault(("background_talent_choice", choice_id), label)
        # The pair and route projections are typed authority records rather
        # than ordinary slot rows.  Resolve their display names here so
        # committed-state prompts never fall back to canonical IDs.
        contract = source.get("response_contract")
        pair_rows = contract.get("presented_legal_first_cycle_pairs") if isinstance(contract, Mapping) else None
        if pair_rows is None:
            pair_rows = source.get("presented_legal_first_cycle_pairs")
        for pair_row in _display_rows(pair_rows):
            if not isinstance(pair_row, Mapping):
                continue
            pair = pair_row.get("free_talent_pair") if isinstance(pair_row.get("free_talent_pair"), Mapping) else pair_row
            sphere_id = pair.get("sphere_id") if isinstance(pair, Mapping) else None
            talent_id = pair.get("talent_id") if isinstance(pair, Mapping) else None
            sphere_name = pair_row.get("sphere_name") if isinstance(pair_row.get("sphere_name"), str) else None
            talent_name = pair_row.get("talent_name") if isinstance(pair_row.get("talent_name"), str) else None
            if isinstance(sphere_id, str) and sphere_name:
                catalog.setdefault(("sphere_free_talent_pair", sphere_id), _short(sphere_name, 160))
            if isinstance(talent_id, str) and talent_name:
                catalog.setdefault(("sphere_free_talent_pair", talent_id), _short(talent_name, 160))
            for choice_id, slot_id in ((sphere_id, "sphere_free_talent_pair"), (talent_id, "sphere_free_talent_pair")):
                if not isinstance(choice_id, str) or (slot_id, choice_id) in catalog:
                    continue
                matching = next((label for (_source_slot, source_id), label in catalog.items() if source_id == choice_id), None)
                if matching:
                    catalog.setdefault((slot_id, choice_id), matching)
        for route in _display_rows(source.get("sphere_route_modules")):
            if not isinstance(route, Mapping):
                continue
            route_id = route.get("route_id")
            sphere_id = route.get("sphere_id")
            sphere_name = route.get("sphere_name") if isinstance(route.get("sphere_name"), str) else None
            sphere = route.get("sphere")
            if sphere_name is None and isinstance(sphere, Mapping):
                sphere_name = sphere.get("name") if isinstance(sphere.get("name"), str) else None
            if isinstance(route_id, str) and sphere_name:
                catalog.setdefault(("sphere_route", route_id), _short(sphere_name, 160))
            if isinstance(sphere_id, str) and sphere_name:
                catalog.setdefault(("sphere_free_talent_pair", sphere_id), _short(sphere_name, 160))
            assignments = route.get("ordinary_talent_ids_by_cl")
            if isinstance(assignments, Mapping):
                for talent_id in assignments.values():
                    if isinstance(talent_id, str):
                        catalog.setdefault(("ordinary_talent", talent_id), "Ordinary Talent")
        profiles = _map(source.get("sphere_comparability_index")).get("profiles")
        for profile in _display_rows(profiles):
            if not isinstance(profile, Mapping):
                continue
            sphere_id = profile.get("sphere_id")
            label = _display_text(profile)
            if isinstance(sphere_id, str) and label:
                catalog.setdefault(("sphere_free_talent_pair", sphere_id), label)
                catalog.setdefault(("sphere_route", sphere_id), label)
    for (slot_id, choice_id), label in tuple(catalog.items()):
        if slot_id == "insight_priorities":
            catalog.setdefault(("insight_occurrence", choice_id), label)
    return catalog


def _slot_label(slot_id: str) -> str:
    return _SLOT_LABELS.get(slot_id.split(":", 1)[0], "Committed choice")


def _label_for(catalog: Mapping[tuple[str, str], str], slot_id: str, choice_id: str) -> str:
    return catalog.get((slot_id, choice_id), catalog.get((slot_id.split(":", 1)[0], choice_id), _slot_label(slot_id)))


def _target_cl(request: Any, envelope: Any) -> str:
    value = _first(request, envelope, "target_cl", "starting_cl", "character_level")
    if type(value) is int:
        return str(value)
    binding = _map(_map(request).get("binding"))
    return str(binding.get("target_cl")) if type(binding.get("target_cl")) is int else "unknown"


_INSPIRATION = {
    "origin": (
        "a fishing village on a misty southern marsh", "a northern steppe frontier fort",
        "the lower wards of the imperial capital", "a salt-flat trading post by the sea",
        "the ruins of a fallen bamboo-valley sect", "a desert caravan oasis",
        "a frozen high-plateau monastery", "a river-delta smuggling port",
        "a mountain mining town", "a border village between warring clans",
        "a floating market on a lake", "an ancestral shrine deep in old forest",
    ),
    "motif": (
        "thunder", "rot and renewal", "iron and forge smoke", "moonlight", "blood lineage",
        "poison and cure", "music", "ancestors and graves", "wildfire", "frost",
        "beasts of the wild", "mirrors and illusion", "tides", "ink and scripture",
    ),
    "temperament": (
        "patient", "reckless", "grieving", "ambitious", "devout", "cynical",
        "merciful", "obsessive", "cheerful", "cold and exacting",
    ),
    "role": (
        "outcast", "disinherited heir", "hunter", "healer", "scholar", "smuggler",
        "former soldier", "wandering monk", "sect servant", "bodyguard", "artisan", "exile",
    ),
}


def _inspiration(request: Any, envelope: Any) -> str:
    """A server-seeded starting idea for a blank brief, so characters differ.

    Seeded by the sealed request hash: every replay of one run sees the same
    idea, and different runs see different ones.
    """
    request_map = _map(request)
    seed = request_map.get("request_sha256") or _map(request_map.get("binding")).get("request_sha256") or ""
    if not isinstance(seed, str) or not seed:
        return ""
    picks = []
    for key, values in _INSPIRATION.items():
        digest = hashlib.sha256(f"tianxia.inspiration.v1|{seed}|{key}".encode("utf-8")).digest()
        picks.append(values[int.from_bytes(digest[:8], "big") % len(values)])
    origin, motif, temperament, role = picks
    return f"a {temperament} {role} from {origin}, whose cultivation is shaped by {motif}"


def _name_suggestions(request: Any, envelope: Any, committed: Any) -> list[str]:
    """Seeded ancient-Chinese names for the identity step (owner 2026-09-27: the local AI named five characters
    "Lingfeng"): themed by the Spheres already chosen and the seeded inspiration's motif; seeded by the sealed request
    hash, so every replay of one run sees the same names (factory_authoring/names.py)."""
    request_map = _map(request)
    seed = request_map.get("request_sha256") or _map(request_map.get("binding")).get("request_sha256") or ""
    if not isinstance(seed, str) or not seed:
        return []
    from factory_authoring import names

    words = [str(value) for value in _committed_names(committed, None, request, envelope)] if committed is not None else []
    motif = ""
    if not _concept(request, envelope):
        digest = hashlib.sha256(f"tianxia.inspiration.v1|{seed}|motif".encode("utf-8")).digest()
        motif = _INSPIRATION["motif"][int.from_bytes(digest[:8], "big") % len(_INSPIRATION["motif"])]
    dao = names.data()["motif_trigrams"].get(motif)
    rows = names.suggestions(seed, 6, dao=dao, themes=names.themes_for([*words, motif]))
    return [f"{row['name']} ({row['meaning']})" for row in rows]


def _concept(request: Any, envelope: Any) -> str:
    locked = _owner_locked_concept(request, envelope)
    if locked:
        return _short(locked, 900)
    for source in (_map(request), _map(_map(request).get("stage1_prompt")), _map(_map(request).get("intent")), _map(envelope)):
        for key in ("concept", "one_sentence_concept", "character_concept", "brief"):
            value = _short(source.get(key), 900)
            if value:
                return value
        identity = _map(source.get("identity"))
        value = _short(identity.get("one_sentence_concept", identity.get("concept")), 900)
        if value:
            return value
    return ""


def _locked_ids(request: Any, envelope: Any) -> list[str]:
    raw = _first(request, envelope, "owner_locks")
    locks = _map(raw).get("by_slot") if isinstance(raw, Mapping) else None
    locks = locks if isinstance(locks, Mapping) else (_map(raw) if isinstance(raw, Mapping) else {})
    catalog = _display_catalog(request, envelope)
    result: list[str] = []
    for slot_id in sorted(locks):
        value = locks[slot_id]
        base_slot = str(slot_id).split(":", 1)[0]
        if base_slot == "sphere_free_talent_pair":
            pair_rows = value.get("pairs") if isinstance(value, Mapping) else value
            pair_rows = pair_rows if isinstance(pair_rows, (list, tuple)) else [pair_rows]
            for pair in pair_rows:
                if not isinstance(pair, Mapping):
                    continue
                sphere_id = pair.get("sphere_id")
                talent_id = pair.get("talent_id")
                if isinstance(sphere_id, str) and isinstance(talent_id, str):
                    sphere = _label_for(catalog, base_slot, sphere_id)
                    talent = _label_for(catalog, base_slot, talent_id)
                    result.append(f"{_slot_label(str(slot_id))}: {sphere} + {talent}")
            continue
        if base_slot == "sphere_route" and isinstance(value, Mapping):
            value = value.get("route_id", value.get("id"))
        elif base_slot == "ordinary_talent" and isinstance(value, Mapping):
            value = list(value.values())
        elif base_slot == "insight_occurrence":
            occurrence_rows = value if isinstance(value, (list, tuple)) else [value]
            for occurrence in occurrence_rows:
                if isinstance(occurrence, Mapping) and isinstance(occurrence.get("insight_id"), str):
                    label = _label_for(catalog, base_slot, occurrence["insight_id"])
                    result.append(f"{_slot_label(str(slot_id))}: {label}")
            continue
        if base_slot == "asi_or_insight":
            branch_rows = _map(value).get("advancement_milestone_branch_by_milestone_id") if isinstance(value, Mapping) else None
            if branch_rows is None:
                branch_rows = _map(value).get("branches") if isinstance(value, Mapping) else None
            if isinstance(branch_rows, Mapping):
                for milestone_id, raw in sorted(branch_rows.items(), key=lambda item: str(item[0])):
                    branch = raw
                    if isinstance(raw, Mapping):
                        branch = raw.get("branch", raw.get("choice_id", raw.get("value")))
                    if isinstance(branch, str) and branch in _BRANCH_LABELS:
                        result.append(f"{_slot_label(f'asi_or_insight:{milestone_id}')}: {_BRANCH_LABELS[branch]}")
                    continue
            branch = value.get("branch", value.get("choice_id", value.get("value"))) if isinstance(value, Mapping) else value
            if isinstance(branch, str) and branch in _BRANCH_LABELS:
                result.append(f"{_slot_label(str(slot_id))}: {_BRANCH_LABELS[branch]}")
                continue
        values = _map(value).get("choice_ids", _map(value).get("choices", _map(value).get("id"))) if isinstance(value, Mapping) else value
        if not isinstance(values, (list, tuple)):
            values = [values]
        ids = [item for item in values if isinstance(item, str) and item]
        if ids:
            labels = [_label_for(catalog, str(slot_id), item) for item in ids[:4]]
            result.append(f"{_slot_label(str(slot_id))}: {', '.join(labels)}")
    return result[:12]


def build_stable_prefix(request: Mapping[str, Any] | None, envelope: Mapping[str, Any] | None = None) -> str:
    """Build bytes shared by every step of one frozen request."""

    request = request if isinstance(request, Mapping) else {}
    envelope = envelope if isinstance(envelope, Mapping) else {}
    lines = [
        "[system]",
        OPERATOR_CONTRACT.rstrip("\n"),
        "[user, part A]",
        f"Target cultivation level: {_target_cl(request, envelope)}",
        f"Character brief: {_concept(request, envelope) or 'No additional concept text was frozen.'}",
        "Owner-locked choices: " + ("; ".join(_locked_ids(request, envelope)) or "none"),
    ]
    from character_creation.concept_index import prompt_guidance

    concept_advice = prompt_guidance(request)
    if concept_advice:
        lines.append(concept_advice)
    owner_notes = _owner_revision_notes(request, envelope)
    if owner_notes:
        lines.append(
            "Owner revision notes (narrative guidance only; choose only sealed legal options): "
            + owner_notes
        )
    return "\n".join(lines)[:MAX_PREFIX_LENGTH]


def _menu_from(value: StepMenu | Mapping[str, Any]) -> StepMenu:
    if isinstance(value, StepMenu):
        return validate_step_menu(value)
    if isinstance(value, Mapping):
        options = []
        for row in value.get("options") or []:
            if not isinstance(row, Mapping):
                raise LinearMenuError("DCC_LINEAR_OPTION_TYPE", "A menu option must be an object.")
            options.append(StepOption(
                str(row.get("option_id", "")),
                tuple(row.get("choice_ids") or ()),
                str(row.get("cue", "Continue")),
                str(row.get("kind", "pick")),
            ))
        return StepMenu(
            step_id=str(value.get("step_id", "")),
            step_kind=str(value.get("step_kind", "")),
            ordinal=value.get("ordinal", 0),
            title=str(value.get("title", "")),
            min_choices=value.get("min_choices", 0),
            max_choices=value.get("max_choices", 0),
            options=tuple(options),
            page_id=str(value.get("page_id", "")),
            next_page_id=value.get("next_page_id"),
            authority_sha256=str(value.get("authority_sha256", "")),
            menu_sha256=str(value.get("menu_sha256", "")),
        )
    raise LinearMenuError("DCC_LINEAR_MENU_TYPE", "Expected a linear step menu.")


def _committed_names(committed: Any, menu: StepMenu, request: Any, envelope: Any) -> list[str]:
    if isinstance(committed, CommittedState):
        source = committed.to_dict()
    else:
        source = _map(committed)
    slots = _map(source.get("by_slot"))
    catalog = _display_catalog(request, envelope)
    result: list[str] = []
    for slot_id in sorted(slots):
        values = slots[slot_id]
        if slot_id == "item_priorities" and getattr(menu, "step_kind", None) == "identity":
            # An item priority is a wish the kit may not afford (owner 2026-09-27: the concept promised a
            # "World-Turtle Shield +3" the budget bought as a Hundred-Fold Steel Shield +1); the concept is not built on it.
            continue
        if isinstance(values, (list, tuple)):
            for value in values:
                if isinstance(value, str):
                    result.append(f"{_slot_label(str(slot_id))}: {_label_for(catalog, str(slot_id), value)}")
    route_id = source.get("route_id")
    if isinstance(route_id, str) and route_id:
        result.append(f"Sphere route: {_label_for(catalog, 'sphere_route', route_id)}")
    pairs = source.get("pairs")
    if isinstance(pairs, (list, tuple)):
        for pair in pairs:
            if not isinstance(pair, Mapping):
                continue
            sphere_id = pair.get("sphere_id")
            talent_id = pair.get("talent_id")
            if not isinstance(sphere_id, str) or not isinstance(talent_id, str):
                continue
            sphere = _label_for(catalog, "sphere_free_talent_pair", sphere_id)
            talent = _label_for(catalog, "sphere_free_talent_pair", talent_id)
            result.append(f"Sphere/free-Talent pair: {sphere} + {talent}")
    ordinary = _map(source.get("ordinary_by_cl"))
    for cl, talent_id in sorted(ordinary.items(), key=lambda item: str(item[0])):
        if isinstance(talent_id, str):
            result.append(f"Ordinary Talent CL {cl}: {_label_for(catalog, 'ordinary_talent', talent_id)}")
    occurrences = source.get("insight_occurrences")
    if isinstance(occurrences, (list, tuple)):
        for occurrence in occurrences:
            if isinstance(occurrence, Mapping) and isinstance(occurrence.get("insight_id"), str):
                result.append(f"Insight occurrence: {_label_for(catalog, 'insight_occurrence', occurrence['insight_id'])}")
    return result[:40]


def _working_identity(committed: Any) -> str:
    """The identity chosen at the start of the walk, as one prompt line."""

    source = committed.to_dict() if isinstance(committed, CommittedState) else _map(committed)
    identity = _map(_map(source.get("bounded")).get("identity"))
    name = identity.get("name") if isinstance(identity.get("name"), str) else ""
    title = identity.get("title") if isinstance(identity.get("title"), str) else ""
    concept = identity.get("concept") if isinstance(identity.get("concept"), str) else ""
    head = ", ".join(part for part in (name.strip(), title.strip()) if part)
    return _short(f"{head}: {concept.strip()}" if head and concept.strip() else head or concept.strip(), 400)


WALK_STEPS_FIXED = 30
WALK_STEPS_PER_LEVEL = 6


def walk_steps_estimate(request: Mapping[str, Any] | None) -> int:
    """Estimate the guided walk's length from the frozen target level.

    A finished CL 20 walk publishes about 145 menus: roughly 30 one-off
    choices (identity, Method, Foundation, Background, point buy, Path
    skills, priorities) plus about six per level (three Constructed
    Training menus, one Path progression, one ordinary talent, and the
    milestone or Insight menus spread across levels).  The value is an
    estimate for the owner-facing headline and the step prompt; the walk
    itself is bounded by MAX_WALK_STEPS.
    """

    target_cl = None
    if isinstance(request, Mapping):
        envelope = request.get("delegated_choice_envelope")
        binding = envelope.get("binding") if isinstance(envelope, Mapping) else None
        if isinstance(binding, Mapping) and type(binding.get("target_cl")) is int:
            target_cl = binding["target_cl"]
    if target_cl is None or target_cl < 1:
        return 22
    return max(22, min(MAX_WALK_STEPS, WALK_STEPS_FIXED + WALK_STEPS_PER_LEVEL * target_cl))


def build_step_prompt(
    request: Mapping[str, Any] | None,
    envelope: Mapping[str, Any] | None,
    committed: CommittedState | Mapping[str, Any] | None,
    menu: StepMenu | Mapping[str, Any],
    *,
    steps_estimate: int = 22,
) -> str:
    """Build the stable prefix plus one bounded menu-specific suffix."""

    menu = _menu_from(menu)
    estimate = steps_estimate if type(steps_estimate) is int and 1 <= steps_estimate <= MAX_WALK_STEPS else 22
    lines = [
        build_stable_prefix(request, envelope),
        "[user, part B]",
        f"Step {menu.ordinal} of about {estimate}: {menu.title}",
        "Already chosen: " + ("; ".join(_committed_names(committed, menu, request, envelope)) or "none"),
    ]
    working_identity = _working_identity(committed)
    if working_identity and menu.step_kind != "identity":
        lines.insert(2, f"Character concept (keep every choice consistent with it): {working_identity}")
    if menu.step_kind.split(":", 1)[0] in {"insight_priorities", "item_priorities"}:
        lines.append("Choose what this built character would prioritize next; this shapes the final sheet.")
    if menu.step_kind in {"asi_or_insight", "insight_occurrence", "point_buy_preset",
                          "point_buy_assignment", "background_ability", "asi_milestone"}:
        from character_creation.insight_build_policy import AUTOMATIC_INSIGHT_ADVICE

        if menu.step_kind in {"point_buy_preset", "point_buy_assignment", "background_ability"}:
            lines.append(
                "Choose starting scores and the Background bonus for this character's concept: "
                "consider its intended attacks, skills and defenses as well as Path and owned "
                "Sphere abilities. The first option is a fallback, not a required choice. "
                "Choose any offered legal score spread or assignment; use More options if "
                "needed. Spend exactly 27 points, keep starting scores from 8 to 15, and "
                "honor owner locks."
            )
        else:
            lines.append(AUTOMATIC_INSIGHT_ADVICE)
        if menu.step_kind == "asi_or_insight" and menu.options:
            from .linear_menus import mechanical_choice_detail

            lines.append("Why the first option is recommended: "
                         + mechanical_choice_detail(request, envelope, committed, menu, menu.options[0]))
    lines.append("Options:")
    for option in menu.options:
        lines.append(f"  {option.option_id} — {option.cue}")
    if menu.step_kind == "identity":
        locked_name = owner_locked_identity_name(request, envelope)
        locked_title = owner_locked_identity_title(request, envelope)
        locked_concept = _owner_locked_concept(request, envelope)
        if locked_name:
            lines.append(
                f"Owner-locked identity name: {locked_name}. copy this exact name unchanged; "
                "do not substitute, translate, or stylize it."
            )
        else:
            lines.append(
                "No owner-locked identity name is sealed. Propose one nonblank name for owner "
                "review; it may use ancient Chinese rendered in English/pinyin style; invent a "
                "fresh name for this character rather than a common stock name; it may incorporate "
                "theme from committed choices, carry no mechanics, and draw from the brief."
            )
            suggested = _name_suggestions(request, envelope, committed)
            if suggested:
                lines.append("Names drawn for this character from its Dao (choose one, or join parts of two; each is a real "
                             "ancient-style name): " + "; ".join(suggested) + ".")
        if locked_title:
            lines.append(
                f"Owner-locked identity title: {locked_title}. copy this exact title unchanged; "
                "do not substitute, translate, or stylize it."
            )
        else:
            lines.append(
                "Also write one concise nonblank identity title for owner review; do not infer it "
                "from mechanics or rules text."
            )
        if locked_concept:
            lines.append(
                f"Owner-locked character concept: {locked_concept}. copy this exact concept "
                "unchanged; do not paraphrase or replace it."
            )
        else:
            lines.append(
                "Also write concept: one plain sentence (at most 240 characters) describing who "
                "this cultivator is and how they fight or cultivate, drawn from the brief; if the "
                "brief is empty, invent an original, specific cultivator. Never mention the brief, "
                "the prompt or missing information; no mechanics, no rules text, and no named item or "
                "treasure (the equipment is bought later, within the character's means). Every later step "
                "will be chosen to fit this concept."
            )
            inspiration = "" if _concept(request, envelope) else _inspiration(request, envelope)
            if inspiration:
                lines.append(f"Inspiration for this character (build on it freely): {inspiration}.")
        lines.append('Reply with one JSON object: {"name":"<string>","title":"<string>","concept":"<string>"}')
    else:
        lines.append('Reply with one JSON object: {"option_id":"<one of the IDs above>"}')
    return "\n".join(lines)[: MAX_PREFIX_LENGTH + MAX_SUFFIX_LENGTH]


def build_response_schema(
    menu: StepMenu | Mapping[str, Any],
    request: Mapping[str, Any] | None = None,
    envelope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the exact provider response schema for a menu."""

    menu = _menu_from(menu)
    if menu.step_kind == "identity":
        return build_identity_response_schema(request, envelope)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["option_id"],
        "properties": {
            "option_id": {"type": "string", "enum": list(menu.option_ids)},
        },
    }


def build_identity_response_schema(
    request: Mapping[str, Any] | None = None,
    envelope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    name_schema: dict[str, Any] = {"type": "string", "maxLength": MAX_IDENTITY_LENGTH}
    title_schema: dict[str, Any] = {"type": "string", "maxLength": MAX_TITLE_LENGTH}
    concept_schema: dict[str, Any] = {"type": "string", "maxLength": MAX_CONCEPT_LENGTH}
    locked_name = owner_locked_identity_name(request, envelope)
    if locked_name:
        name_schema = {
            "type": "string",
            "maxLength": _identity_limit(MAX_IDENTITY_LENGTH, locked_name),
            "const": locked_name,
        }
    locked_title = owner_locked_identity_title(request, envelope)
    if locked_title:
        title_schema = {
            "type": "string",
            "maxLength": _identity_limit(MAX_TITLE_LENGTH, locked_title),
            "const": locked_title,
        }
    locked_concept = _owner_locked_concept(request, envelope)
    if locked_concept:
        concept_schema = {
            "type": "string",
            "maxLength": _identity_limit(MAX_CONCEPT_LENGTH, locked_concept),
            "const": locked_concept,
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "title", "concept"],
        "properties": {
            "name": name_schema,
            "title": title_schema,
            "concept": concept_schema,
        },
    }


def parse_step_response(response: Mapping[str, Any] | str, menu: StepMenu | Mapping[str, Any]) -> str:
    """Validate one option-ID response before any state mutation."""

    menu = _menu_from(menu)
    if menu.step_kind == "identity":
        raise LinearMenuError("DCC_LINEAR_RESPONSE_KIND", "Identity responses require parse_identity_response.")
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except (TypeError, ValueError) as exc:
            raise LinearMenuError("DCC_LINEAR_RESPONSE_JSON", "The response is not valid JSON.") from exc
    if not isinstance(response, Mapping) or set(response) != {"option_id"}:
        raise LinearMenuError("DCC_LINEAR_RESPONSE_SCHEMA", "A step response must contain exactly option_id.")
    option_id = response.get("option_id")
    if not isinstance(option_id, str) or option_id not in set(menu.option_ids):
        raise LinearMenuError("DCC_LINEAR_UNKNOWN_OPTION", "The response option is not in the current menu.")
    return option_id


def parse_identity_response(
    response: Mapping[str, Any] | str,
    request: Mapping[str, Any] | None = None,
    envelope: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except (TypeError, ValueError) as exc:
            raise LinearMenuError("DCC_LINEAR_RESPONSE_JSON", "The identity response is not valid JSON.") from exc
    if not isinstance(response, Mapping) or set(response) not in ({"name", "title"}, {"name", "title", "concept"}):
        raise LinearMenuError("DCC_LINEAR_RESPONSE_SCHEMA", "Identity requires exactly name, title, and concept.")
    result: dict[str, str] = {}
    locked = owner_locked_descriptive_fields(request, envelope)
    for key in ("name", "title"):
        value = response.get(key)
        field = (
            "owner_descriptive_fields.identity.name"
            if key == "name"
            else "owner_descriptive_fields.identity.title"
        )
        limit = _identity_limit(
            MAX_IDENTITY_LENGTH if key == "name" else MAX_TITLE_LENGTH,
            locked.get(field),
        )
        if not isinstance(value, str) or not value or len(value) > limit:
            raise LinearMenuError(
                "DCC_LINEAR_IDENTITY_LIMIT",
                f"Identity {key} must be a non-empty string of at most {limit} characters.",
            )
        result[key] = " ".join(value.split())
        if not result[key]:
            raise LinearMenuError("DCC_LINEAR_IDENTITY_LIMIT", "Identity fields must not be blank.")
    if "concept" in response:
        concept = response.get("concept")
        concept_limit = _identity_limit(MAX_CONCEPT_LENGTH, locked.get("concept"))
        if not isinstance(concept, str) or len(concept) > concept_limit:
            raise LinearMenuError(
                "DCC_LINEAR_IDENTITY_LIMIT",
                f"The identity concept must be a string of at most {concept_limit} characters.",
            )
        concept = " ".join(concept.split())
        if concept:
            result["concept"] = concept
    return result


def validate_identity_owner_lock(
    response: Mapping[str, Any] | str,
    request: Mapping[str, Any] | None = None,
    envelope: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Reject any changed owner-locked descriptive field before commit."""

    identity = parse_identity_response(response, request, envelope)
    actual_fields = {
        "owner_descriptive_fields.identity.name": identity.get("name"),
        "concept": identity.get("concept"),
        "owner_descriptive_fields.identity.title": identity.get("title"),
    }
    messages = {
        "owner_descriptive_fields.identity.name": "The response must contain the exact owner-locked character name unchanged.",
        "concept": "The response must contain the exact owner-locked character concept unchanged.",
        "owner_descriptive_fields.identity.title": "The response must contain the exact owner-locked character title unchanged.",
    }
    for field, expected in owner_locked_descriptive_fields(request, envelope).items():
        if actual_fields.get(field) != expected:
            raise FoundryError(
                "CG1_OWNER_LOCKED_DESCRIPTIVE_FIELD_CHANGED",
                messages[field],
                details={"field": field, "expected": expected, "actual": actual_fields.get(field)},
                status_code=409,
            )
    return identity


def validate_option_id(option_id: Any, menu: StepMenu | Mapping[str, Any]) -> str:
    return parse_step_response({"option_id": option_id}, menu)


def build_step_schema(
    menu: StepMenu | Mapping[str, Any],
    request: Mapping[str, Any] | None = None,
    envelope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return build_response_schema(menu, request, envelope)


def response_schema(
    menu: StepMenu | Mapping[str, Any],
    request: Mapping[str, Any] | None = None,
    envelope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return build_response_schema(menu, request, envelope)


def parse_option_response(response: Mapping[str, Any] | str, menu: StepMenu | Mapping[str, Any]) -> str:
    return parse_step_response(response, menu)


__all__ = [
    "MAX_PREFIX_LENGTH",
    "MAX_SUFFIX_LENGTH",
    "MAX_IDENTITY_LENGTH",
    "MAX_TITLE_LENGTH",
    "OPERATOR_CONTRACT",
    "build_stable_prefix",
    "build_step_prompt",
    "build_response_schema",
    "build_identity_response_schema",
    "build_step_schema",
    "response_schema",
    "parse_step_response",
    "parse_option_response",
    "parse_identity_response",
    "owner_locked_identity_name",
    "owner_locked_identity_title",
    "owner_locked_descriptive_fields",
    "validate_identity_owner_lock",
    "validate_option_id",
]
