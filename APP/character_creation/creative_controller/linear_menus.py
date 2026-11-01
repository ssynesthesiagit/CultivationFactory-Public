"""Pure, bounded menus for the first version of the linear DCC walk.

This module intentionally has no dependency on the provider adapter, the
database, or the character-creation service.  A menu is a projection of the
already frozen request/envelope and committed state.  Identifiers are opaque;
the human-readable cue is presentation-only and is never consulted when
deciding whether a choice is legal.
"""

from __future__ import annotations

import itertools
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Mapping, Sequence
from character_creation.path_attainment import equal_initial_path_attainment, initial_path_attainment_vector
from paged_selection_contract import paged_max_pages

from creation_training_authority import (
    CREATION_TRAINING_BONUS_KIND,
    CREATION_TRAINING_CHANNEL_BY_KIND,
    CREATION_TRAINING_MAX_PER_CL,
    CREATION_TRAINING_SPHERE_KIND,
    CREATION_TRAINING_TALENT_KIND,
    SealedBackgroundSphereResolutionError,
    canonical_background_package_ids,
    canonical_selected_background_sphere_ids,
    constructed_outcome,
    constructed_source,
    creation_route_legality_errors,
    validate_creation_training_contract,
    validate_trained_choice_shape,
)

from .contracts import (
    CreativeControllerError,
    canonical_sha256,
    derive_option_id,
    domain_digest,
)


LINEAR_MENU_SCHEMA = "TianxiaFoundry.DccLinearStepMenu.v1"
LINEAR_OPTION_SCHEMA = "TianxiaFoundry.DccLinearStepOption.v1"
LINEAR_STATE_SCHEMA = "TianxiaFoundry.DccLinearCommittedState.v1"

MAX_OPTIONS_PER_PAGE = 12
MAX_PAGES_PER_STEP = 3
# Loop guard, not a design budget.  A three-Path CL20 build legitimately
# walks about 120 steps (20 ordinary Talents, up to 20 progression picks,
# 15 milestones with ability follow-ups, priorities, proficiencies), so the
# ceiling sits well above that while still failing a runaway walk closed.
MAX_WALK_STEPS = 200
# Rulebook Realm entry for Foundations (Core Rules Reference 1.2 / 8.2).
FOUNDATION_REALM_ENTRY_CL = 5
MAX_CUE_LENGTH = 160

OPTION_PICK = "pick"
OPTION_BUNDLE = "bundle"
OPTION_NONE = "none"
OPTION_KINDS = frozenset({OPTION_PICK, OPTION_BUNDLE, OPTION_NONE})
BACKGROUND_ABILITY_AMOUNT_PREFIX = "background_ability_amount:"

STEP_KINDS = frozenset(
    {
        "foundation_initial_stage",
        "path_choice",
        "subpath_choice",
        "method_choice",
        "foundation_choice",
        "background_choice",
        "background_sphere_choice",
        "background_talent_choice",
        "background_ability",
        "origin_insight_choice",
        "point_buy_preset",
        "point_buy_assignment",
        "sphere_free_talent_pair",
        "sphere_route",
        "ordinary_talent",
        "creation_training",
        "forged_design",
        "sphere_priorities",
        "insight_priorities",
        "insight_occurrence",
        "asi_or_insight",
        "asi_milestone",
        "path_progression",
        "path_skill",
        "origin_skill",
        "background_language",
        "item_priorities",
        "starting_kit_option",
        "starting_kit_choice",
        "treasure_weapon_chassis",
        "treasure_weapon_material",
        "treasure_weapon_enchantment",
        "treasure_armor_chassis",
        "treasure_armor_material",
        "treasure_armor_enhancement",
        "treasure_wondrous",
        "treasure_consumable",
        "identity",
    }
)

STEP_TITLES = {
    "foundation_initial_stage": "Initial Foundation Stage",
    "path_choice": "Path",
    "subpath_choice": "Subpath",
    "method_choice": "Method",
    "foundation_choice": "Foundation",
    "background_choice": "Background",
    "background_sphere_choice": "Background Sphere",
    "background_talent_choice": "Background Talent",
    "background_ability": "Background Ability",
    "origin_insight_choice": "Origin Insight",
    "point_buy_preset": "Point-buy Preset",
    "point_buy_assignment": "Point-buy Assignment",
    "sphere_free_talent_pair": "Sphere and Free Talent",
    "sphere_route": "Sphere Route",
    "ordinary_talent": "Ordinary Talent",
    "creation_training": "Constructed Training",
    "forged_design": "Forged Technique Design",
    "sphere_priorities": "Sphere Priorities",
    "insight_priorities": "Insight Priorities",
    "insight_occurrence": "Insight Occurrence",
    "asi_or_insight": "Ability Score Improvement or Cultivation Insight",
    "asi_milestone": "Ability Score Improvement",
    "path_progression": "Path Progression",
    "path_skill": "Path Skill",
    "origin_skill": "Origin Skill",
    "background_language": "Background Language",
    "item_priorities": "Item Priorities",
    "starting_kit_option": "Starting Kit",
    "starting_kit_choice": "Starting Kit Choice",
    "treasure_weapon_chassis": "Treasure Weapon",
    "treasure_weapon_material": "Treasure Weapon Material",
    "treasure_weapon_enchantment": "Treasure Weapon Enchantment",
    "treasure_armor_chassis": "Treasure Armour",
    "treasure_armor_material": "Treasure Armour Material",
    "treasure_armor_enhancement": "Treasure Armour Enhancement",
    "treasure_wondrous": "Wondrous Treasure",
    "treasure_consumable": "Consumable Treasure",
    "identity": "Identity",
}

_MISSING = object()
_ID_FIELDS = (
    "choice_id",
    "id",
    "value",
    "ability",
    "ability_score",
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
_CUE_FIELDS = (
    "cue",
    "semantic_cue",
    "display_name",
    "name",
    "label",
    "title",
    "category",
    "owner",
)


class LinearMenuError(CreativeControllerError):
    """A fail-closed error raised while projecting a linear menu."""


def _error(code: str, message: str, *, details: Any = None) -> None:
    raise LinearMenuError(code, message, details=details, status_code=400)


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _bounded_cue(value: Any, fallback: str) -> str:
    """Return a bounded display cue without making it an authority source."""

    cue = value if isinstance(value, str) else fallback
    cue = " ".join(cue.split())
    if not cue:
        cue = fallback
    return cue[:MAX_CUE_LENGTH]


def _canonical_scalar(value: Any) -> str | None:
    if isinstance(value, str):
        return value if value else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _choice_id(row: Any) -> str | None:
    if isinstance(row, str):
        return row or None
    if isinstance(row, (int, float)) and not isinstance(row, bool):
        return str(row)
    if not isinstance(row, Mapping):
        return None
    for key in _ID_FIELDS:
        value = _canonical_scalar(row.get(key))
        if value is not None:
            return value
    return None


def _cue(row: Any, choice_ids: Sequence[str]) -> str:
    # Canonical IDs are authority data, not owner/model-facing prose.  A
    # malformed or display-sparse row therefore receives a generic cue
    # rather than leaking its IDs into the prompt.
    fallback = "Choice" if choice_ids else "Continue"
    if isinstance(row, Mapping):
        for key in _CUE_FIELDS:
            cue = _string(row.get(key))
            if cue:
                return _bounded_cue(cue, fallback)
        metadata = row.get("metadata")
        if isinstance(metadata, Mapping):
            for key in _CUE_FIELDS:
                cue = _string(metadata.get(key))
                if cue:
                    return _bounded_cue(cue, fallback)
    return fallback


def _rows(value: Any) -> list[Any]:
    """Normalize an authority list while retaining no mutable source object."""

    if value is None:
        return []
    if isinstance(value, Mapping):
        # A single typed row is different from a map keyed by choice ID.
        if any(key in value for key in _ID_FIELDS) or any(key in value for key in ("choice_ids", "bundle")):
            return [value]
        for key in ("options", "choices", "allowed_values", "values", "items", "ids"):
            if key in value:
                return _rows(value[key])
        # Linkage maps are commonly keyed by canonical IDs.  The key itself is
        # authority; a value may supply only typed presentation metadata.
        return [
            ({"id": str(key), **(dict(item) if isinstance(item, Mapping) else {})})
            for key, item in value.items()
            if isinstance(key, (str, int)) and not isinstance(key, bool)
        ]
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


@dataclass(frozen=True)
class _Candidate:
    choice_ids: tuple[str, ...]
    cue: str
    kind: str = OPTION_PICK

    def __post_init__(self) -> None:
        ids = tuple(self.choice_ids)
        if self.kind not in OPTION_KINDS:
            _error("DCC_LINEAR_OPTION_KIND", "Unsupported linear option kind.")
        if self.kind == OPTION_NONE:
            if ids:
                _error("DCC_LINEAR_OPTION_NONE", "A none option cannot commit a choice.")
        elif not ids:
            _error("DCC_LINEAR_OPTION_EMPTY", "A selectable option must commit at least one choice.")
        if len(ids) != len(set(ids)) or any(not isinstance(value, str) or not value for value in ids):
            _error("DCC_LINEAR_OPTION_IDS", "Option choice IDs must be distinct, non-empty strings.")
        if not isinstance(self.cue, str) or not self.cue or len(self.cue) > MAX_CUE_LENGTH:
            _error("DCC_LINEAR_OPTION_CUE", "An option cue must be a bounded non-empty string.")


def _candidate(row: Any) -> _Candidate | None:
    if isinstance(row, Mapping) and isinstance(row.get("choice_ids"), (list, tuple)):
        ids = tuple(value for value in row["choice_ids"] if isinstance(value, str) and value)
        if not ids:
            return None
        kind = row.get("kind") if row.get("kind") in OPTION_KINDS else (OPTION_BUNDLE if len(ids) > 1 else OPTION_PICK)
        return _Candidate(ids, _cue(row, ids), kind)
    if isinstance(row, Mapping) and isinstance(row.get("bundle"), (list, tuple)):
        ids = tuple(value for value in row["bundle"] if isinstance(value, str) and value)
        if not ids:
            return None
        return _Candidate(ids, _cue(row, ids), OPTION_BUNDLE)
    choice_id = _choice_id(row)
    if choice_id is None:
        return None
    kind = row.get("kind") if isinstance(row, Mapping) and row.get("kind") in OPTION_KINDS else OPTION_PICK
    return _Candidate((choice_id,), _cue(row, (choice_id,)), kind)


def _candidate_sort_key(candidate: _Candidate) -> tuple[str, str, str]:
    # Explicit stop choices are always presented after legal picks.  They are
    # still part of the deterministic set and never make a required first pick
    # look skippable.
    return ("\uffff" if candidate.kind == OPTION_NONE else "\x00", "\x1f".join(candidate.choice_ids), candidate.cue)


def _allowed_ids(value: Any) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        if any(key in value for key in ("allowed_values", "ids", "choices", "values")):
            for key in ("allowed_values", "ids", "choices", "values"):
                if key in value:
                    return _allowed_ids(value[key])
        # A map from ID to typed restrictions is an explicit set of IDs.
        return {str(key) for key in value if isinstance(key, (str, int)) and not isinstance(key, bool)}
    if isinstance(value, (list, tuple, set, frozenset)):
        values: set[str] = set()
        for row in value:
            candidate = _candidate(row)
            if candidate is not None:
                values.update(candidate.choice_ids)
            else:
                scalar = _choice_id(row)
                if scalar is not None:
                    values.add(scalar)
        return values
    scalar = _choice_id(value)
    return {scalar} if scalar is not None else set()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _container(request: Any, envelope: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    return _mapping(request), _mapping(envelope)


def _first(request: Any, envelope: Any, *keys: str) -> Any:
    request_map, envelope_map = _container(request, envelope)
    for container in (envelope_map, request_map):
        for key in keys:
            if key in container:
                return container[key]
    return None


def _slot_rows(request: Any, envelope: Any, slot_id: str) -> tuple[list[Any], bool]:
    request_map, envelope_map = _container(request, envelope)
    found = False
    values: list[Any] = []
    for container in (envelope_map, request_map):
        for key in ("choices_by_slot", "allowed_choices_by_slot", "allowed_high_level", "choices", "choice_catalogue"):
            slots = container.get(key)
            if not isinstance(slots, Mapping) or slot_id not in slots:
                continue
            found = True
            values.extend(_rows(slots.get(slot_id)))
            break
    return values, found


def _slot_allowed(request: Any, envelope: Any, slot_id: str) -> set[str] | None:
    request_map, envelope_map = _container(request, envelope)
    found = False
    result: set[str] = set()
    for container in (envelope_map, request_map):
        for key in ("allowed_choices_by_slot", "allowed_choice_ids_by_slot"):
            slots = container.get(key)
            if isinstance(slots, Mapping) and slot_id in slots:
                found = True
                result.update(_allowed_ids(slots.get(slot_id)) or set())
    return result if found else None


def _authority_candidates(request: Any, envelope: Any, slot_id: str) -> list[_Candidate]:
    rows, found = _slot_rows(request, envelope, slot_id)
    allowed = _slot_allowed(request, envelope, slot_id)
    if not found:
        return []
    result: dict[tuple[str, ...], _Candidate] = {}
    for row in rows:
        candidate = _candidate(row)
        if candidate is None:
            continue
        if allowed is not None and not set(candidate.choice_ids) <= allowed:
            continue
        result.setdefault(candidate.choice_ids, candidate)
    return sorted(result.values(), key=_candidate_sort_key)


def _selection_limits(request: Any, envelope: Any, slot_id: str, *, default_min: int = 1, default_max: int | None = None) -> tuple[int, int, bool]:
    raw = _first(request, envelope, "selection_limits_by_slot", "selection_limits")
    row = raw.get(slot_id) if isinstance(raw, Mapping) else None
    row = row if isinstance(row, Mapping) else {}
    minimum = row.get("final_min", row.get("min_choices", row.get("owner_lock_min", default_min)))
    maximum = row.get("final_max", row.get("max_choices", row.get("owner_lock_max", default_max)))
    if type(minimum) is not int or minimum < 0:
        minimum = default_min
    if maximum is None:
        maximum = default_max if default_max is not None else max(minimum, 1)
    if type(maximum) is not int or maximum < minimum:
        maximum = max(minimum, 1)
    allow_none = row.get("allow_none") if isinstance(row.get("allow_none"), bool) else minimum == 0
    return minimum, maximum, allow_none


# Read-only dict views of recent immutable states: the menu builders read the
# state ~20k times per walk and each read deep-copied it (8 s per walk).
# Keyed by object identity, verified against the stored object.
_STATE_VIEW_CACHE: dict[int, tuple["CommittedState", dict[str, Any]]] = {}


def _state_mapping(committed: Any) -> Mapping[str, Any]:
    if isinstance(committed, CommittedState):
        cached = _STATE_VIEW_CACHE.get(id(committed))
        if cached is not None and cached[0] is committed:
            return cached[1]
        view = committed.to_dict()
        if len(_STATE_VIEW_CACHE) >= 8:
            _STATE_VIEW_CACHE.pop(next(iter(_STATE_VIEW_CACHE)))
        _STATE_VIEW_CACHE[id(committed)] = (committed, view)
        return view
    if isinstance(committed, Mapping):
        return committed
    return {}


_SAME_CL = object()  # training rows share the causal CL cut unless a caller says otherwise


def _committed_training_ids(
    committed: Any,
    *,
    max_cl: int | None = None,
) -> tuple[set[str], set[str]]:
    """Return trained Spheres and Talents visible at an effective CL.

    The creation-training contract contains future route records as well as
    committed selections. Menu legality reads only walk state and, when a
    causal CL is supplied, excludes rows acquired after that CL. With the
    default ``None`` all committed rows remain visible for duplicate checks.
    """

    state = _state_mapping(committed)
    spheres: set[str] = set()
    talents: set[str] = set()
    rows = state.get("trained_choices")
    if not isinstance(rows, (list, tuple)):
        return spheres, talents
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if max_cl is not None:
            row_cl = row.get("cl")
            if type(row_cl) is not int or row_cl > max_cl:
                continue
        record_id = row.get("record_id")
        choice_type = row.get("choice_type")
        if not isinstance(record_id, str) or not record_id:
            continue
        if choice_type == "new_sphere":
            spheres.add(record_id)
            bonus_id = row.get("bonus_talent_id")
            if isinstance(bonus_id, str) and bonus_id:
                talents.add(bonus_id)
        elif choice_type == "known_sphere_talent":
            talents.add(record_id)
    return spheres, talents


def _committed_acquired_talent_ids(committed: Any) -> set[str]:
    """Return committed Talent IDs across free, ordinary, and training lanes."""

    state = _state_mapping(committed)
    _trained_spheres, talents = _committed_training_ids(committed)
    for row in state.get("pairs") or ():
        if isinstance(row, Mapping) and isinstance(row.get("talent_id"), str) and row["talent_id"]:
            talents.add(row["talent_id"])
    ordinary = state.get("ordinary_by_cl")
    if isinstance(ordinary, Mapping):
        talents.update(value for value in ordinary.values() if isinstance(value, str) and value)
    return talents


def _state_slot(committed: Any, slot_id: str) -> list[str]:
    state = _state_mapping(committed)
    slots = state.get("by_slot")
    if not isinstance(slots, Mapping):
        return []
    values = slots.get(slot_id) or []
    return [value for value in values if isinstance(value, str)] if isinstance(values, (list, tuple)) else []


def _owner_locks(request: Any, envelope: Any) -> Mapping[str, Any]:
    raw = _first(request, envelope, "owner_locks")
    if not isinstance(raw, Mapping):
        return {}
    by_slot = raw.get("by_slot")
    return by_slot if isinstance(by_slot, Mapping) else raw


def owner_lock_for(request: Any, envelope: Any, slot_id: str) -> Any:
    """Return a frozen owner lock, or a private sentinel when absent."""

    locks = _owner_locks(request, envelope)
    value = locks.get(slot_id, _MISSING)
    if value is _MISSING:
        return _MISSING
    # The production delegated envelope publishes an empty ``by_slot`` row
    # for every unresolved slot.  The delegated validator skips every empty
    # row (``if not locked_ids: continue``): an empty row is not a lock, and
    # the slot stays open to the model.  ``zero_owner_path_locks_are_legal``
    # only records whether the owner locked any Path; it was previously
    # misread as the switch for this rule, so the first real walk on a
    # project with owner-locked Paths skipped Background, Origin, Method,
    # Foundation and Sphere priorities outright and was rejected.
    if value in (None, [], (), {}):
        return _MISSING
    return value


def is_owner_locked(request: Any, envelope: Any, slot_id: str) -> bool:
    """Whether the frozen envelope owns this slot before the model walk."""

    return owner_lock_for(request, envelope, slot_id) is not _MISSING


def _lock_values(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        for key in ("choice_ids", "choices", "value", "id", "selected"):
            if key in value:
                return _lock_values(value[key])
        return []
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str) and item]
    return [value] if isinstance(value, str) and value else []


def _request_digest(request: Any) -> str:
    value = _mapping(request).get("request_sha256")
    return value if isinstance(value, str) and len(value) == 64 else canonical_sha256(request if request is not None else {})


def _envelope_digest(envelope: Any) -> str:
    value = _mapping(envelope).get("delegated_choice_envelope_sha256", _mapping(envelope).get("envelope_sha256"))
    return value if isinstance(value, str) and len(value) == 64 else canonical_sha256(envelope if envelope is not None else {})


def _state_digest(committed: Any) -> str:
    if isinstance(committed, CommittedState):
        return committed.committed_sha256
    value = _mapping(committed).get("committed_sha256")
    if isinstance(value, str) and len(value) == 64:
        return value
    return canonical_sha256(committed if committed is not None else CommittedState.empty().to_dict())


def _authority_digest(request: Any, envelope: Any, committed: Any, step_id: str, page: int, ordinal: int) -> str:
    return domain_digest(
        "dcc.linear.menu.authority.v1",
        {
            "request_sha256": _request_digest(request),
            "envelope_sha256": _envelope_digest(envelope),
            "committed_sha256": _state_digest(committed),
            "step_id": step_id,
            "page": page,
            "ordinal": ordinal,
        },
    )


def _page_slice(candidates: Sequence[_Candidate], page: int, max_pages: int = MAX_PAGES_PER_STEP) -> tuple[list[_Candidate], bool, int]:
    if type(max_pages) is not int or max_pages < 1:
        max_pages = MAX_PAGES_PER_STEP
    if type(page) is not int or page < 1 or page > max_pages:
        _error("DCC_LINEAR_PAGE_LIMIT", "A linear step page is outside the allowed range.", details={"page": page})
    total = len(candidates)
    start = 0
    remaining = total
    for _ in range(1, page):
        size = 11 if remaining > MAX_OPTIONS_PER_PAGE else MAX_OPTIONS_PER_PAGE
        start += size
        remaining -= size
    if start >= total and total:
        _error("DCC_LINEAR_PAGE_EMPTY", "A linear step page has no legal continuation.", details={"page": page})
    size = 11 if remaining > MAX_OPTIONS_PER_PAGE else MAX_OPTIONS_PER_PAGE
    if page == max_pages and remaining > MAX_OPTIONS_PER_PAGE:
        # More candidates than three pages can hold.  Serve the last pageful and
        # end pagination rather than failing the walk: a step whose menu is
        # merely wider than the display ceiling is still a legal step, and
        # refusing it stranded an otherwise complete character (observed at
        # creation_training:2:2 with 37 and item_priorities:4 with 48).  The
        # caller advances once no continuation is offered.
        visible = list(candidates[start : start + MAX_OPTIONS_PER_PAGE])
        return visible, False, start
    visible = list(candidates[start : start + size])
    has_next = start + len(visible) < total
    return visible, has_next, start


# ---------------------------------------------------------------------------
# Concept relevance: menus list options that fit the character's concept first.
# Legality is unchanged; only the order the model sees.

_CONCEPT_STOP = frozenset("""a an and are as at be by for from her his its of on or that the their them they this
to was who whose with who while into over under through fighting fights fight cultivator cultivation
character someone person one uses using sect sects clan clans""".split())
_CONCEPT_SYNONYMS = {
    "toxin": "poiso", "toxic": "poiso", "venom": "poiso", "venomo": "poiso",
    "alche": "alche", "pill": "alche", "elixi": "alche", "brewe": "alche",
    "sword": "blade", "blade": "blade", "saber": "blade",
    "lightn": "thund", "storm": "thund", "shado": "shado", "stealt": "shado",
    "ghost": "death", "corps": "death", "grave": "death", "undea": "death",
    "flame": "fire", "burn": "fire", "frost": "ice", "snow": "ice",
}
_PATH_THEMES = {
    "tianxia.path.body_refining": "body fist fists strength muscle warrior martial blade sword spear iron bone blood brawler hunter soldier bodyguard",
    "tianxia.path.qi_cultivation": "qi alchemy alchemist poison toxin pill formation talisman fire flame thunder lightning frost ice element elemental scholar array smith",
    "tianxia.path.spirit_awakening": "spirit soul mind dream illusion ghost ancestor ancestors music song fate karma divination shaman medium monk prayer",
}
# Keyed by the sealed envelope and request hashes, so no parsed request is
# kept alive after its walk (holding five envelopes pinned gigabytes).
_CONCEPT_INDEX_CACHE: dict[tuple[Any, ...], dict[str, str]] = {}


def _stems(text: str) -> set[str]:
    stems: set[str] = set()
    for word in re.findall(r"[a-z]+", text.lower()):
        if len(word) < 4 or word in _CONCEPT_STOP:
            continue
        stem = word[:5]
        stems.add(_CONCEPT_SYNONYMS.get(word[:6], _CONCEPT_SYNONYMS.get(stem, stem)))
    return stems


def _concept_stems(request: Any, envelope: Any, committed: Any) -> set[str]:
    identity = _mapping(_mapping(_state_mapping(committed).get("bounded")).get("identity"))
    concept = identity.get("concept") if isinstance(identity.get("concept"), str) else ""
    if not concept:
        request_map = _mapping(request)
        for source in (request_map, _mapping(request_map.get("stage1_prompt"))):
            value = source.get("concept")
            if isinstance(value, str) and value.strip():
                concept = value
                break
    return _stems(concept) if concept else set()


def _concept_text_index(request: Any, envelope: Any) -> dict[str, str]:
    """choice_id -> name and description, built once per frozen envelope."""
    request_map, envelope_map = _container(request, envelope)
    envelope_sha = envelope_map.get("envelope_sha256")
    request_sha = request_map.get("request_sha256")
    cache_key = (envelope_sha, request_sha) if isinstance(envelope_sha, str) and isinstance(request_sha, str) else None
    if cache_key is not None and cache_key in _CONCEPT_INDEX_CACHE:
        return _CONCEPT_INDEX_CACHE[cache_key]
    index: dict[str, str] = {}
    for slots in (envelope_map.get("choices_by_slot"), request_map.get("choices_by_slot")):
        if not isinstance(slots, Mapping):
            continue
        for rows in slots.values():
            for row in _rows(rows):
                choice_id = _choice_id(row)
                if isinstance(choice_id, str) and choice_id not in index and isinstance(row, Mapping):
                    index[choice_id] = f"{row.get('name') or ''} {str(row.get('description') or '')[:600]}"
    for path_id, words in _PATH_THEMES.items():
        index[path_id] = f"{index.get(path_id, '')} {words}"
    if cache_key is not None:
        if len(_CONCEPT_INDEX_CACHE) > 4:
            _CONCEPT_INDEX_CACHE.clear()
        _CONCEPT_INDEX_CACHE[cache_key] = index
    return index


def _concept_score(concept: set[str], index: Mapping[str, str], candidate: "_Candidate") -> int:
    if not concept or not candidate.choice_ids:
        return 0
    text = candidate.cue + " " + " ".join(index.get(choice_id, "") for choice_id in candidate.choice_ids)
    score = len(concept & _stems(text))
    # A Sphere named for the concept (Poison for a poisoner) outweighs passing
    # mentions in other Spheres' Talent text.
    for choice_id in candidate.choice_ids:
        if isinstance(choice_id, str) and choice_id.startswith("tianxia.sphere."):
            score += 2 * len(concept & _stems(choice_id.rsplit(".", 1)[-1].replace("_", " ")))
    return score


_PATH_CHECKED_STEPS = {"sphere_route", "sphere_free_talent_pair", "ordinary_talent", "sphere_priorities", "creation_training_route",
                       "creation_training", "path_progression", "insight_occurrence"}


def _path_legal(request: Any, envelope: Any, committed: Any, step_kind: str, candidates: Sequence[_Candidate], minimum: int) -> list[_Candidate]:
    """Drop the options the character's Path cannot take (owner 2026-09-27; factory_authoring/path_access.py): a Sphere
    its Path is not listed for, and, for a Body Refining character, a technique that projects Qi beyond the body. When
    that would leave a required menu empty, the menu stays as it was: a character is never stranded mid-build."""
    if step_kind not in _PATH_CHECKED_STEPS and not step_kind.startswith(("creation_training", "sphere_")):
        return list(candidates)
    paths = [value for value in _state_mapping(committed).get("by_slot", {}).get("path_choice", []) if isinstance(value, str)]
    if not paths:
        return list(candidates)
    from factory_authoring.path_access import blocked

    routes = {route_id: sphere_id for row in _route_modules(request, envelope)
              if (route_id := _route_id(row)) and (sphere_id := _route_sphere_id(row))}
    kept = [candidate for candidate in candidates if not any(blocked(choice, paths, routes) for choice in candidate.choice_ids)]
    if minimum >= 1 and not any(candidate.kind != OPTION_NONE for candidate in kept) and any(candidate.kind != OPTION_NONE for candidate in candidates):
        return list(candidates)
    return kept


def _make_menu(
    request: Any,
    envelope: Any,
    committed: Any,
    *,
    step_id: str,
    step_kind: str,
    ordinal: int,
    minimum: int,
    maximum: int,
    candidates: Sequence[_Candidate],
    page: int,
    title: str | None = None,
    preserve_candidate_order: bool = False,
    concept_ranked_order: bool = False,
    max_pages: int = MAX_PAGES_PER_STEP,
) -> "StepMenu | None":
    if not isinstance(step_id, str) or not step_id:
        _error("DCC_LINEAR_STEP_ID", "A linear step ID is required.")
    if step_kind not in STEP_KINDS:
        _error("DCC_LINEAR_STEP_KIND", "Unsupported linear step kind.")
    if type(ordinal) is not int or ordinal < 1 or ordinal > MAX_WALK_STEPS:
        _error("DCC_LINEAR_STEP_LIMIT", "A linear step ordinal exceeds the walk ceiling.")
    if type(minimum) is not int or type(maximum) is not int or minimum < 0 or maximum < minimum:
        _error("DCC_LINEAR_CARDINALITY", "Linear step cardinality is invalid.")
    candidates = _path_legal(request, envelope, committed, step_kind, candidates, minimum)
    # ``concept_ranked_order`` keeps the caller's order (for example best
    # treasure grade first) as the tie-break under concept ranking.
    ordered = list(candidates) if preserve_candidate_order or concept_ranked_order else sorted(candidates, key=_candidate_sort_key)
    if step_kind == "background_ability":
        priority = _ability_priority(committed, request, envelope)
        ordered.sort(key=lambda candidate: priority.index(candidate.choice_ids[0])
                     if candidate.choice_ids and candidate.choice_ids[0] in priority else len(priority))
        preserve_candidate_order = True
    concept = set() if preserve_candidate_order or step_kind == "identity" else _concept_stems(request, envelope, committed)
    if concept and len(ordered) > 1:
        index = _concept_text_index(request, envelope)
        scores = {id(candidate): _concept_score(concept, index, candidate) for candidate in ordered}
        # Stable: concept matches first, the canonical order within ties.
        ordered.sort(key=lambda candidate: -scores[id(candidate)])
    if not preserve_candidate_order and step_kind != "identity":
        from character_creation.concept_index import recommendation_scores

        semantic_scores = recommendation_scores(_mapping(request))
        if semantic_scores:
            ordered.sort(key=lambda candidate: -max(
                (semantic_scores.get(choice_id, -1000) for choice_id in candidate.choice_ids),
                default=-1000,
            ))
    visible, has_next, absolute_start = _page_slice(ordered, page, max_pages)
    authority_sha256 = _authority_digest(request, envelope, committed, step_id, page, ordinal)
    options: list[StepOption] = []
    for local_position, candidate in enumerate(visible):
        absolute_position = absolute_start + local_position
        option_id = derive_option_id(
            authority_sha256,
            canonical_sha256({"position": absolute_position, "choice_ids": list(candidate.choice_ids)}),
            "DCC_LINEAR_STEP",
            step_id,
        )
        options.append(StepOption(option_id, candidate.choice_ids, candidate.cue, candidate.kind))
    next_page_id = f"{step_id}:page:{page + 1}" if has_next else None
    if has_next:
        # A continuation carries no mechanics.  It is represented as a none
        # option to keep the v1 option vocabulary exact; the walk recognizes
        # it by the empty choice_ids plus next_page_id on this menu.
        continuation_id = derive_option_id(
            authority_sha256,
            canonical_sha256({"position": absolute_start + len(visible), "continuation": next_page_id}),
            "DCC_LINEAR_STEP",
            f"{step_id}:next:{page}",
        )
        options.append(StepOption(continuation_id, (), "More options", OPTION_NONE))
    return StepMenu(
        step_id=step_id,
        step_kind=step_kind,
        ordinal=ordinal,
        title=title or STEP_TITLES[step_kind],
        min_choices=minimum,
        max_choices=maximum,
        options=tuple(options),
        page_id=f"{step_id}:page:{page}",
        next_page_id=next_page_id,
        authority_sha256=authority_sha256,
    )


@dataclass(frozen=True)
class StepOption:
    """One opaque model-visible option and the typed IDs it commits."""

    option_id: str
    choice_ids: tuple[str, ...] = ()
    cue: str = "Continue"
    kind: str = OPTION_PICK

    def __post_init__(self) -> None:
        if not isinstance(self.option_id, str) or not self.option_id.startswith("dcc.opt."):
            _error("DCC_LINEAR_OPTION_ID", "A step option ID must be an opaque dcc.opt identifier.")
        ids = tuple(self.choice_ids)
        object.__setattr__(self, "choice_ids", ids)
        if self.kind not in OPTION_KINDS:
            _error("DCC_LINEAR_OPTION_KIND", "Unsupported linear option kind.")
        if self.kind == OPTION_NONE and ids:
            _error("DCC_LINEAR_OPTION_NONE", "A none option cannot commit a choice.")
        if self.kind != OPTION_NONE and not ids:
            _error("DCC_LINEAR_OPTION_EMPTY", "A selectable option must commit a choice.")
        if len(ids) != len(set(ids)) or any(not isinstance(value, str) or not value for value in ids):
            _error("DCC_LINEAR_OPTION_IDS", "Option choice IDs must be distinct, non-empty strings.")
        if not isinstance(self.cue, str) or not self.cue or len(self.cue) > MAX_CUE_LENGTH:
            _error("DCC_LINEAR_OPTION_CUE", "An option cue must be a bounded non-empty string.")

    @property
    def is_continuation(self) -> bool:
        return self.kind == OPTION_NONE and not self.choice_ids and self.cue == "More options"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": LINEAR_OPTION_SCHEMA,
            "option_id": self.option_id,
            "choice_ids": list(self.choice_ids),
            "cue": self.cue,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class StepMenu:
    """A self-hashed, bounded page of options for one walk step."""

    step_id: str
    step_kind: str
    ordinal: int
    title: str
    min_choices: int
    max_choices: int
    options: tuple[StepOption, ...]
    page_id: str
    next_page_id: str | None = None
    authority_sha256: str = ""
    menu_sha256: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.step_id, str) or not self.step_id:
            _error("DCC_LINEAR_STEP_ID", "A menu step ID must be non-empty.")
        if self.step_kind not in STEP_KINDS:
            _error("DCC_LINEAR_STEP_KIND", "Unsupported linear step kind.")
        if type(self.ordinal) is not int or not 1 <= self.ordinal <= MAX_WALK_STEPS:
            _error("DCC_LINEAR_STEP_LIMIT", "A menu ordinal is outside the walk ceiling.")
        if type(self.min_choices) is not int or type(self.max_choices) is not int or not 0 <= self.min_choices <= self.max_choices:
            _error("DCC_LINEAR_CARDINALITY", "A menu cardinality is invalid.")
        options = tuple(self.options)
        object.__setattr__(self, "options", options)
        if not 1 <= len(options) <= MAX_OPTIONS_PER_PAGE:
            _error("DCC_LINEAR_OPTION_LIMIT", "A menu page must contain between one and twelve options.")
        option_ids = [option.option_id for option in options]
        if len(option_ids) != len(set(option_ids)):
            _error("DCC_LINEAR_OPTION_DUPLICATE", "Menu option IDs must be unique.")
        if not isinstance(self.page_id, str) or not self.page_id:
            _error("DCC_LINEAR_PAGE_ID", "A menu page ID must be non-empty.")
        if self.next_page_id is not None and (not isinstance(self.next_page_id, str) or not self.next_page_id or self.next_page_id == self.page_id):
            _error("DCC_LINEAR_PAGE_ID", "A continuation page ID is invalid.")
        continuation = [option for option in options if option.is_continuation]
        if continuation and self.next_page_id is None:
            _error("DCC_LINEAR_PAGE_CONTINUATION", "A continuation option requires a next page.")
        if self.next_page_id is not None and len(continuation) != 1:
            _error("DCC_LINEAR_PAGE_CONTINUATION", "A paged menu must have one continuation option.")
        unsigned = self._unsigned_dict()
        expected = canonical_sha256(unsigned)
        if self.menu_sha256:
            if self.menu_sha256 != expected:
                _error("DCC_LINEAR_MENU_HASH", "A menu self-hash does not match its contents.")
        else:
            object.__setattr__(self, "menu_sha256", expected)

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": LINEAR_MENU_SCHEMA,
            "step_id": self.step_id,
            "step_kind": self.step_kind,
            "ordinal": self.ordinal,
            "title": self.title,
            "min_choices": self.min_choices,
            "max_choices": self.max_choices,
            "options": [option.to_dict() for option in self.options],
            "page_id": self.page_id,
            "next_page_id": self.next_page_id,
            "authority_sha256": self.authority_sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._unsigned_dict(), "menu_sha256": self.menu_sha256}

    @property
    def option_ids(self) -> tuple[str, ...]:
        return tuple(option.option_id for option in self.options)

    @property
    def continuation_option_id(self) -> str | None:
        for option in self.options:
            if option.is_continuation:
                return option.option_id
        return None


@dataclass(frozen=True)
class CommittedState:
    """Immutable-by-convention state retained by the pure walk engine."""

    by_slot: Mapping[str, Sequence[str]] = field(default_factory=dict)
    pairs: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    ordinary_by_cl: Mapping[str, str] = field(default_factory=dict)
    insight_occurrences: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    bounded: Mapping[str, Any] = field(default_factory=dict)
    route_id: str | None = None
    committed_sha256: str = ""
    trained_choices: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    trained_choice_skips: Sequence[int] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        slots = {
            str(slot): [value for value in values if isinstance(value, str)]
            for slot, values in (self.by_slot.items() if isinstance(self.by_slot, Mapping) else [])
            if isinstance(slot, str) and isinstance(values, (list, tuple))
        }
        ordinary = {
            str(cl): value
            for cl, value in (self.ordinary_by_cl.items() if isinstance(self.ordinary_by_cl, Mapping) else [])
            if isinstance(value, str)
        }
        pairs = [deepcopy(row) for row in self.pairs if isinstance(row, Mapping)] if isinstance(self.pairs, (list, tuple)) else []
        occurrences = [deepcopy(row) for row in self.insight_occurrences if isinstance(row, Mapping)] if isinstance(self.insight_occurrences, (list, tuple)) else []
        bounded = deepcopy(dict(self.bounded)) if isinstance(self.bounded, Mapping) else {}
        trained_choices = [deepcopy(row) for row in self.trained_choices if isinstance(row, Mapping)] if isinstance(self.trained_choices, (list, tuple)) else []
        trained_choice_skips = sorted({value for value in self.trained_choice_skips if type(value) is int and value >= 1}) if isinstance(self.trained_choice_skips, (list, tuple, set, frozenset)) else []
        object.__setattr__(self, "by_slot", slots)
        object.__setattr__(self, "ordinary_by_cl", ordinary)
        object.__setattr__(self, "pairs", pairs)
        object.__setattr__(self, "insight_occurrences", occurrences)
        object.__setattr__(self, "bounded", bounded)
        object.__setattr__(self, "trained_choices", trained_choices)
        object.__setattr__(self, "trained_choice_skips", trained_choice_skips)
        if self.route_id is not None and not isinstance(self.route_id, str):
            _error("DCC_LINEAR_ROUTE_ID", "route_id must be a string or null.")
        expected = canonical_sha256(self._unsigned_dict())
        if self.committed_sha256:
            if self.committed_sha256 != expected:
                _error("DCC_LINEAR_STATE_HASH", "Committed state self-hash does not match its contents.")
        else:
            object.__setattr__(self, "committed_sha256", expected)

    @classmethod
    def empty(cls) -> "CommittedState":
        return cls()

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": LINEAR_STATE_SCHEMA,
            "by_slot": {slot: list(values) for slot, values in sorted(self.by_slot.items())},
            "pairs": deepcopy(list(self.pairs)),
            "ordinary_by_cl": {cl: value for cl, value in sorted(self.ordinary_by_cl.items())},
            "insight_occurrences": deepcopy(list(self.insight_occurrences)),
            "bounded": deepcopy(dict(self.bounded)),
            "route_id": self.route_id,
            "trained_choices": deepcopy(list(self.trained_choices)),
            "trained_choice_skips": list(self.trained_choice_skips),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._unsigned_dict(), "committed_sha256": self.committed_sha256}

    def with_slot(self, slot_id: str, values: Sequence[str]) -> "CommittedState":
        if not isinstance(slot_id, str) or not slot_id:
            _error("DCC_LINEAR_SLOT_ID", "A committed slot ID must be non-empty.")
        ids = [value for value in values if isinstance(value, str) and value]
        if len(ids) != len(set(ids)):
            _error("DCC_LINEAR_COMMIT_DUPLICATE", "A committed slot cannot contain duplicate IDs.")
        slots = {key: list(value) for key, value in self.by_slot.items()}
        slots[slot_id] = ids
        return CommittedState(slots, self.pairs, self.ordinary_by_cl, self.insight_occurrences, self.bounded, self.route_id, trained_choices=self.trained_choices, trained_choice_skips=self.trained_choice_skips)

    def with_choice(self, slot_id: str, choice_ids: Sequence[str]) -> "CommittedState":
        current = list(self.by_slot.get(slot_id, []))
        for choice_id in choice_ids:
            if not isinstance(choice_id, str) or not choice_id:
                _error("DCC_LINEAR_COMMIT_ID", "A committed choice ID must be a non-empty string.")
            if choice_id in current:
                _error("DCC_LINEAR_COMMIT_DUPLICATE", "A choice cannot be committed twice in one slot.")
            current.append(choice_id)
        return self.with_slot(slot_id, current)

    def with_bounded(self, key: str, value: Any) -> "CommittedState":
        if not isinstance(key, str) or not key:
            _error("DCC_LINEAR_BOUNDED_KEY", "A bounded field key must be non-empty.")
        bounded = deepcopy(dict(self.bounded))
        bounded[key] = deepcopy(value)
        return CommittedState(self.by_slot, self.pairs, self.ordinary_by_cl, self.insight_occurrences, bounded, self.route_id, trained_choices=self.trained_choices, trained_choice_skips=self.trained_choice_skips)

    def with_point_buy_preset(self, preset: Mapping[str, Any]) -> "CommittedState":
        """Retain the typed preset selected before a possible assignment step."""

        if not isinstance(preset, Mapping):
            _error("DCC_LINEAR_POINT_BUY_PRESET", "A point-buy preset must be typed object data.")
        return self.with_bounded("point_buy_preset", deepcopy(dict(preset)))

    def with_ability_scores(self, scores: Mapping[str, Any]) -> "CommittedState":
        """Commit the final bounded six-ability score map."""

        if not isinstance(scores, Mapping):
            _error("DCC_LINEAR_ABILITY_SCORES", "Ability scores must be typed object data.")
        return self.with_bounded("ability_scores", deepcopy(dict(scores)))

    def with_ability_score_changes(self, milestone_id: str, deltas: Mapping[str, Any]) -> "CommittedState":
        """Commit one typed ASI resolution under its frozen milestone ID."""

        if not isinstance(milestone_id, str) or not milestone_id or not isinstance(deltas, Mapping):
            _error("DCC_LINEAR_ASI", "An ASI resolution requires a milestone ID and typed deltas.")
        changes = deepcopy(dict(self.bounded.get("ability_score_changes_by_milestone_id") or {}))
        if milestone_id in changes:
            prior = changes[milestone_id]
            if prior != deltas and prior != {"deltas": dict(deltas)}:
                _error("DCC_LINEAR_ASI_CONFLICT", "An ASI milestone cannot be replaced.")
            return self
        changes[milestone_id] = {"deltas": deepcopy(dict(deltas))}
        return self.with_bounded("ability_score_changes_by_milestone_id", changes)

    def with_milestone_branch(self, milestone_id: str, branch: str) -> "CommittedState":
        """Commit which printed resolution one level milestone takes.

        The printed *Ability Score Improvement or Cultivation Insight* feature is
        a choice at each of its levels, so the walk records the branch
        (``ability_score_increase`` or ``cultivation_insight``) before the branch
        menu asks its detail question.  Transient walk fact, keyed by the frozen
        milestone ID and holding a plain branch name, so it survives a walk
        snapshot's commit and reload.
        """

        if not isinstance(milestone_id, str) or not milestone_id or branch not in MILESTONE_BRANCHES:
            _error("DCC_LINEAR_MILESTONE_BRANCH", "A level milestone branch requires a milestone ID and one printed branch name.")
        branches = deepcopy(dict(self.bounded.get("advancement_milestone_branch_by_milestone_id") or {}))
        prior = branches.get(milestone_id)
        if prior is not None and prior != branch:
            _error("DCC_LINEAR_MILESTONE_BRANCH_CONFLICT", "A level milestone cannot switch to the other printed resolution.")
        branches[milestone_id] = branch
        return self.with_bounded("advancement_milestone_branch_by_milestone_id", branches)

    def with_path_progression(self, cl: str | int, path_id: str) -> "CommittedState":
        """Commit one exact frozen Path ID for an ambiguous CL."""

        if not isinstance(path_id, str) or not path_id:
            _error("DCC_LINEAR_PROGRESSION", "A path progression choice must be a non-empty Path ID.")
        progress = deepcopy(dict(self.bounded.get("path_progression_by_cl") or {}))
        key = str(cl)
        prior = progress.get(key)
        if prior is not None and prior != path_id:
            _error("DCC_LINEAR_PROGRESSION_CONFLICT", "A Path progression CL cannot be replaced.")
        if prior == path_id:
            _error("DCC_LINEAR_PROGRESSION_DUPLICATE", "A Path progression CL cannot be selected twice.")
        progress[key] = path_id
        return self.with_bounded("path_progression_by_cl", progress)

    def with_proficiency(self, field: str, owner_id: str, values: Sequence[str]) -> "CommittedState":
        """Commit one bounded starting-proficiency selection map entry."""

        if not isinstance(field, str) or not field or not isinstance(owner_id, str) or not owner_id:
            _error("DCC_LINEAR_PROFICIENCY", "A proficiency commitment requires typed field and owner IDs.")
        clean = [value for value in values if isinstance(value, str) and value]
        if len(clean) != len(set(clean)):
            _error("DCC_LINEAR_PROFICIENCY_DUPLICATE", "A proficiency field cannot repeat a value.")
        entries = deepcopy(dict(self.bounded.get(field) or {}))
        prior = entries.get(owner_id)
        if prior is not None:
            prior_values = [value for value in prior if isinstance(value, str)] if isinstance(prior, (list, tuple)) else []
            if clean[: len(prior_values)] != prior_values or len(clean) <= len(prior_values):
                _error("DCC_LINEAR_PROFICIENCY_CONFLICT", "A proficiency field cannot be replaced or selected twice.")
        entries[owner_id] = clean
        return self.with_bounded(field, entries)

    def with_pair(self, sphere_id: str, talent_id: str) -> "CommittedState":
        if not isinstance(sphere_id, str) or not sphere_id or not isinstance(talent_id, str) or not talent_id:
            _error("DCC_LINEAR_PAIR_ID", "A committed Sphere/free-Talent pair requires two typed IDs.")
        pair = {"sphere_id": sphere_id, "talent_id": talent_id}
        if any(
            isinstance(row, Mapping)
            and row.get("sphere_id") == sphere_id
            and row.get("talent_id") == talent_id
            for row in self.pairs
        ):
            _error("DCC_LINEAR_PAIR_DUPLICATE", "A Sphere/free-Talent pair cannot be committed twice.")
        if talent_id in _committed_acquired_talent_ids(self):
            _error("DCC_LINEAR_PAIR_DUPLICATE", "A free Talent cannot be committed after another acquisition lane.")
        return CommittedState(self.by_slot, [*self.pairs, pair], self.ordinary_by_cl, self.insight_occurrences, self.bounded, self.route_id, trained_choices=self.trained_choices, trained_choice_skips=self.trained_choice_skips)

    def with_route(self, route_id: str) -> "CommittedState":
        if not isinstance(route_id, str) or not route_id:
            _error("DCC_LINEAR_ROUTE_ID", "A committed route ID must be non-empty.")
        if self.route_id is not None and self.route_id != route_id:
            _error("DCC_LINEAR_ROUTE_CONFLICT", "A second route cannot replace the committed route.")
        return CommittedState(self.by_slot, self.pairs, self.ordinary_by_cl, self.insight_occurrences, self.bounded, route_id, trained_choices=self.trained_choices, trained_choice_skips=self.trained_choice_skips)

    def with_ordinary(self, cl: str | int, talent_id: str) -> "CommittedState":
        if not isinstance(talent_id, str) or not talent_id:
            _error("DCC_LINEAR_ORDINARY_ID", "A committed ordinary Talent ID must be non-empty.")
        key = str(cl)
        ordinary = dict(self.ordinary_by_cl)
        if key in ordinary and ordinary[key] != talent_id:
            _error("DCC_LINEAR_ORDINARY_CONFLICT", "An ordinary Talent CL already has a different commitment.")
        if talent_id in ordinary.values() and ordinary.get(key) != talent_id:
            _error("DCC_LINEAR_ORDINARY_DUPLICATE", "An ordinary Talent cannot be committed twice.")
        if ordinary.get(key) != talent_id and talent_id in _committed_acquired_talent_ids(self):
            _error("DCC_LINEAR_ORDINARY_DUPLICATE", "An ordinary Talent cannot be committed after another acquisition lane.")
        ordinary[key] = talent_id
        return CommittedState(self.by_slot, self.pairs, ordinary, self.insight_occurrences, self.bounded, self.route_id, trained_choices=self.trained_choices, trained_choice_skips=self.trained_choice_skips)

    def with_trained_choice(self, choice: Mapping[str, Any]) -> "CommittedState":
        """Commit one bounded constructed-training selection.

        Source and outcome are reconstructed from the sealed envelope during
        response assembly.  The walk state therefore stores only the stable
        selection and its required Sphere bonus ID; callers cannot supply an
        independent source proof through the controller state.
        """

        if not isinstance(choice, Mapping):
            _error("DCC_LINEAR_TRAINED_CHOICE", "A constructed training choice must be typed object data.")
        cl = choice.get("cl")
        slot = choice.get("slot")
        choice_type = choice.get("choice_type")
        record_id = choice.get("record_id")
        if type(cl) is not int or cl < 1 or type(slot) is not int or not 1 <= slot <= CREATION_TRAINING_MAX_PER_CL:
            _error("DCC_LINEAR_TRAINED_CHOICE", "A constructed training choice requires bounded CL and slot values.")
        if choice_type not in {"new_sphere", "known_sphere_talent"} or not isinstance(record_id, str) or not record_id:
            _error("DCC_LINEAR_TRAINED_CHOICE", "A constructed training choice requires a typed route and record ID.")
        acquired_talents = _committed_acquired_talent_ids(self)
        if choice_type == "known_sphere_talent" and record_id in acquired_talents:
            _error("DCC_LINEAR_TRAINED_CHOICE_DUPLICATE", "A constructed Talent cannot be selected after another acquisition lane.")
        if choice_type == "new_sphere":
            bonus_id = choice.get("bonus_talent_id")
            if not isinstance(bonus_id, str) or not bonus_id:
                _error("DCC_LINEAR_TRAINED_CHOICE", "A new Sphere choice requires its paired bonus Talent ID.")
            if bonus_id in acquired_talents:
                _error("DCC_LINEAR_TRAINED_CHOICE_DUPLICATE_BONUS", "A constructed Sphere bonus Talent cannot follow another acquisition lane.")
        elif "bonus_talent_id" in choice:
            _error("DCC_LINEAR_TRAINED_CHOICE", "A known-Sphere Talent choice cannot carry a Sphere bonus field.")
        if cl in self.trained_choice_skips:
            _error("DCC_LINEAR_TRAINED_CHOICE_SKIPPED", "A constructed-training CL already has an explicit stop.")
        rows = [deepcopy(dict(row)) for row in self.trained_choices]
        if any(row.get("record_id") == record_id for row in rows if isinstance(row, Mapping)):
            _error("DCC_LINEAR_TRAINED_CHOICE_DUPLICATE", "A constructed training record cannot be selected twice.")
        existing_bonus_ids = {
            row.get("bonus_talent_id")
            for row in rows
            if isinstance(row, Mapping) and isinstance(row.get("bonus_talent_id"), str)
        }
        existing_record_ids = {
            row.get("record_id")
            for row in rows
            if isinstance(row, Mapping) and isinstance(row.get("record_id"), str)
        }
        if choice_type == "new_sphere" and choice.get("bonus_talent_id") in existing_bonus_ids | existing_record_ids:
            _error("DCC_LINEAR_TRAINED_CHOICE_DUPLICATE_BONUS", "A constructed Sphere bonus Talent cannot be selected twice.")
        if choice_type == "known_sphere_talent" and record_id in existing_bonus_ids:
            _error("DCC_LINEAR_TRAINED_CHOICE_DUPLICATE_BONUS", "A constructed Talent cannot reuse an earlier Sphere bonus Talent.")
        prior = [row for row in rows if row.get("cl") == cl]
        if slot != len(prior) + 1:
            _error("DCC_LINEAR_TRAINED_CHOICE_SLOT", "Constructed training slots must be contiguous within each CL.")
        normalized = {"cl": cl, "slot": slot, "choice_type": choice_type, "record_id": record_id}
        if choice_type == "new_sphere":
            normalized["bonus_talent_id"] = choice["bonus_talent_id"]
        return CommittedState(
            self.by_slot,
            self.pairs,
            self.ordinary_by_cl,
            self.insight_occurrences,
            self.bounded,
            self.route_id,
            trained_choices=[*rows, normalized],
            trained_choice_skips=self.trained_choice_skips,
        )

    def with_trained_choice_skip(self, cl: int) -> "CommittedState":
        """Record an explicit legal decision to use fewer optional choices."""

        if type(cl) is not int or cl < 1:
            _error("DCC_LINEAR_TRAINED_CHOICE_SKIP", "A constructed-training skip requires a positive CL.")
        if cl in self.trained_choice_skips:
            _error("DCC_LINEAR_TRAINED_CHOICE_SKIP_DUPLICATE", "A constructed-training skip cannot be committed twice.")
        return CommittedState(
            self.by_slot,
            self.pairs,
            self.ordinary_by_cl,
            self.insight_occurrences,
            self.bounded,
            self.route_id,
            trained_choices=self.trained_choices,
            trained_choice_skips=[*self.trained_choice_skips, cl],
        )

    def with_insight_occurrence(self, occurrence: Mapping[str, Any]) -> "CommittedState":
        if not isinstance(occurrence, Mapping):
            _error("DCC_LINEAR_INSIGHT_OCCURRENCE", "An Insight occurrence must be typed object data.")
        insight_id = occurrence.get("insight_id")
        milestone_id = occurrence.get("milestone_id")
        if not isinstance(insight_id, str) or not insight_id or not isinstance(milestone_id, str) or not milestone_id:
            _error("DCC_LINEAR_INSIGHT_OCCURRENCE", "An Insight occurrence requires typed insight and milestone IDs.")
        if any(isinstance(row, Mapping) and row.get("milestone_id") == milestone_id for row in self.insight_occurrences):
            _error("DCC_LINEAR_INSIGHT_DUPLICATE", "A milestone Insight occurrence cannot be committed twice.")
        return CommittedState(self.by_slot, self.pairs, self.ordinary_by_cl, [*self.insight_occurrences, deepcopy(dict(occurrence))], self.bounded, self.route_id, trained_choices=self.trained_choices, trained_choice_skips=self.trained_choice_skips)

    def with_insight_ability(self, milestone_id: str, ability: str) -> "CommittedState":
        """Attach the typed follow-up ability to an existing occurrence."""

        if not isinstance(milestone_id, str) or not milestone_id or not isinstance(ability, str) or not ability:
            _error("DCC_LINEAR_INSIGHT_ABILITY", "An Insight ability follow-up requires typed IDs.")
        occurrences = [deepcopy(row) for row in self.insight_occurrences]
        for occurrence in occurrences:
            if occurrence.get("milestone_id") != milestone_id:
                continue
            parameters = occurrence.get("parameters")
            parameters = deepcopy(dict(parameters)) if isinstance(parameters, Mapping) else {}
            prior = parameters.get("ability")
            if prior is not None:
                code = "DCC_LINEAR_INSIGHT_ABILITY_DUPLICATE" if prior == ability else "DCC_LINEAR_INSIGHT_ABILITY_CONFLICT"
                _error(code, "An Insight occurrence ability cannot be replaced or committed twice.")
            parameters["ability"] = ability
            occurrence["parameters"] = parameters
            return CommittedState(self.by_slot, self.pairs, self.ordinary_by_cl, occurrences, self.bounded, self.route_id, trained_choices=self.trained_choices, trained_choice_skips=self.trained_choice_skips)
        _error("DCC_LINEAR_INSIGHT_ABILITY", "An Insight ability follow-up requires an existing occurrence.")

    def with_identity(self, name: str, title: str, concept: str | None = None) -> "CommittedState":
        identity: dict[str, str] = {"name": name, "title": title}
        if isinstance(concept, str) and concept.strip():
            identity["concept"] = " ".join(concept.split())
        return self.with_bounded("identity", identity)


_VALIDATOR_MANDATORY_SLOTS = frozenset({
    "background_choice",
    "background_sphere_choice",
    "background_talent_choice",
    "origin_insight_choice",
})


def _starting_proficiency_required_minimum(request: Any, envelope: Any, slot_id: str) -> int:
    """Mirror the validator's unconditional Background/Origin requirement.

    The frozen ``selection_limits_by_slot`` advertise Background, Background
    Sphere, Background Talent and Origin Insight as optional (``final_min``
    0, ``allow_none``), but the complete-character validator raises
    ``CG1_BOUNDED_DECISION_REQUIRED`` unless all four are selected, and the
    starting-proficiency validator separately demands one Background and one
    Origin.  On the first real Granite walks (2026-09-04) the model took the
    offered "continue without another choice" stop at Background and then at
    Background Sphere, and each whole build was rejected afterwards.  No stop
    may be offered on the first pick of these four slots.
    """

    if slot_id == "foundation_choice":
        # Rulebook: Foundations enter at the Foundation Realm (CL 5) and the
        # Factory review treats a deferred Foundation at or above it as an
        # unresolved owner decision ("Choose a Foundation").  Require the pick
        # there; below CL 5 the candidate list is empty and only the deferral
        # remains (see _foundation_candidates).
        target_cl = _frozen_target_cl(request, envelope)
        return 1 if target_cl is not None and target_cl >= FOUNDATION_REALM_ENTRY_CL else 0
    return 1 if slot_id in _VALIDATOR_MANDATORY_SLOTS else 0


def _none_allowed(minimum: int, allow_none: bool, selection_index: int, selected_count: int) -> bool:
    # Required first picks may never be skipped.  Once the frozen minimum is
    # met, an explicit none is a legal stop for optional/repeated slots.
    return allow_none and selected_count >= minimum and (
        minimum == 0 or selection_index > minimum
    )


# The delegated validator checks every selected slot choice against the
# frozen row's typed ``availability.minimum_cl``, ``prerequisites`` and
# ``incompatibilities``.  Planning slots are checked against every selected
# ID; the remaining slots are checked against a legality-only view that
# excludes planning priorities and adds the typed acquisitions and Method
# grants.  These helpers mirror that predicate over the committed walk state
# so a menu never offers an ID the unchanged validator would reject.
_VALIDATOR_PLANNING_SLOT_IDS = frozenset({
    "sphere_priorities",
    "advancement_skeleton",
    "insight_priorities",
    "item_priorities",
})


def _relation_targets(relation: Any) -> list[str]:
    """Mirror of the validator's typed relation target extraction."""

    if isinstance(relation, str):
        return [relation]
    if not isinstance(relation, Mapping):
        return []
    targets = relation.get("target_ids") or relation.get("targets")
    # Catalog either-or relations (schema: one target_id) list every
    # alternative in ``value``.
    if not targets and relation.get("operator") in {"one_of", "all_of"} and isinstance(relation.get("value"), list):
        targets = relation["value"]
    if isinstance(targets, str):
        return [targets]
    if isinstance(targets, list):
        return [target for target in targets if isinstance(target, str)]
    target = relation.get("target_id") or relation.get("record_id") or relation.get("canonical_id") or relation.get("id")
    return [target] if isinstance(target, str) else []


def _row_relations(row: Mapping[str, Any], key: str) -> Any:
    relations = row.get(key)
    if relations is None and isinstance(row.get("legality"), Mapping):
        relations = row["legality"].get(key)
    return relations


def _slot_rows_by_id(request: Any, envelope: Any, slot_id: str) -> dict[str, Mapping[str, Any]]:
    rows, _found = _slot_rows(request, envelope, slot_id)
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        choice_id = _choice_id(row)
        if isinstance(choice_id, str) and choice_id:
            result.setdefault(choice_id, row)
    return result


def _committed_present_ids(
    request: Any,
    envelope: Any,
    committed: Any,
    *,
    planning: bool,
    causal_cl: int | None = None,
    training_cl: Any = _SAME_CL,
) -> set[str]:
    state = _state_mapping(committed)
    slots = state.get("by_slot")
    slots = slots if isinstance(slots, Mapping) else {}
    present: set[str] = set()
    for slot_id, values in slots.items():
        if not planning and slot_id in _VALIDATOR_PLANNING_SLOT_IDS:
            continue
        if isinstance(values, (list, tuple)):
            present.update(value for value in values if isinstance(value, str) and value)
    if planning:
        return present
    for row in state.get("pairs") or ():
        if isinstance(row, Mapping):
            for key in ("sphere_id", "talent_id"):
                if isinstance(row.get(key), str) and row[key]:
                    present.add(row[key])
    ordinary = state.get("ordinary_by_cl")
    if isinstance(ordinary, Mapping):
        for raw_cl, value in ordinary.items():
            if not isinstance(value, str) or not value:
                continue
            if causal_cl is None:
                present.add(value)
                continue
            try:
                ordinary_cl = int(raw_cl)
            except (TypeError, ValueError):
                continue
            if ordinary_cl < causal_cl:
                present.add(value)
    trained_spheres, trained_talents = _committed_training_ids(committed, max_cl=causal_cl if training_cl is _SAME_CL else training_cl)
    present.update(trained_spheres)
    present.update(trained_talents)
    for occurrence in state.get("insight_occurrences") or ():
        if isinstance(occurrence, Mapping) and isinstance(occurrence.get("insight_id"), str) and occurrence["insight_id"]:
            present.add(occurrence["insight_id"])
    _materializable, grants, _required = _path_grant_cover_state(request, envelope)
    if grants is not None:
        for method_id in _state_slot(committed, "method_choice"):
            granted = grants.get(method_id)
            if isinstance(granted, (list, tuple)):
                # A Method's Path list is compatibility, not a Path the
                # character walks; the validator counts only chosen Paths
                # (a Spirit character was offered a Body-only Insight, build 23).
                present.update(value for value in granted if isinstance(value, str) and value and not value.startswith("tianxia.path."))
    return present


def _structural_gates_met(request: Any, envelope: Any, talent_id: str, present: set[str]) -> bool:
    """Whether every structural clause gating ``talent_id`` has a present alternative.

    The sealed request carries the canonical catalog's structural acquisition
    gates; a target the walk never grants (a Sphere package such as
    Spear-Heart) is simply never present, so that Talent is not offered
    (build 17 failed on TAL_SPEAR_HEART_OF_THE_SPEAR).
    """
    gates = _mapping(_first(request, envelope, "structural_talent_gates")).get(talent_id)
    if isinstance(gates, (list, tuple)) and not all(
        isinstance(clause, (list, tuple)) and any(target in present for target in clause) for clause in gates
    ):
        return False
    # Canonical Talent prerequisites: every clause needs one alternative
    # whose Talents are all present (the grant validator's rule).
    talent_gates = _mapping(_first(request, envelope, "talent_prerequisite_gates")).get(talent_id)
    if isinstance(talent_gates, (list, tuple)):
        for clause in talent_gates:
            if not isinstance(clause, (list, tuple)) or not any(
                isinstance(alternative, (list, tuple)) and all(target in present for target in alternative)
                for alternative in clause
            ):
                return False
    return True


def _relation_satisfied(relation: Any, present: set[str]) -> bool | None:
    """Return the validator's verdict, or ``None`` when it would refuse the relation."""

    if not isinstance(relation, Mapping):
        return None
    targets = _relation_targets(relation)
    if not targets:
        return None
    operator = relation.get("operator", "requires")
    if operator in {"requires", "all_of"}:
        return all(target in present for target in targets)
    if operator == "one_of":
        return any(target in present for target in targets)
    if operator == "not":
        return not any(target in present for target in targets)
    return None


def _frozen_legality_filter(
    request: Any,
    envelope: Any,
    committed: Any,
    slot_id: str,
    candidates: Sequence[_Candidate],
    *,
    planning: bool | None = None,
    causal_cl: int | None = None,
    training_cl: Any = None,
) -> list[_Candidate]:
    rows_by_id = _slot_rows_by_id(request, envelope, slot_id)
    if not rows_by_id:
        return list(candidates)
    if planning is None:
        planning = slot_id in _VALIDATOR_PLANNING_SLOT_IDS
    present = _committed_present_ids(request, envelope, committed, planning=planning, causal_cl=causal_cl,
                                     training_cl=_SAME_CL if training_cl is None else training_cl)
    target_cl = _frozen_target_cl(request, envelope)
    # Already committed choices whose ``not`` prerequisites or typed
    # incompatibilities name a later pick close that pick, because the
    # validator re-checks every selected row against the final set.
    excluded_by_committed: set[str] = set()
    committed_slots = _state_mapping(committed).get("by_slot")
    committed_slots = committed_slots if isinstance(committed_slots, Mapping) else {}
    for committed_slot, values in committed_slots.items():
        if not isinstance(values, (list, tuple)) or not values:
            continue
        committed_rows = _slot_rows_by_id(request, envelope, committed_slot)
        for value in values:
            row = committed_rows.get(value) if isinstance(value, str) else None
            if not isinstance(row, Mapping):
                continue
            for relation in _row_relations(row, "prerequisites") or []:
                if isinstance(relation, Mapping) and relation.get("operator") == "not":
                    excluded_by_committed.update(_relation_targets(relation))
            for relation in _row_relations(row, "incompatibilities") or []:
                excluded_by_committed.update(_relation_targets(relation))
    result: list[_Candidate] = []
    for candidate in candidates:
        if candidate.kind == OPTION_NONE or not candidate.choice_ids:
            result.append(candidate)
            continue
        legal = True
        trial = present | set(candidate.choice_ids)
        for choice_id in candidate.choice_ids:
            row = rows_by_id.get(choice_id)
            if not isinstance(row, Mapping):
                continue
            if choice_id in excluded_by_committed or not _structural_gates_met(request, envelope, choice_id, trial):
                legal = False
                break
            availability = row.get("availability") if isinstance(row.get("availability"), Mapping) else {}
            minimum_cl = availability.get("minimum_cl")
            if type(minimum_cl) is int and target_cl is not None and target_cl < minimum_cl:
                legal = False
                break
            relations = _row_relations(row, "prerequisites") or []
            if not isinstance(relations, (list, tuple)):
                legal = False
                break
            if any(_relation_satisfied(relation, trial) is not True for relation in relations):
                legal = False
                break
            incompatibilities = _row_relations(row, "incompatibilities") or []
            incompatible = {
                target
                for relation in (incompatibilities if isinstance(incompatibilities, (list, tuple)) else [])
                for target in _relation_targets(relation)
            }
            if incompatible & (trial - {choice_id}):
                legal = False
                break
        if legal:
            result.append(candidate)
    return result


def _menu_for_slot(
    request: Any,
    envelope: Any,
    committed: Any,
    *,
    step_id: str,
    step_kind: str,
    slot_id: str,
    ordinal: int,
    page: int,
    selection_index: int,
    default_min: int = 1,
    default_max: int | None = 1,
    title: str | None = None,
    candidates: Sequence[_Candidate] | None = None,
    ignore_slot_lock: bool = False,
    require_choice: bool = False,
    max_pages: int = MAX_PAGES_PER_STEP,
) -> StepMenu | None:
    if (not ignore_slot_lock and owner_lock_for(request, envelope, slot_id) is not _MISSING) or owner_lock_for(request, envelope, step_id) is not _MISSING:
        return None
    minimum, maximum, allow_none = _selection_limits(
        request,
        envelope,
        slot_id,
        default_min=default_min,
        default_max=default_max,
    )
    if require_choice:
        # A rule the walk has already fixed (a Path attainment that demands
        # its Subpath) makes this pick mandatory whatever the slot-wide
        # minimum says; no none option is legal here.
        minimum = max(minimum, 1)
        allow_none = False
    required_minimum = _starting_proficiency_required_minimum(request, envelope, slot_id)
    if required_minimum > minimum:
        minimum = required_minimum
        if maximum < minimum:
            maximum = minimum
    selected = _state_slot(committed, slot_id)
    effective_selection_index = max(
        selection_index if type(selection_index) is int and selection_index > 0 else 1,
        len(selected) + 1,
    )
    if len(selected) >= maximum:
        return None
    legal = list(candidates if candidates is not None else _authority_candidates(request, envelope, slot_id))
    selected_ids = set(selected)
    if selected_ids:
        legal = [candidate for candidate in legal if not selected_ids.intersection(candidate.choice_ids)]
    legal = _frozen_legality_filter(request, envelope, committed, slot_id, legal)
    # A character may walk one Path or several: once the first Path is chosen,
    # stopping is legal even though the slot itself may not be left empty
    # (every walk took all three Paths before this).
    repeat_stop = slot_id == "path_choice" and len(selected) >= max(minimum, 1)
    if repeat_stop or _none_allowed(minimum, allow_none, effective_selection_index, len(selected)):
        label = "No further Path" if slot_id == "path_choice" else "Continue without another choice"
        legal.append(_Candidate((), label, OPTION_NONE))
    if not legal:
        return None
    return _make_menu(
        request,
        envelope,
        committed,
        step_id=step_id,
        step_kind=step_kind,
        ordinal=ordinal,
        # Every S1 pick is one menu selection.  Slot-wide min/max still gate
        # presence and none; bundles in later slices may commit several typed
        # IDs while retaining this 1/1 step shape.
        minimum=1,
        maximum=1,
        candidates=legal,
        page=page,
        title=title,
        max_pages=max_pages,
    )


def _path_grant_cover_state(request: Any, envelope: Any) -> tuple[dict[str, _Candidate], Mapping[str, Any] | None, bool]:
    """Project the frozen typed Method authority used for path lookahead.

    Uses only frozen typed authority: the materializable ``method_choice``
    slot rows (choices intersect allowed), the typed
    ``method_granted_path_ids`` map, and the validator's zero-owner-lock
    Method requirement.  Never synthesizes IDs and never reads prose.
    """

    materializable = _authority_candidates(request, envelope, "method_choice")
    # The complete-source request release carries an exact Method planning
    # preference separately from acquisition locks. Honor that frozen choice
    # before asking the model; merely carrying its access proof does not do so.
    # Retained older walks keep their original menus and replay identities.
    compiler = _first(request, envelope, "compiler_selection_authority")
    if isinstance(compiler, Mapping) and compiler.get("schema") == "TianxiaFoundry.CompilerSelectionAuthority.v3":
        owner = _first(request, envelope, "owner_locks")
        planning = owner.get("planning_by_slot") if isinstance(owner, Mapping) else None
        method = planning.get("method_choice") if isinstance(planning, Mapping) else None
        if isinstance(method, Mapping) and method.get("mode") in {"EXACT", "HARD_LOCK"}:
            exact_ids = method.get("choice_ids")
            materializable = [candidate for candidate in materializable
                              if isinstance(exact_ids, list) and list(candidate.choice_ids) == exact_ids]
    materializable_by_id = {
        candidate.choice_ids[0]: candidate
        for candidate in materializable
        if len(candidate.choice_ids) == 1
    }
    compatibility = _first(request, envelope, "compatibility_envelope", "path_method_authority")
    grants = compatibility.get("method_granted_path_ids") if isinstance(compatibility, Mapping) else None
    grants = grants if isinstance(grants, Mapping) else None
    return materializable_by_id, grants, _validator_requires_method_choice(request, envelope)


def _grant_set_covers(grants: Mapping[str, Any] | None, method_id: str, path_set: set[str]) -> bool:
    if grants is not None and path_set:
        paths = grants.get(method_id)
        if isinstance(paths, (list, tuple)) and not path_set <= {value for value in paths if isinstance(value, str)}:
            return False
    return True


def _path_choice_candidates(request: Any, envelope: Any, committed: Any) -> list[_Candidate]:
    """Return path candidates that preserve a grant-covering Method.

    Each remaining candidate is kept only when the resulting committed Path
    set (lookahead 1) keeps at least one materializable grant-covering
    Method possible.  When the validator may lawfully defer Method, or when
    no materializable Method authority is frozen, no candidate is filtered.
    """

    base = _authority_candidates(request, envelope, "path_choice")
    if not base:
        return base
    materializable_by_id, grants, requires = _path_grant_cover_state(request, envelope)
    if not requires or not materializable_by_id:
        return base
    selected = set(_state_slot(committed, "path_choice"))
    result: list[_Candidate] = []
    for candidate in base:
        if selected.intersection(candidate.choice_ids):
            continue
        hypothetical = set(selected) | set(candidate.choice_ids)
        if any(_grant_set_covers(grants, method_id, hypothetical) for method_id in materializable_by_id):
            result.append(candidate)
    return sorted(result, key=_candidate_sort_key)


def build_path_choice_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, step_id: str = "path_choice", ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    return _menu_for_slot(request, envelope, committed, step_id=step_id, step_kind="path_choice", slot_id="path_choice", ordinal=ordinal, page=page, selection_index=selection_index, default_min=1, default_max=3, candidates=_path_choice_candidates(request, envelope, committed))


def _subpath_candidates(request: Any, envelope: Any, path_id: str) -> list[_Candidate]:
    rows, found = _slot_rows(request, envelope, "subpath_choice")
    if not found:
        rows = []
    filtered: list[Any] = []
    for row in rows:
        if isinstance(row, Mapping):
            owner = row.get(
                "owning_path_id",
                row.get("path_id", row.get("parent_path_id", row.get("owner"))),
            )
            if owner != path_id:
                continue
        filtered.append(row)
    # Some frozen envelopes carry a path-keyed index rather than flat rows.
    if not filtered:
        index = _first(request, envelope, "path_subpath_index", "subpaths_by_path", "subpath_index")
        if isinstance(index, Mapping) and path_id in index:
            filtered = _rows(index[path_id])
    allowed = _slot_allowed(request, envelope, "subpath_choice")
    target_cl = _frozen_target_cl(request, envelope)
    minimum_by_choice: Mapping[str, Any] = {}
    if target_cl is not None:
        for source in (_mapping(envelope), _mapping(request)):
            typed = _mapping(
                _mapping(
                    _mapping(source.get("typed_choice_authority_by_slot")).get("subpath_choice")
                ).get("minimum_attainment_by_choice")
            )
            if typed:
                minimum_by_choice = typed
                break
    result: dict[tuple[str, ...], _Candidate] = {}
    for row in filtered:
        candidate = _candidate(row)
        if candidate is None or (allowed is not None and not set(candidate.choice_ids) <= allowed):
            continue
        if target_cl is not None:
            for choice_id in candidate.choice_ids:
                minimum = minimum_by_choice.get(choice_id)
                if minimum is None and isinstance(row, Mapping):
                    minimum = row.get("minimum_attainment")
                try:
                    minimum = int(minimum) if minimum is not None else DEFAULT_SUBPATH_MINIMUM_ATTAINMENT
                except (TypeError, ValueError):
                    minimum = DEFAULT_SUBPATH_MINIMUM_ATTAINMENT
                if minimum > target_cl:
                    break
            else:
                result.setdefault(candidate.choice_ids, candidate)
            continue
        result.setdefault(candidate.choice_ids, candidate)
    return sorted(result.values(), key=_candidate_sort_key)


def _owner_locked_subpath_owner_ids(request: Any, envelope: Any) -> set[str]:
    """Paths whose Subpath the owner already sealed in the frozen envelope."""

    lock = owner_lock_for(request, envelope, "subpath_choice")
    if lock is _MISSING:
        return set()
    rows = _slot_rows_by_id(request, envelope, "subpath_choice")
    owners: set[str] = set()
    for subpath_id in _lock_values(lock):
        row = rows.get(subpath_id) or {}
        owner = row.get("owning_path_id", row.get("path_id", row.get("parent_path_id")))
        if isinstance(owner, str) and owner:
            owners.add(owner)
    return owners


def subpath_owner_by_id(request: Any, envelope: Any) -> dict[str, str]:
    """Owning Path of every sealed Subpath row, from typed ownership only."""

    result: dict[str, str] = {}
    for subpath_id, row in _slot_rows_by_id(request, envelope, "subpath_choice").items():
        owner = row.get("owning_path_id", row.get("path_id", row.get("parent_path_id"))) if isinstance(row, Mapping) else None
        if isinstance(owner, str) and owner:
            result[subpath_id] = owner
    return result


def final_path_attainment(request: Any, envelope: Any, committed: Any) -> dict[str, int] | None:
    """Each selected Path's final attainment once every progression CL is fixed.

    A CL counts toward a Path when the walk committed it, the owner locked it,
    or exactly one selected Path can advance there (the validator resolves
    such a CL without a pick).  Any CL still open returns ``None``: the
    attainment is not yet knowable and no rule may be applied to it.
    """

    target_cl = _frozen_target_cl(request, envelope)
    selected_paths = [value for value in _state_slot(committed, "path_choice") if isinstance(value, str) and value]
    if target_cl is None or not selected_paths:
        return None
    if equal_initial_path_attainment(_mapping(request)):
        vector = initial_path_attainment_vector(selected_paths, target_cl)
        return {path_id: vector[path_id] for path_id in selected_paths}
    existing = _mapping(_mapping(_state_mapping(committed).get("bounded")).get("path_progression_by_cl"))
    attained = {path_id: 0 for path_id in selected_paths}
    for cl in range(1, target_cl + 1):
        key = str(cl)
        value = existing.get(key)
        if not isinstance(value, str):
            lock = owner_lock_for(request, envelope, f"path_progression:{key}")
            values = _lock_values(lock) if lock is not _MISSING else []
            value = values[0] if len(values) == 1 else None
        if not isinstance(value, str):
            candidates = [
                candidate.choice_ids[0]
                for candidate in _progression_candidates(request, envelope, key)
                if candidate.choice_ids and candidate.choice_ids[0] in attained
            ]
            if len(candidates) != 1:
                return None
            value = candidates[0]
        if value in attained:
            attained[value] += 1
    return attained


def subpath_required_path_ids(request: Any, envelope: Any, committed: Any) -> list[str]:
    """Selected Paths whose fixed attainment demands a Subpath they lack.

    Mirrors the Stage 2 Path milestone: a Path that reaches its Subpath
    selection level (the sealed per-Subpath minimum, default 3) must hold
    exactly one Subpath.  Owner-locked and committed Subpaths both satisfy it.
    """

    attained = final_path_attainment(request, envelope, committed)
    if not attained:
        return []
    rows = _slot_rows_by_id(request, envelope, "subpath_choice")
    minimum_by_choice: Mapping[str, Any] = {}
    for source in (_mapping(envelope), _mapping(request)):
        typed = _mapping(_mapping(_mapping(source.get("typed_choice_authority_by_slot")).get("subpath_choice")).get("minimum_attainment_by_choice"))
        if typed:
            minimum_by_choice = typed
            break
    held_owners = set(_owner_locked_subpath_owner_ids(request, envelope))
    for subpath_id in _state_slot(committed, "subpath_choice"):
        row = rows.get(subpath_id) or {}
        owner = row.get("owning_path_id", row.get("path_id", row.get("parent_path_id")))
        if isinstance(owner, str):
            held_owners.add(owner)
    result: list[str] = []
    for path_id, level in attained.items():
        if path_id in held_owners:
            continue
        thresholds: list[int] = []
        for subpath_id, row in rows.items():
            owner = row.get("owning_path_id", row.get("path_id", row.get("parent_path_id"))) if isinstance(row, Mapping) else None
            if owner != path_id:
                continue
            minimum = minimum_by_choice.get(subpath_id)
            if minimum is None and isinstance(row, Mapping):
                minimum = row.get("minimum_attainment", row.get("minimum_cl"))
            try:
                thresholds.append(int(minimum) if minimum is not None else DEFAULT_SUBPATH_MINIMUM_ATTAINMENT)
            except (TypeError, ValueError):
                thresholds.append(DEFAULT_SUBPATH_MINIMUM_ATTAINMENT)
        if not thresholds:
            continue
        if level >= min(thresholds):
            result.append(path_id)
    return result


def build_subpath_choice_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, path_id: str | None = None, ordinal: int = 1, page: int = 1, selection_index: int = 1, require_choice: bool = False) -> StepMenu | None:
    if path_id is None:
        paths = _state_slot(committed, "path_choice")
        path_id = paths[-1] if paths else ""
    if not path_id:
        return None
    # An owner Subpath lock is a per-Path choice: locking Oni Blood decides
    # Body Refining's Subpath and nothing else.  Treating that lock as
    # slot-wide silenced every other selected Path's Subpath menu, and Stage 2
    # then rejected the build at that Path's level-3 milestone.
    if path_id in _owner_locked_subpath_owner_ids(request, envelope):
        return None
    step_id = f"subpath_choice:{path_id}" + (":required" if require_choice else "")
    required = _first(request, envelope, "subpath_choice_required")
    if not isinstance(required, bool):
        for source in (_mapping(envelope), _mapping(request)):
            response_contract = source.get("response_contract")
            if isinstance(response_contract, Mapping) and "subpath_choice_required" in response_contract:
                required = response_contract["subpath_choice_required"]
                break
    if not isinstance(required, bool):
        required = bool((_first(request, envelope, "subpath_required") is True))
    minimum = 1 if required else 0
    return _menu_for_slot(
        request,
        envelope,
        committed,
        step_id=step_id,
        step_kind="subpath_choice",
        slot_id="subpath_choice",
        ordinal=ordinal,
        page=page,
        selection_index=selection_index,
        default_min=minimum,
        default_max=1,
        candidates=_subpath_candidates(request, envelope, path_id),
        ignore_slot_lock=True,
        require_choice=require_choice,
    )


def _validator_requires_method_choice(request: Any, envelope: Any) -> bool:
    """Mirror the delegated validator's zero-owner-lock Method requirement.

    ``CG1_DELEGATED_METHOD_REQUIRED`` fires when the final plan defers Method
    and the frozen envelope carries no owner-locked Paths.  The walk must
    therefore offer a real Method pick in exactly that case; any other frozen
    shape may lawfully defer.
    """

    target_cl = _frozen_target_cl(request, envelope)
    if type(target_cl) is int and target_cl >= 1:
        # Any attainment requires a Method (Path 0 to 1 is a Method initiation).
        return True
    locks = _owner_locks(request, envelope)
    owner_paths = locks.get("path_choice") if isinstance(locks, Mapping) else None
    if owner_paths is None:
        return True
    if isinstance(owner_paths, str):
        return not owner_paths
    if isinstance(owner_paths, Mapping):
        return not any(isinstance(key, str) and key for key in owner_paths)
    if isinstance(owner_paths, (list, tuple, set, frozenset)):
        return not any(isinstance(value, str) and value for value in owner_paths)
    return not bool(owner_paths)


def _method_candidates(request: Any, envelope: Any, committed: Any) -> list[_Candidate]:
    compatibility = _first(request, envelope, "compatibility_envelope", "path_method_authority")
    values = compatibility.get("compatible_method_ids") if isinstance(compatibility, Mapping) else None
    if values is None:
        values = _first(request, envelope, "compatible_method_ids")
    # The compatibility projection can advertise methods that are not
    # materializable in this frozen project.  Prefer the exact typed method
    # slot authority (which is filtered by allowed_choice_ids_by_slot) and use
    # compatibility only as the path-compatibility predicate.
    materializable = _authority_candidates(request, envelope, "method_choice")
    compiler = _first(request, envelope, "compiler_selection_authority")
    if isinstance(compiler, Mapping) and compiler.get("schema") == "TianxiaFoundry.CompilerSelectionAuthority.v3":
        owner = _first(request, envelope, "owner_locks")
        planning = owner.get("planning_by_slot") if isinstance(owner, Mapping) else None
        method = planning.get("method_choice") if isinstance(planning, Mapping) else None
        if isinstance(method, Mapping) and method.get("mode") in {"EXACT", "HARD_LOCK"}:
            exact_ids = method.get("choice_ids")
            materializable = [candidate for candidate in materializable
                              if isinstance(exact_ids, list) and list(candidate.choice_ids) == exact_ids]
    materializable_by_id = {
        candidate.choice_ids[0]: candidate
        for candidate in materializable
        if len(candidate.choice_ids) == 1
    }
    compatible_ids = (
        {value for value in values if isinstance(value, str)}
        if values is not None
        else None
    )
    selected_paths = set(_state_slot(committed, "path_choice"))
    grants = compatibility.get("method_granted_path_ids") if isinstance(compatibility, Mapping) else None

    def _grant_covers(candidate: _Candidate) -> bool:
        # Owner ruling 2026-09-25: the Method must grant exactly the committed Paths; one that
        # also grants a Path the character does not take is disqualified.
        if isinstance(grants, Mapping) and selected_paths:
            paths = grants.get(candidate.choice_ids[0])
            if isinstance(paths, (list, tuple)) and selected_paths != {value for value in paths if isinstance(value, str)}:
                return False
        return True

    result: list[_Candidate] = []
    for candidate in materializable_by_id.values():
        method_id = candidate.choice_ids[0]
        if compatible_ids is not None and method_id not in compatible_ids:
            continue
        if not _grant_covers(candidate):
            continue
        result.append(candidate)
    if result:
        return sorted({item.choice_ids: item for item in result}.values(), key=_candidate_sort_key)
    if not materializable_by_id or not _validator_requires_method_choice(request, envelope):
        # Without an explicit frozen method-slot authority there is no safe
        # materializable candidate to expose from compatibility prose alone
        # (the validator would reject it as unknown/out-of-envelope), and a
        # run with owner-locked Paths may lawfully defer Method.  Either way
        # there is no safe pick to offer.
        return []
    # The compatible_method_ids allowlist is planner display input that the
    # validator never checks for Method legality (it checks grant coverage of
    # the final Paths).  When that allowlist drifts from grant coverage, the
    # strict intersect above empties and the retained walk would skip the
    # required pick entirely.  Fall back to exactly the validator-legal set:
    # materializable (frozen choices intersect allowed) covering the committed
    # Paths.  Never synthesize IDs from compatibility prose.
    fallback = [candidate for candidate in materializable_by_id.values() if _grant_covers(candidate)]
    return sorted({item.choice_ids: item for item in fallback}.values(), key=_candidate_sort_key)


def build_method_choice_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    mode = _first(request, envelope, "method_planning_mode", "planning_mode")
    mode = mode.upper() if isinstance(mode, str) else None
    candidates = _method_candidates(request, envelope, committed)
    target_cl = _frozen_target_cl(request, envelope)
    required_by_attainment = type(target_cl) is int and target_cl >= 1
    if mode == "AUTO" and not required_by_attainment:
        candidates = []
    if required_by_attainment:
        # AUTO means the model chooses among the legal Methods; a character
        # with attainment cannot defer.  No none option is legal here.
        return _menu_for_slot(request, envelope, committed, step_id="method_choice", step_kind="method_choice", slot_id="method_choice", ordinal=ordinal, page=page, selection_index=selection_index, default_min=1, default_max=1, candidates=candidates, require_choice=True)
    menu = _menu_for_slot(request, envelope, committed, step_id="method_choice", step_kind="method_choice", slot_id="method_choice", ordinal=ordinal, page=page, selection_index=selection_index, default_min=0 if mode == "AUTO" else 1, default_max=1, candidates=candidates)
    if menu is None and mode == "AUTO" and owner_lock_for(request, envelope, "method_choice") is _MISSING:
        return _make_menu(request, envelope, committed, step_id="method_choice", step_kind="method_choice", ordinal=ordinal, minimum=1, maximum=1, candidates=[_Candidate((), "Continue with automatic method planning", OPTION_NONE)], page=page)
    return menu


def method_required_gap(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any) -> dict[str, Any] | None:
    """Explain a required Method step that has no legal menu.

    Returns ``None`` when a Method is committed, owner-locked, or not
    required (no attainment); otherwise the exact facts: which compatible
    Methods the frozen request offered and why each is unavailable.
    """

    target_cl = _frozen_target_cl(request, envelope)
    if type(target_cl) is not int or target_cl < 1:
        return None
    if _state_slot(committed, "method_choice") or is_owner_locked(request, envelope, "method_choice"):
        return None
    if _method_candidates(request, envelope, committed):
        return None
    authority = _first(request, envelope, "path_method_authority")
    authority = authority if isinstance(authority, Mapping) else {}
    access_by_id = authority.get("method_access_by_id") if isinstance(authority.get("method_access_by_id"), Mapping) else {}
    compatible = [value for value in authority.get("compatible_method_ids") or [] if isinstance(value, str)]
    allowed = _slot_allowed(request, envelope, "method_choice")
    rows = _slot_rows_by_id(request, envelope, "method_choice")
    reasons: dict[str, list[str]] = {}
    for method_id in compatible:
        why: list[str] = []
        row = rows.get(method_id) or {}
        evidence = row.get("compiler_selection_evidence") if isinstance(row, Mapping) else None
        if isinstance(evidence, Mapping) and evidence.get("selectable") is not True:
            why.append("not_in_pinned_compiler_corpus")
        access = access_by_id.get(method_id) if isinstance(access_by_id, Mapping) else None
        if isinstance(access, Mapping) and access.get("initial_creation_selectable") is False and not access.get("constructed_access_route"):
            why.append("no_published_learning_route")
        if allowed is not None and method_id not in allowed and not why:
            why.append("not_allowed_in_frozen_request")
        reasons[method_id] = why or ["no_candidate_covers_selected_paths"]
    return {
        "step_id": "method_choice",
        "target_cl": target_cl,
        "selected_path_ids": list(_state_slot(committed, "path_choice")),
        "reason": "no_legal_method_candidate",
        "compatible_method_ids": compatible,
        "reasons_by_method_id": reasons,
    }


def _row_id_list(row: Any, key: str) -> list[str]:
    if not isinstance(row, Mapping):
        return []
    value = row.get(key)
    if not value:
        authority = row.get("authority")
        value = authority.get(key) if isinstance(authority, Mapping) else None
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, (list, tuple)) else []


def _advancing_path_tokens(values: Any) -> set[str]:
    """Normalize either Path id form for comparison.

    The Foundation authority writes ``compatible_path_ids`` in the compact
    upper form ("BODY_REFINING") while the committed Path slot uses the
    canonical id form ("tianxia.path.body_refining").  Comparing the trailing
    token of the canonical id against the compact form needs no mapping table
    and accepts either form.
    """

    tokens: set[str] = set()
    if isinstance(values, (list, tuple, set)):
        for value in values:
            if not isinstance(value, str) or not value:
                continue
            tokens.add(value.rsplit(".", 1)[-1].strip().upper())
    return tokens


def _verified_foundation_path_ids(foundation_id: str) -> list[str]:
    """The Paths a Foundation supports, from the pinned records the validator uses.

    Envelope rows omit ``compatible_path_ids``; without this fallback the walk
    offered a Body/Qi Foundation to a Spirit character (build 21).
    """
    try:
        from non_sphere_authority.foundation_mechanics import verified_foundation_records

        record = verified_foundation_records().get(foundation_id)
    except Exception:  # noqa: BLE001 - an unreadable authority must not break the menu
        return []
    paths = record.get("compatible_path_ids") if isinstance(record, Mapping) else None
    return [value for value in paths if isinstance(value, str)] if isinstance(paths, list) else []


def _foundation_candidates(request: Any, envelope: Any, committed: Any) -> list[_Candidate]:
    """Mirror CG1_METHOD_FOUNDATION_INCOMPATIBLE for the committed Method.

    The validator rejects a Foundation whose typed ``compatible_method_ids``
    exclude the selected Method, and a Method whose typed
    ``compatible_foundation_ids`` (on its row or in the sealed
    ``method_foundation_compatibility`` map) exclude the Foundation.  Empty
    lists constrain nothing, exactly as in the validator.

    It also mirrors the initial-Foundation authority gate: a Foundation that
    publishes ``compatible_path_ids`` must cover every Path the character ends
    with, or its initial state has no supported active expression
    (NS1R_INITIAL_FOUNDATION_AUTHORITY_INVALID).  Offering such a Foundation let
    the walk commit a choice the validator could only reject, so the same
    containment rule is applied here before the option is extended.
    """

    # Rulebook (Foundations Overview; Core Rules 8.2; AI generation reference
    # 16): "No character has a Foundation by default before the relevant Realm
    # or Source Rule grants one"; normal Realm entry is CL 5.  Below that the
    # only legal pick is the explicit deferral, which the slot's optional stop
    # provides.
    target_cl = _frozen_target_cl(request, envelope)
    if target_cl is not None and target_cl < FOUNDATION_REALM_ENTRY_CL:
        return []
    candidates = _authority_candidates(request, envelope, "foundation_choice")
    # Path containment applies whether or not a Method is chosen yet (the
    # Foundation step comes first, so the Method-only filter below returned
    # early and let a Body-only Foundation reach a Qi character, build 21).
    foundation_rows = _slot_rows_by_id(request, envelope, "foundation_choice")
    selected_paths = _advancing_path_tokens(_state_slot(committed, "path_choice"))

    def paths_supported(candidate: _Candidate) -> bool:
        foundation_id = candidate.choice_ids[0] if candidate.choice_ids else None
        if foundation_id is None:
            return True
        foundation_paths = _advancing_path_tokens(
            _row_id_list(foundation_rows.get(foundation_id), "compatible_path_ids")
            or _row_id_list(foundation_rows.get(foundation_id), "related_choice_ids")
            or _verified_foundation_path_ids(foundation_id)
        )
        return not (foundation_paths and selected_paths and not selected_paths.issubset(foundation_paths))

    candidates = [candidate for candidate in candidates if paths_supported(candidate)]
    # The Method that compilation will apply: the committed Method choice, or
    # the owner's EXACT access plan that Stage 2 sets as Primary when the slot
    # was deferred.  Foundation compatibility is filtered against that same
    # Method so the required Foundation step never picks one the Primary
    # Method rejects.
    method_id = _governing_method_id(request, envelope, committed)
    if not method_id:
        return candidates
    method_row = _slot_rows_by_id(request, envelope, "method_choice").get(method_id) or {}
    allowed_foundations = set(_row_id_list(method_row, "compatible_foundation_ids"))
    sealed_map = _first(request, envelope, "method_foundation_compatibility")
    if isinstance(sealed_map, Mapping):
        allowed_foundations |= set(_row_id_list(sealed_map.get(method_id), "compatible_foundation_ids"))
    result: list[_Candidate] = []
    for candidate in candidates:
        foundation_id = candidate.choice_ids[0] if candidate.choice_ids else None
        if foundation_id is None:
            result.append(candidate)
            continue
        if allowed_foundations and foundation_id not in allowed_foundations:
            continue
        compatible_methods = _row_id_list(foundation_rows.get(foundation_id), "compatible_method_ids")
        if compatible_methods and method_id not in compatible_methods:
            continue
        result.append(candidate)
    return result


def build_foundation_choice_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    return _menu_for_slot(request, envelope, committed, step_id="foundation_choice", step_kind="foundation_choice", slot_id="foundation_choice", ordinal=ordinal, page=page, selection_index=selection_index, candidates=_foundation_candidates(request, envelope, committed))


def build_background_choice_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    return _menu_for_slot(request, envelope, committed, step_id="background_choice", step_kind="background_choice", slot_id="background_choice", ordinal=ordinal, page=page, selection_index=selection_index)


def _linkage_rows(request: Any, envelope: Any, background_id: str, sphere_id: str | None = None) -> list[Any]:
    linkage = _first(request, envelope, "background_package_linkage", "background_package", "background_linkage")
    if not isinstance(linkage, Mapping):
        # Production envelopes keep the package linkage under the typed
        # authority for the Background slot.  It is still the same frozen
        # authority as the compact top-level alias; do not infer linkage from
        # display rows or prose when the alias is absent.
        for source in (_mapping(envelope), _mapping(request)):
            typed = source.get("typed_choice_authority_by_slot")
            background_authority = typed.get("background_choice") if isinstance(typed, Mapping) else None
            typed_linkage = background_authority.get("background_package_linkage") if isinstance(background_authority, Mapping) else None
            if not isinstance(typed_linkage, Mapping):
                continue
            background_rows = _rows(typed_linkage.get(background_id))
            if sphere_id is None:
                result: list[Any] = []
                for row in background_rows:
                    if not isinstance(row, Mapping):
                        continue
                    choice_id = row.get("background_sphere_choice_id", row.get("sphere_id"))
                    if not isinstance(choice_id, str) or not choice_id:
                        continue
                    result.append(_typed_linkage_choice_row(request, envelope, "background_sphere_choice", choice_id, row))
                return result
            result = []
            for row in background_rows:
                if not isinstance(row, Mapping):
                    continue
                linked_sphere = row.get("background_sphere_choice_id", row.get("sphere_id"))
                if linked_sphere != sphere_id:
                    continue
                choice_id = row.get("background_talent_choice_id", row.get("talent_id"))
                if not isinstance(choice_id, str) or not choice_id:
                    continue
                result.append(_typed_linkage_choice_row(request, envelope, "background_talent_choice", choice_id, row))
            return result
        return []
    background = linkage.get(background_id)
    if background is None:
        return []
    if sphere_id is None:
        if isinstance(background, Mapping):
            for key in ("spheres", "sphere_ids", "allowed_spheres", "background_spheres"):
                if key in background:
                    return _rows(background[key])
            return _rows(background)
        return _rows(background)
    if isinstance(background, Mapping):
        nested = background.get(sphere_id)
        if nested is not None:
            if isinstance(nested, Mapping):
                for key in ("talents", "talent_ids", "allowed_talents", "background_talents"):
                    if key in nested:
                        return _rows(nested[key])
            return _rows(nested)
        for key in ("talents_by_sphere", "talent_ids_by_sphere", "talents"):
            nested_map = background.get(key)
            if isinstance(nested_map, Mapping) and sphere_id in nested_map:
                return _rows(nested_map[sphere_id])
    return []


def _typed_linkage_choice_row(
    request: Any,
    envelope: Any,
    slot_id: str,
    choice_id: str,
    linkage_row: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Join a typed linkage ID to its typed choice row for presentation."""

    for row in _slot_rows(request, envelope, slot_id)[0]:
        if _choice_id(row) == choice_id and isinstance(row, Mapping):
            return dict(row)
    # The linkage ID remains the authority even when its catalog row is
    # sparse.  The generic cue path deliberately avoids exposing that ID.
    return {"id": choice_id, **dict(linkage_row)}


def _linkage_candidates(request: Any, envelope: Any, background_id: str, sphere_id: str | None = None, slot_id: str = "") -> list[_Candidate]:
    rows = _linkage_rows(request, envelope, background_id, sphere_id)
    allowed = _slot_allowed(request, envelope, slot_id) if slot_id else None
    result: dict[tuple[str, ...], _Candidate] = {}
    for row in rows:
        candidate = _candidate(row)
        if candidate is not None and (allowed is None or set(candidate.choice_ids) <= allowed):
            result.setdefault(candidate.choice_ids, candidate)
    return sorted(result.values(), key=_candidate_sort_key)


def _background_sphere_candidates(request: Any, envelope: Any, background_id: str) -> list[_Candidate]:
    """Return the sealed sphere rows of the one selected Background package.

    An owner-locked Background Talent already names exactly one sealed
    package.  Offering the other packages' spheres would let the walk commit a
    combination the sealed package validator must reject, so those rows are
    dropped before the menu is built.
    """

    candidates = _linkage_candidates(request, envelope, background_id, slot_id="background_sphere_choice")
    locked_talents = _owner_or_state_ids(request, envelope, None, "background_talent_choice")
    if not locked_talents:
        # A Sphere whose every Background Talent Stage 2 cannot record (Temple
        # Initiate's Protection offers only Ward) is a dead end: the talent step
        # after it has nothing buildable.  Skip it unless nothing else is left.
        def dead_end(candidate: _Candidate) -> bool:
            if not candidate.choice_ids:
                return False
            talents = _linkage_candidates(request, envelope, background_id, candidate.choice_ids[0], slot_id="background_talent_choice")
            return bool(talents) and not _background_talents_legal_at_cl1(
                request, envelope, background_id, candidate.choice_ids[0], talents, strict=True
            )

        buildable = [candidate for candidate in candidates if not dead_end(candidate)]
        return buildable or candidates
    return [
        candidate
        for candidate in candidates
        if candidate.choice_ids
        and any(
            set(talent.choice_ids) & locked_talents
            for talent in _linkage_candidates(
                request, envelope, background_id, candidate.choice_ids[0], slot_id="background_talent_choice"
            )
        )
    ]


def build_background_sphere_choice_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    backgrounds = _state_slot(committed, "background_choice")
    if not backgrounds:
        return None
    background_id = backgrounds[-1]
    return _menu_for_slot(request, envelope, committed, step_id="background_sphere_choice", step_kind="background_sphere_choice", slot_id="background_sphere_choice", ordinal=ordinal, page=page, selection_index=selection_index, candidates=_background_sphere_candidates(request, envelope, background_id))


def build_background_talent_choice_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    backgrounds = _state_slot(committed, "background_choice")
    spheres = _state_slot(committed, "background_sphere_choice")
    if not backgrounds or not spheres:
        return None
    candidates = _linkage_candidates(request, envelope, backgrounds[-1], spheres[-1], "background_talent_choice")
    return _menu_for_slot(request, envelope, committed, step_id="background_talent_choice", step_kind="background_talent_choice", slot_id="background_talent_choice", ordinal=ordinal, page=page, selection_index=selection_index, candidates=_background_talents_legal_at_cl1(request, envelope, backgrounds[-1], spheres[-1], candidates))


def _background_talents_legal_at_cl1(request: Any, envelope: Any, background_id: str, sphere_id: str, candidates: list[_Candidate], *, strict: bool = False) -> list[_Candidate]:
    """Drop Background Talents Stage 2 cannot record at CL1.

    Stage 2 records a Background Talent as its canonical Talent and enforces
    that Talent's minimum CL, so Dream-Touched's printed Shared Dream (canonical
    minimum CL 5) fails the whole Background package at CL1.
    """
    canonical_by_choice: dict[str, str] = {}
    packages = _mapping(_linear_projection(request, envelope).get("background_package_linkage")).get(background_id)
    for row in packages if isinstance(packages, (list, tuple)) else ():
        if isinstance(row, Mapping) and isinstance(row.get("background_talent_choice_id"), str) and isinstance(row.get("canonical_talent_id"), str):
            canonical_by_choice[row["background_talent_choice_id"]] = row["canonical_talent_id"]
    talent_rows = _slot_rows_by_id(request, envelope, "advancement_skeleton")

    def legal(candidate: _Candidate) -> bool:
        for choice_id in candidate.choice_ids:
            canonical = canonical_by_choice.get(choice_id)
            row = talent_rows.get(canonical or "")
            # A package naming only its own route id (Dream Ward, Ward) is
            # recorded by Stage 2 as the same-named ordinary Talent and then
            # fails the package check (build 11); skip those routes.
            if canonical is not None and row is None:
                return False
            minimum_cl = _mapping(row.get("availability")).get("minimum_cl") if isinstance(row, Mapping) else None
            if type(minimum_cl) is int and minimum_cl > 1:
                return False
        return True

    kept = [candidate for candidate in candidates if legal(candidate)]
    return kept if strict else kept or candidates


def _background_ability_amount_advertised(request: Any, envelope: Any) -> bool:
    if _contract_field(request, envelope, "background_ability_amount") is not None:
        return True
    projection = _linear_projection(request, envelope)
    response_contract = projection.get("response_contract")
    advertised = response_contract.get("allowed_bounded_choice_keys") if isinstance(response_contract, Mapping) else None
    return isinstance(advertised, (list, tuple, set, frozenset)) and "background_ability_amount" in advertised


def _background_ability_typed_values(raw: Any) -> tuple[list[str], list[int], int | None]:
    if isinstance(raw, Mapping) and isinstance(raw.get("ability_adjustment"), Mapping):
        raw = raw["ability_adjustment"]
    if isinstance(raw, Mapping):
        values = raw.get("allowed_abilities", raw.get("allowed_values"))
        raw_amounts = raw.get("allowed_amounts")
        if raw_amounts is None:
            raw_amounts = raw.get("amount_choices")
        fixed_amount = raw.get("amount")
    else:
        values = raw
        raw_amounts = None
        fixed_amount = None
    abilities = sorted({
        value
        for row in _rows(values)
        for value in [_choice_id(row)]
        if value in {"STR", "DEX", "CON", "INT", "WIS", "CHA"}
    })
    amounts = sorted({
        value
        for value in (raw_amounts or [])
        if type(value) is int and value > 0
    }) if isinstance(raw_amounts, (list, tuple, set, frozenset)) else []
    fixed = fixed_amount if type(fixed_amount) is int and fixed_amount > 0 else None
    return abilities, amounts, fixed


def _generated_build(request: Any, envelope: Any) -> bool:
    """Whether this request is a generated build; manual menus keep printed choices."""
    values = (_mapping(request), _mapping(envelope))
    return any(value.get("generation_route") in {"ai_bootstrap", "quick_build", "generated"}
               or value.get("creation_mode") in {"quick", "generated"} for value in values)


def _background_ability_candidates(request: Any, envelope: Any, committed: Any = None) -> list[_Candidate]:
    names = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
             "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}
    background_ids = _state_slot(committed, "background_choice")
    background_id = background_ids[-1] if background_ids else None
    raw_values: list[Any] = []
    contract = _bounded_choice_contract(request, envelope)
    fields = contract.get("fields") if isinstance(contract, Mapping) else None
    field = fields.get("background_ability") if isinstance(fields, Mapping) else None
    if field is None and isinstance(contract, Mapping):
        field = contract.get("background_ability")
    if isinstance(field, Mapping) and background_id in field and isinstance(field.get(background_id), Mapping):
        field = field[background_id]
    if isinstance(field, Mapping) or isinstance(field, (list, tuple, set, frozenset)):
        raw_values.append(field)

    for summary in (
        _first(request, envelope, "bounded_choice_summary"),
        _linear_projection(request, envelope).get("bounded_choice_summary"),
    ):
        if not isinstance(summary, Mapping):
            continue
        candidates = summary.get("background_ability_candidates")
        if isinstance(candidates, Mapping) and background_id in candidates:
            raw_values.append(candidates[background_id])

    if background_id:
        for source in (_mapping(envelope), _mapping(request)):
            typed = source.get("typed_choice_authority_by_slot")
            background_authority = typed.get("background_choice") if isinstance(typed, Mapping) else None
            adjustments = background_authority.get("ability_adjustment_by_choice") if isinstance(background_authority, Mapping) else None
            if isinstance(adjustments, Mapping) and background_id in adjustments:
                raw_values.append(adjustments[background_id])

    amount_advertised = _background_ability_amount_advertised(request, envelope)
    result: dict[tuple[str, ...], _Candidate] = {}
    for raw in raw_values:
        abilities, amounts, fixed_amount = _background_ability_typed_values(raw)
        if not abilities:
            continue
        if amount_advertised:
            available_amounts = amounts or ([fixed_amount] if fixed_amount is not None else [])
            for ability in abilities:
                for amount in available_amounts:
                    token = f"{BACKGROUND_ABILITY_AMOUNT_PREFIX}{amount}"
                    result[(ability, token)] = _Candidate(
                        (ability, token),
                        f"Increase {names.get(ability, ability)} ({ability}) by {amount} from your Background.",
                        OPTION_BUNDLE,
                    )
        else:
            for ability in abilities:
                name = f"{names.get(ability, ability)} ({ability})"
                cue = (f"Increase {name} by {fixed_amount} from your Background." if fixed_amount is not None
                       else f"Apply your Background's listed bonus to {name}.")
                result[(ability,)] = _Candidate((ability,), cue, OPTION_PICK)
    ordered = sorted(result.values(), key=_candidate_sort_key)
    # Rule: the Background bonus goes to the key ability first (the priority
    # order's first offered ability). Concept cannot move it to a lower one.
    if _generated_build(request, envelope):
        offered = {candidate.choice_ids[0] for candidate in ordered}
        key = next((ability for ability in _ability_priority(committed, request, envelope) if ability in offered), None)
        if key is not None:
            ordered = [candidate for candidate in ordered if candidate.choice_ids[0] == key]
    return ordered


def build_background_ability_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    if not _state_slot(committed, "background_choice"):
        return None
    if "background_ability" in _mapping(_state_mapping(committed).get("bounded")):
        return None
    return _menu_for_slot(request, envelope, committed, step_id="background_ability", step_kind="background_ability", slot_id="background_ability", ordinal=ordinal, page=page, selection_index=selection_index, candidates=_background_ability_candidates(request, envelope, committed))


def build_foundation_initial_stage_menu(request, envelope, committed=None, *, ordinal=1, page=1, selection_index=1):
    selected = _state_slot(committed, "foundation_choice")
    bounded = _mapping(_state_mapping(committed).get("bounded"))
    contract = _mapping(_contract_field(request, envelope, "foundation_initial_stage"))
    if not selected or not contract or "foundation_initial_stage" in bounded:
        return None
    options = _mapping(contract.get("options_by_foundation_id")).get(selected[0], [])
    if len(options) == 1:
        # A source default is deterministic; it consumes no model decision.
        return None
    return _make_menu(
        request, envelope, committed, step_id="foundation_initial_stage",
        step_kind="foundation_initial_stage", ordinal=ordinal, minimum=1, maximum=1,
        candidates=[_Candidate((stage,), f"Published initial Foundation stage: {stage}") for stage in options], page=page,
    )


def build_origin_insight_choice_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    # The origin choice is independently authorized by its frozen slot rows.
    # Exclude only the explicit unresolved rows whose typed contract says that
    # proficiency mechanics are present; resolved origins remain selectable.
    unresolved = _origin_unresolved_ids(request, envelope)
    candidates = _authority_candidates(request, envelope, "origin_insight_choice")
    if unresolved:
        candidates = [
            candidate
            for candidate in candidates
            if not unresolved.intersection(candidate.choice_ids)
        ]
    return _menu_for_slot(request, envelope, committed, step_id="origin_insight_choice", step_kind="origin_insight_choice", slot_id="origin_insight_choice", ordinal=ordinal, page=page, selection_index=selection_index, candidates=candidates)


def _response_contract(request: Any, envelope: Any) -> Mapping[str, Any]:
    value = _first(request, envelope, "response_contract")
    return value if isinstance(value, Mapping) else {}


def _typed_grant_accounting(request: Any, envelope: Any) -> Mapping[str, Any]:
    """Read the frozen grant accounting used for pre-response capacity."""

    request_map = _mapping(request)
    sources: list[Mapping[str, Any]] = []
    snapshot = request_map.get("typed_choice_snapshot")
    if isinstance(snapshot, Mapping):
        sources.append(snapshot)
    stage1 = request_map.get("stage1_prompt")
    stage1_envelope = stage1.get("envelope") if isinstance(stage1, Mapping) else None
    if isinstance(stage1_envelope, Mapping):
        sources.append(stage1_envelope)
    for source in sources:
        locks = source.get("typed_locks")
        if not isinstance(locks, (list, tuple)):
            locks = source.get("user_locks")
        if not isinstance(locks, (list, tuple)):
            continue
        for lock in reversed(locks):
            if not isinstance(lock, Mapping) or lock.get("field") != "character_sheet.canonical_grant_plan":
                continue
            value = lock.get("value")
            accounting = value.get("grant_accounting") if isinstance(value, Mapping) else None
            if isinstance(accounting, Mapping):
                return accounting
    return {}


def _linear_projection(request: Any, envelope: Any) -> Mapping[str, Any]:
    """Return an optional deterministic provider projection supplied to the walk."""

    for source in (_mapping(envelope), _mapping(request)):
        for key in ("linear_provider_payload", "provider_payload"):
            value = source.get(key)
            if isinstance(value, Mapping):
                return value
    return {}


def _expected_count(request: Any, envelope: Any, key: str) -> int:
    aliases = {
        "sphere_free_talent_pairs": (
            "sphere_free_talent_pairs",
            "sphere_free_talent_pair_count",
            "free_sphere_talent_grant_count",
        ),
        "ordinary_talent_ids": ("ordinary_talent_ids", "ordinary_talent_count"),
    }.get(key, (key,))
    projection = _linear_projection(request, envelope)
    for source in (_response_contract(request, envelope), _response_contract(projection, {}), projection, _mapping(envelope), _mapping(request)):
        for container_key in ("expected_acquisition_counts", "acquisition_contract"):
            container = source.get(container_key)
            if isinstance(container, Mapping):
                for alias in aliases:
                    value = container.get(alias)
                    if type(value) is int and value > 0:
                        return value
        for alias in aliases:
            value = source.get(alias)
            if type(value) is int and value > 0:
                return value
    accounting = _typed_grant_accounting(request, envelope)
    if key == "sphere_free_talent_pairs":
        value = accounting.get("free_sphere_talent_grant_count")
        if type(value) is int and value > 0:
            return value
        rows = accounting.get("free_sphere_talent_grants")
        if isinstance(rows, (list, tuple)) and rows:
            return len(rows)
        # This is the same typed pre-response placeholder rule used by the
        # provider projection: an empty compatibility grant lock still
        # requires the bootstrap pair when ordinary capacity is frozen.
        ordinary_count = _expected_count(request, envelope, "ordinary_talent_ids")
        generation_route = None
        origin = None
        request_map = _mapping(request)
        for source in (request_map.get("typed_choice_snapshot"), _mapping(_mapping(request_map.get("stage1_prompt")).get("envelope"))):
            locks = source.get("typed_locks") if isinstance(source, Mapping) else None
            if not isinstance(locks, (list, tuple)) and isinstance(source, Mapping):
                locks = source.get("user_locks")
            for lock in locks or ():
                if not isinstance(lock, Mapping):
                    continue
                if lock.get("field") == "character_sheet.generation_route":
                    generation_route = lock.get("value")
                elif lock.get("field") == "character_sheet.canonical_grant_plan_origin":
                    origin = lock.get("value")
        if (
            value == 0
            and not rows
            and ordinary_count > 0
            and generation_route == "ai_bootstrap"
            and origin == "compatibility_projection"
        ):
            return 1
    return 0


def _pair_rows(request: Any, envelope: Any) -> list[Mapping[str, Any]]:
    value = _first(request, envelope, "presented_legal_first_cycle_pairs")
    if value is None:
        value = _response_contract(request, envelope).get("presented_legal_first_cycle_pairs")
    if value is None:
        projection = _linear_projection(request, envelope)
        value = projection.get("presented_legal_first_cycle_pairs")
        if value is None:
            value = _response_contract(projection, {}).get("presented_legal_first_cycle_pairs")
    if value is None:
        accounting = _typed_grant_accounting(request, envelope)
        value = accounting.get("free_sphere_talent_grants")
    if not isinstance(value, (list, tuple)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _pair_key(row: Mapping[str, Any]) -> tuple[str, str] | None:
    pair = row.get("free_talent_pair") if isinstance(row.get("free_talent_pair"), Mapping) else row
    sphere_id = pair.get("sphere_id") if isinstance(pair, Mapping) else None
    talent_id = pair.get("talent_id") if isinstance(pair, Mapping) else None
    return (sphere_id, talent_id) if isinstance(sphere_id, str) and sphere_id and isinstance(talent_id, str) and talent_id else None


def _typed_label(row: Mapping[str, Any], *, fallback: str) -> str:
    for key in ("name", "display_name", "sphere_name", "talent_name", "label", "cue", "semantic_cue"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:MAX_CUE_LENGTH]
    for key in ("sphere", "talent", "metadata"):
        nested = row.get(key)
        if isinstance(nested, Mapping):
            label = _typed_label(nested, fallback=fallback)
            if label != fallback:
                return label
    return fallback


def _pair_cue(request: Any, envelope: Any, row: Mapping[str, Any], sphere_id: str, talent_id: str) -> str:
    sphere_name = row.get("sphere_name")
    talent_name = row.get("talent_name")
    if isinstance(sphere_name, str) and sphere_name.strip() and isinstance(talent_name, str) and talent_name.strip():
        return f"{' '.join(sphere_name.split())} + {' '.join(talent_name.split())}"[:MAX_CUE_LENGTH]
    pair_label = _typed_label(row, fallback="Sphere and free Talent")
    if pair_label != "Sphere and free Talent":
        return pair_label
    # The pair object may intentionally omit display fields.  Resolve them
    # from the same frozen typed rows used by the compact provider payload.
    labels: dict[str, str] = {}
    for source in (_mapping(envelope), _mapping(request)):
        for key in ("choices_by_slot", "allowed_choices_by_slot", "allowed_high_level"):
            slots = source.get(key)
            if not isinstance(slots, Mapping):
                continue
            for rows in slots.values():
                for candidate_row in _rows(rows):
                    candidate_id = _choice_id(candidate_row)
                    if candidate_id in {sphere_id, talent_id} and isinstance(candidate_row, Mapping):
                        labels[candidate_id] = _typed_label(candidate_row, fallback="Choice")
        shortlist = source.get("ordinary_talent_shortlist_by_sphere")
        if isinstance(shortlist, Mapping):
            for rows in shortlist.values():
                for candidate_row in _rows(rows):
                    candidate_id = _choice_id(candidate_row)
                    if candidate_id in {sphere_id, talent_id} and isinstance(candidate_row, Mapping):
                        labels[candidate_id] = _typed_label(candidate_row, fallback="Choice")
        profiles = _mapping(source.get("sphere_comparability_index")).get("profiles")
        for profile in _rows(profiles):
            if isinstance(profile, Mapping) and profile.get("sphere_id") == sphere_id:
                labels[sphere_id] = _typed_label(profile, fallback="Choice")
    sphere_label = labels.get(sphere_id, "Sphere")
    talent_label = labels.get(talent_id, "free Talent")
    return f"{sphere_label} + {talent_label}"


def _sealed_owner_locks(request: Any, envelope: Any) -> list[Mapping[str, Any]]:
    """Every sealed owner lock row reachable from the frozen request."""

    rows: list[Mapping[str, Any]] = []
    request_map = _mapping(request)
    for source in (
        _mapping(_mapping(request_map.get("stage1_prompt")).get("envelope")).get("user_locks"),
        _mapping(request_map.get("typed_choice_snapshot")).get("typed_locks"),
        _mapping(envelope).get("owner_user_locks"),
        request_map.get("owner_user_locks"),
    ):
        if isinstance(source, (list, tuple)):
            rows.extend(row for row in source if isinstance(row, Mapping))
    return rows


def _owner_planning_preferences(request: Any, envelope: Any) -> dict[str, list[str]]:
    """The owner's wizard priorities, sealed in the request as planning locks.

    Owner decision 10: these are binding priorities for the walk, not hints.
    ``character_sheet.planning_preferences`` carries ordered
    ``sphere_priority_ids`` and ``talent_priority_ids``; ``preferred_record_ids``
    is the flat preferred list.  Returned in owner order, de-duplicated.
    """

    result: dict[str, list[str]] = {"sphere_priority_ids": [], "talent_priority_ids": [], "preferred_record_ids": []}

    def extend(key: str, values: Any) -> None:
        if isinstance(values, (list, tuple)):
            for value in values:
                if isinstance(value, str) and value and value not in result[key]:
                    result[key].append(value)

    direct = _first(request, envelope, "owner_planning_preferences")
    if isinstance(direct, Mapping):
        for key in result:
            extend(key, direct.get(key))
    for lock in _sealed_owner_locks(request, envelope):
        field = lock.get("field")
        value = lock.get("value")
        if field == "character_sheet.planning_preferences" and isinstance(value, Mapping):
            extend("sphere_priority_ids", value.get("sphere_priority_ids"))
            extend("talent_priority_ids", value.get("talent_priority_ids"))
        elif field == "preferred_record_ids":
            extend("preferred_record_ids", value)
    return result


def _free_acquisition_kinds(request: Any, envelope: Any) -> tuple[str, str]:
    """Mirror the server's route-specific free Talent/Sphere acquisition kinds."""

    for lock in _sealed_owner_locks(request, envelope):
        if lock.get("field") == "character_sheet.generation_route":
            if lock.get("value") == "ai_bootstrap":
                return ("ai_bootstrap_talent_acquisition", "ai_bootstrap_sphere_acquisition")
            return ("sect_trial_talent_acquisition", "sect_trial_sphere_acquisition")
    return ("sect_trial_talent_acquisition", "sect_trial_sphere_acquisition")


_CHANNEL_KINDS = {
    "ai-bootstrap-free-cl1-sphere": "ai_bootstrap_sphere_acquisition",
    "sect-trial-cl1-sphere": "sect_trial_sphere_acquisition",
    "ai-bootstrap-free-cl1-talent": "ai_bootstrap_talent_acquisition",
    "sect-trial-cl1-level-talent": "sect_trial_talent_acquisition",
    # Canonical Sphere rows advertise the generic channel; the server treats
    # it as both route-specific Sphere kinds.
    "sphere-acquisition": "sphere_acquisition",
}

def _sealed_allowed_kinds(authority: Mapping[str, Any], row: Mapping[str, Any]) -> set[str]:
    """Mirror ``_provider_stage2_allowed_kinds``: typed kinds, else channel kinds."""

    direct = {value for value in list(authority.get("allowed_kinds") or []) + list(row.get("allowed_kinds") or []) if isinstance(value, str) and value.strip()}
    if direct:
        return direct
    channels = {value for value in list(authority.get("allowed_channels") or []) + list(row.get("acquisition_channels") or []) if isinstance(value, str) and value.strip()}
    kinds = {_CHANNEL_KINDS[channel] for channel in channels if channel in _CHANNEL_KINDS}
    if "sphere_acquisition" in kinds:
        kinds |= {"ai_bootstrap_sphere_acquisition", "sect_trial_sphere_acquisition"}
    return kinds


def _creation_training_typed_authority(
    request: Any,
    envelope: Any,
    record_id: str,
    choice_type: str,
    row: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return the exact sealed Stage 2 authority for one training record."""

    slot_id = "sphere_priorities" if choice_type == "new_sphere" else "advancement_skeleton"
    for source in (_mapping(envelope), _mapping(request)):
        typed = source.get("typed_choice_authority_by_slot")
        section = typed.get(slot_id) if isinstance(typed, Mapping) else None
        by_choice = section.get("stage2_authority_by_choice") if isinstance(section, Mapping) else None
        authority = by_choice.get(record_id) if isinstance(by_choice, Mapping) else None
        if isinstance(authority, Mapping):
            return authority
    authority = row.get("stage2_authority")
    if isinstance(authority, Mapping):
        return authority
    compatibility = row.get("compatibility")
    factory = compatibility.get("factory") if isinstance(compatibility, Mapping) else None
    authority = factory.get("stage2_authority") if isinstance(factory, Mapping) else None
    return authority if isinstance(authority, Mapping) else {}


def _creation_training_kind_allowed(
    request: Any,
    envelope: Any,
    route: Mapping[str, Any],
    record_id: str,
    choice_type: str,
    row: Mapping[str, Any],
    expected_kind: str,
) -> bool:
    """Check one emitted training kind against sealed authority.

    The materializer resolves constructed training with an exact typed
    Stage 2 kind and channel.  The menu must therefore require the same
    complete sealed authority before it emits a choice; generic acquisition
    channels and route/source labels are not authority for this lane.
    """

    authority = _creation_training_typed_authority(request, envelope, record_id, choice_type, row)
    if authority.get("authority_complete") is not True:
        return False
    allowed_kinds = {
        value for value in authority.get("allowed_kinds") or []
        if isinstance(value, str) and value.strip()
    }
    expected_channel = CREATION_TRAINING_CHANNEL_BY_KIND.get(expected_kind)
    allowed_channels = {
        value for value in authority.get("allowed_channels") or []
        if isinstance(value, str) and value.strip()
    }
    return (
        expected_kind in allowed_kinds
        and isinstance(expected_channel, str)
        and expected_channel in allowed_channels
    )


def _sphere_typed_authority(request: Any, envelope: Any, sphere_id: str) -> Mapping[str, Any]:
    for source in (_mapping(envelope), _mapping(request)):
        typed = _mapping(_mapping(_mapping(source.get("typed_choice_authority_by_slot")).get("sphere_priorities")).get("stage2_authority_by_choice")).get(sphere_id)
        if isinstance(typed, Mapping):
            return typed
        availability = _mapping(_mapping(source.get("prerequisites_and_availability")).get("sphere_priorities")).get(sphere_id)
        if isinstance(availability, Mapping):
            return availability
    return {}


def _is_non_talent_record(row: Any) -> bool:
    """Catalog stopgap: stat-block records are published typed as talents.

    The Sphere Compendium ships "<Talent> Stat Block" records (Corpse Servant
    Stat Block, Grave Formation Stat Block) as the mechanical description of a
    summoned creature or formation, not as a selectable talent, yet the sealed
    catalog types them as talents with full level-talent authority and no
    typed prerequisite.  Until the catalog marks them, the walk never offers
    them as a Talent pick.  Recorded as a catalog defect for the owner.
    """

    name = row.get("name") if isinstance(row, Mapping) else None
    return isinstance(name, str) and name.strip().casefold().endswith("stat block")


def _legal_free_pairs(request: Any, envelope: Any) -> list[dict[str, str]]:
    """The complete legal CL1 Sphere/free-Talent pair set from sealed authority.

    Mirrors the server predicate (``_provider_free_talent_pairs``) and the
    delegated validator: the Sphere is an allowed Sphere row that advertises
    the route's Sphere kind; the Talent is an allowed skeleton row whose typed
    authority owns it to that Sphere, allows the route's Talent kind, is not
    marked ``free_sphere_talent_eligible: False``, is legal at CL 1, and
    carries no typed prerequisites or incompatibilities.  The server presents
    only a six-Sphere sample of this set; the walk needs all of it so the
    owner's priority Spheres can be honored.
    """

    free_kind, sphere_kind = _free_acquisition_kinds(request, envelope)
    sphere_rows = _slot_rows_by_id(request, envelope, "sphere_priorities")
    allowed_spheres = _slot_allowed(request, envelope, "sphere_priorities")
    legal_spheres: set[str] = set()
    for sphere_id, row in sphere_rows.items():
        if allowed_spheres is not None and sphere_id not in allowed_spheres:
            continue
        if sphere_kind in _sealed_allowed_kinds(_sphere_typed_authority(request, envelope, sphere_id), row):
            legal_spheres.add(sphere_id)
    if not legal_spheres:
        return []
    pairs: list[dict[str, str]] = []
    for talent_id, row in _ordinary_typed_rows(request, envelope).items():
        if _is_non_talent_record(row):
            continue
        authority = _ordinary_typed_authority(request, envelope, talent_id, row)
        owner = authority.get("owning_canonical_sphere_id") or authority.get("owning_sphere_id") or authority.get("sphere_id") or row.get("owning_canonical_sphere_id") or row.get("owning_sphere_id")
        if not isinstance(owner, str) or owner not in legal_spheres:
            continue
        if free_kind not in _sealed_allowed_kinds(authority, row):
            continue
        eligible = authority.get("free_sphere_talent_eligible") if "free_sphere_talent_eligible" in authority else row.get("free_sphere_talent_eligible")
        if eligible is False:
            continue
        minimum_cl = _ordinary_typed_minimum_cl(request, envelope, talent_id, row, authority)
        if type(minimum_cl) is int and (minimum_cl < 0 or minimum_cl > 1):
            continue
        if any(
            source.get(key)
            for source in (authority, row)
            for key in ("hard_prerequisite_ids", "prerequisite_ids", "prerequisites", "incompatibility_ids", "incompatibilities")
        ):
            continue
        pairs.append({"sphere_id": owner, "talent_id": talent_id})
    pairs.sort(key=lambda pair: (pair["sphere_id"], pair["talent_id"]))
    return pairs


def _prefer_owner_priorities(candidates: Sequence[_Candidate], priority_ids: Sequence[str], *, position: int = 0) -> list[_Candidate]:
    """Restrict candidates to the owner's priority IDs when any of them is legal.

    ``position`` selects which choice_id of a bundle is compared (0 for the
    Sphere of a pair, 1 for its Talent).  Order follows the owner's list.
    """

    if not priority_ids:
        return list(candidates)
    by_id: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        if len(candidate.choice_ids) > position:
            by_id.setdefault(candidate.choice_ids[position], []).append(candidate)
    preferred: list[_Candidate] = []
    for priority_id in priority_ids:
        preferred.extend(by_id.get(priority_id, []))
    return preferred or list(candidates)


def _pair_candidates(request: Any, envelope: Any, committed: Any) -> list[_Candidate]:
    existing = {
        (row.get("sphere_id"), row.get("talent_id"))
        for row in _state_mapping(committed).get("pairs", [])
        if isinstance(row, Mapping)
    }
    acquired_talents = _committed_acquired_talent_ids(committed)
    # Creation grants one free Sphere plus the Background Sphere: the free
    # Sphere must be another Sphere (builds 29-31 took Beastmastery twice and
    # Stage 1 rejected the duplicate acquisition).
    background_spheres, _background_talents = _background_package_acquisitions(request, envelope, committed)
    result: dict[tuple[str, ...], _Candidate] = {}
    # The complete legal set first; the server's presented sample only as a
    # fallback for envelopes without typed authority.
    rows: list[Mapping[str, Any]] = list(_legal_free_pairs(request, envelope)) or list(_pair_rows(request, envelope))
    for row in rows:
        key = _pair_key(row)
        if key is None or key in existing or key[1] in acquired_talents or key[0] in background_spheres:
            continue
        sphere_id, talent_id = key
        result[(sphere_id, talent_id)] = _Candidate(
            (sphere_id, talent_id),
            _pair_cue(request, envelope, row, sphere_id, talent_id),
            OPTION_BUNDLE,
        )
    candidates = sorted(result.values(), key=_candidate_sort_key)
    # Owner decision 10: the owner's wizard priorities are binding.  The free
    # CL1 Sphere is the first priority Sphere with a legal pair; within it,
    # the owner's priority Talents win when any is legal.
    preferences = _owner_planning_preferences(request, envelope)
    for sphere_id in _owner_sphere_order(request, envelope, preferences):
        narrowed = [candidate for candidate in candidates if candidate.choice_ids[0] == sphere_id]
        if narrowed:
            candidates = narrowed
            break
    return _prefer_owner_priorities(candidates, preferences["talent_priority_ids"], position=1)


def _owner_sphere_order(request: Any, envelope: Any, preferences: Mapping[str, Sequence[str]]) -> list[str]:
    """Owner Spheres ranked by how many owner-priority Talents they own.

    Creation grants exactly one free Sphere (plus the Background Sphere), so
    the walk cannot serve every priority Sphere.  The Sphere that unlocks
    the most of the owner's priority Talents comes first; ties keep the
    owner's own Sphere order.
    """

    spheres = list(preferences.get("sphere_priority_ids") or [])
    talents = list(preferences.get("talent_priority_ids") or [])
    if not spheres or not talents:
        return spheres
    rows = _ordinary_typed_rows(request, envelope)
    owned: dict[str, int] = {}
    for talent_id in talents:
        row = rows.get(talent_id)
        if row is None:
            continue
        authority = _ordinary_typed_authority(request, envelope, talent_id, row)
        owner = authority.get("owning_canonical_sphere_id") or authority.get("owning_sphere_id") or authority.get("sphere_id")
        if isinstance(owner, str):
            owned[owner] = owned.get(owner, 0) + 1
    return sorted(spheres, key=lambda sphere_id: (-owned.get(sphere_id, 0), spheres.index(sphere_id)))


def build_sphere_free_talent_pair_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, pair_index: int = 1, ordinal: int = 1, page: int = 1) -> StepMenu | None:
    expected = _expected_count(request, envelope, "sphere_free_talent_pairs")
    if type(pair_index) is not int or pair_index < 1 or not expected or pair_index > expected:
        return None
    step_id = f"sphere_free_talent_pair:{pair_index}"
    candidates = _pair_candidates(request, envelope, committed)
    if not candidates or is_owner_locked(request, envelope, step_id) or is_owner_locked(request, envelope, "sphere_free_talent_pair"):
        return None
    return _make_menu(request, envelope, committed, step_id=step_id, step_kind="sphere_free_talent_pair", ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page)


def _route_modules(request: Any, envelope: Any) -> list[Mapping[str, Any]]:
    value = _first(request, envelope, "sphere_route_modules")
    if value is None:
        value = _response_contract(request, envelope).get("sphere_route_modules")
    if value is None:
        projection = _linear_projection(request, envelope)
        value = projection.get("sphere_route_modules")
        if value is None:
            value = _response_contract(projection, {}).get("sphere_route_modules")
    return [row for row in value or [] if isinstance(row, Mapping)] if isinstance(value, (list, tuple)) else []


def _route_id(row: Mapping[str, Any]) -> str | None:
    value = row.get("route_id")
    return value if isinstance(value, str) and value else None


def _route_sphere_id(row: Mapping[str, Any]) -> str | None:
    value = row.get("sphere_id")
    if isinstance(value, str) and value:
        return value
    sphere = row.get("sphere")
    if isinstance(sphere, Mapping) and isinstance(sphere.get("id"), str):
        return sphere["id"]
    return None


def _route_sphere_name(request: Any, envelope: Any, sphere_id: str | None) -> str | None:
    if not sphere_id:
        return None
    for source in (_mapping(envelope), _mapping(request)):
        for container_key in ("sphere_comparability_index", "sphere_comparability"):
            profiles = _mapping(source.get(container_key)).get("profiles")
            if isinstance(profiles, (list, tuple)):
                for profile in profiles:
                    if isinstance(profile, Mapping) and profile.get("sphere_id") == sphere_id:
                        for key in ("name", "display_name", "label"):
                            value = profile.get(key)
                            if isinstance(value, str) and value.strip():
                                return " ".join(value.split())[:MAX_CUE_LENGTH]
        for container_key in ("choices_by_slot", "allowed_choices_by_slot", "allowed_high_level"):
            slots = source.get(container_key)
            if not isinstance(slots, Mapping):
                continue
            for rows in slots.values():
                for candidate_row in _rows(rows):
                    if _choice_id(candidate_row) != sphere_id or not isinstance(candidate_row, Mapping):
                        continue
                    label = _typed_label(candidate_row, fallback="")
                    if label:
                        return label
    return None


def _route_cue(request: Any, envelope: Any, row: Mapping[str, Any]) -> str:
    sphere = row.get("sphere")
    sphere_name = row.get("sphere_name") if isinstance(row.get("sphere_name"), str) else None
    if sphere_name is None and isinstance(sphere, Mapping):
        sphere_name = sphere.get("name") if isinstance(sphere.get("name"), str) else None
    if sphere_name is None:
        sphere_name = _route_sphere_name(request, envelope, _route_sphere_id(row))
    tags = row.get("capability_tags")
    tag_text = ", ".join(value for value in tags if isinstance(value, str) and value) if isinstance(tags, (list, tuple)) else ""
    if sphere_name and tag_text:
        return f"{sphere_name} — {tag_text}"[:MAX_CUE_LENGTH]
    return (sphere_name or "Sphere route")[:MAX_CUE_LENGTH]


def _committed_pair_keys(committed: Any) -> set[tuple[str, str]]:
    return {
        (row.get("sphere_id"), row.get("talent_id"))
        for row in _state_mapping(committed).get("pairs", [])
        if isinstance(row, Mapping) and isinstance(row.get("sphere_id"), str) and isinstance(row.get("talent_id"), str)
    }


def _route_candidates(request: Any, envelope: Any, committed: Any) -> list[_Candidate]:
    pair_keys = _committed_pair_keys(committed)
    result: dict[tuple[str, ...], _Candidate] = {}
    for row in _route_modules(request, envelope):
        route_id = _route_id(row)
        pair = row.get("free_talent_pair") if isinstance(row.get("free_talent_pair"), Mapping) else row
        pair_key = _pair_key(pair) if isinstance(pair, Mapping) else None
        if route_id is None or pair_key is None or pair_key not in pair_keys:
            continue
        result[(route_id,)] = _Candidate((route_id,), _route_cue(request, envelope, row), OPTION_BUNDLE)
    return sorted(result.values(), key=_candidate_sort_key)


def build_sphere_route_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    state = _state_mapping(committed)
    if state.get("route_id") or is_owner_locked(request, envelope, "sphere_route"):
        return None
    candidates = _route_candidates(request, envelope, committed)
    if not candidates:
        return None
    return _make_menu(request, envelope, committed, step_id="sphere_route", step_kind="sphere_route", ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page)


def _route_for_state(request: Any, envelope: Any, committed: Any) -> Mapping[str, Any] | None:
    route_id = _state_mapping(committed).get("route_id")
    if not isinstance(route_id, str):
        return None
    return next((row for row in _route_modules(request, envelope) if row.get("route_id") == route_id), None)


def _route_assignment(row: Mapping[str, Any], cl: int) -> list[str]:
    assignments = row.get("ordinary_talent_ids_by_cl")
    if not isinstance(assignments, Mapping):
        return []
    value = assignments.get(str(cl), assignments.get(cl))
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _ordinary_row(request: Any, envelope: Any, talent_id: str) -> Mapping[str, Any] | None:
    for source in (_mapping(envelope), _mapping(request)):
        shortlist = source.get("ordinary_talent_shortlist_by_sphere")
        if isinstance(shortlist, Mapping):
            for rows in shortlist.values():
                for row in _rows(rows):
                    if _choice_id(row) == talent_id and isinstance(row, Mapping):
                        return row
        for key in ("choices_by_slot", "allowed_choices_by_slot", "allowed_high_level"):
            slots = source.get(key)
            if isinstance(slots, Mapping):
                for slot_id, rows in slots.items():
                    if slot_id not in {"advancement_skeleton", "ordinary_talent"}:
                        continue
                    for row in _rows(rows):
                        if _choice_id(row) == talent_id and isinstance(row, Mapping):
                            return row
    return None


def _ordinary_typed_rows(request: Any, envelope: Any) -> dict[str, Mapping[str, Any]]:
    """Return the frozen typed advancement rows keyed by their canonical ID."""

    result: dict[str, Mapping[str, Any]] = {}
    allowed = _slot_allowed(request, envelope, "advancement_skeleton")
    for source in (_mapping(envelope), _mapping(request)):
        slots = source.get("choices_by_slot")
        rows = slots.get("advancement_skeleton") if isinstance(slots, Mapping) else None
        if isinstance(rows, Mapping):
            items = rows.items()
        elif isinstance(rows, (list, tuple)):
            items = ((None, row) for row in rows)
        else:
            continue
        for raw_id, raw_row in items:
            choice_id = str(raw_id) if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else _choice_id(raw_row)
            if not isinstance(choice_id, str) or not choice_id or (allowed is not None and choice_id not in allowed):
                continue
            row = dict(raw_row) if isinstance(raw_row, Mapping) else {}
            row.setdefault("choice_id", choice_id)
            result.setdefault(choice_id, row)
    return result


def _ordinary_typed_authority(request: Any, envelope: Any, choice_id: str, row: Mapping[str, Any]) -> Mapping[str, Any]:
    for source in (_mapping(envelope), _mapping(request)):
        typed = source.get("typed_choice_authority_by_slot")
        slot = typed.get("advancement_skeleton") if isinstance(typed, Mapping) else None
        by_choice = slot.get("stage2_authority_by_choice") if isinstance(slot, Mapping) else None
        authority = by_choice.get(choice_id) if isinstance(by_choice, Mapping) else None
        if isinstance(authority, Mapping):
            return authority
    authority = row.get("stage2_authority")
    if isinstance(authority, Mapping):
        return authority
    compatibility = row.get("compatibility")
    factory = compatibility.get("factory") if isinstance(compatibility, Mapping) else None
    authority = factory.get("stage2_authority") if isinstance(factory, Mapping) else None
    return authority if isinstance(authority, Mapping) else {}


def _ordinary_typed_minimum_cl(request: Any, envelope: Any, choice_id: str, row: Mapping[str, Any], authority: Mapping[str, Any]) -> int | None:
    availability_by_id: Mapping[str, Any] = {}
    for source in (_mapping(envelope), _mapping(request)):
        prerequisites = source.get("prerequisites_and_availability")
        rows = prerequisites.get("advancement_skeleton") if isinstance(prerequisites, Mapping) else None
        if isinstance(rows, Mapping):
            availability_by_id = rows
            break
    source_row = availability_by_id.get(choice_id) if isinstance(availability_by_id, Mapping) else None
    availability = source_row.get("availability") if isinstance(source_row, Mapping) else None
    for value in (
        authority.get("minimum_cl"),
        row.get("minimum_cl"),
        row.get("availability", {}).get("minimum_cl") if isinstance(row.get("availability"), Mapping) else None,
        availability.get("minimum_cl") if isinstance(availability, Mapping) else None,
    ):
        if type(value) is int:
            return value
    return None


def _known_sphere_ids(request: Any, envelope: Any, committed: Any, *, current_cl: int | None = None) -> set[str]:
    """The Spheres this character knows at creation, as the validator counts them.

    Rulebook: a level talent is chosen from a Sphere you already know.  At
    creation those are the CL1 free Sphere(s) from the committed
    sphere/free-Talent pairs and the Background Sphere.  The validator
    resolves the Background Sphere through its explicit sealed canonical
    relation; the walk reuses that resolver and never consults display names
    or the live catalog.
    """

    state = _state_mapping(committed)
    known = {
        row.get("sphere_id")
        for row in state.get("pairs", [])
        if isinstance(row, Mapping) and isinstance(row.get("sphere_id"), str) and row.get("sphere_id")
    }
    trained_spheres, _trained_talents = _committed_training_ids(committed, max_cl=current_cl)
    known.update(trained_spheres)
    choices_by_slot = _first(request, envelope, "choices_by_slot")
    choices_by_slot = choices_by_slot if isinstance(choices_by_slot, Mapping) else {}
    selected_backgrounds = _state_slot(committed, "background_choice")
    selected_spheres = _state_slot(committed, "background_sphere_choice")
    if selected_backgrounds and selected_spheres:
        selected_by_slot = {
            "background_choice": selected_backgrounds,
            "background_sphere_choice": selected_spheres,
            "background_talent_choice": _state_slot(committed, "background_talent_choice"),
        }
        typed_authority = _first(request, envelope, "typed_choice_authority_by_slot")
        typed_authority = typed_authority if isinstance(typed_authority, Mapping) else {}
        try:
            resolved = canonical_selected_background_sphere_ids(
                selected_by_slot,
                choices_by_slot,
                typed_authority,
            )
        except SealedBackgroundSphereResolutionError:
            resolved = {}
        known.update(resolved.values())
    return known


def _talent_sphere_id(request: Any, envelope: Any, talent_id: str, row: Any = None) -> str | None:
    """The owning canonical Sphere of a talent from sealed typed authority only."""

    authority = _ordinary_typed_authority(request, envelope, talent_id, row if isinstance(row, Mapping) else {})
    for key in ("owning_canonical_sphere_id", "sphere_id"):
        value = authority.get(key) if isinstance(authority, Mapping) else None
        if isinstance(value, str) and value:
            return value
    for source in (_mapping(envelope), _mapping(request), _linear_projection(request, envelope)):
        shortlist = source.get("ordinary_talent_shortlist_by_sphere")
        if not isinstance(shortlist, Mapping):
            continue
        for sphere_id, rows in shortlist.items():
            if any(_choice_id(candidate) == talent_id for candidate in _rows(rows)):
                return str(sphere_id)
    return None


def _talent_from_known_sphere(request: Any, envelope: Any, committed: Any, talent_id: str, row: Any = None, known: set[str] | None = None) -> bool:
    """Mirror the validator: a talent with a typed owning Sphere must belong to a known Sphere."""

    sphere_id = _talent_sphere_id(request, envelope, talent_id, row)
    if sphere_id is None:
        return True
    return sphere_id in (known if known is not None else _known_sphere_ids(request, envelope, committed))


def _ordinary_typed_candidates(request: Any, envelope: Any, committed: Any, cl: int) -> list[_Candidate]:
    acquired_talents = _committed_acquired_talent_ids(committed)
    acquired_talents.update(_background_package_acquisitions(request, envelope, committed)[1])
    known_spheres = _known_sphere_ids(request, envelope, committed, current_cl=cl)
    result: dict[tuple[str, ...], _Candidate] = {}
    for choice_id, row in _ordinary_typed_rows(request, envelope).items():
        if _is_non_talent_record(row):
            continue
        authority = _ordinary_typed_authority(request, envelope, choice_id, row)
        if authority.get("authority_complete") is not True:
            continue
        if "level_talent_acquisition" not in (authority.get("allowed_kinds") or []):
            continue
        if not (authority.get("allowed_channels") or []):
            continue
        minimum_cl = _ordinary_typed_minimum_cl(request, envelope, choice_id, row, authority)
        if type(minimum_cl) is int and minimum_cl > cl:
            continue
        if choice_id in acquired_talents:
            continue
        if not _talent_from_known_sphere(request, envelope, committed, choice_id, row, known_spheres):
            continue
        result[(choice_id,)] = _Candidate(
            (choice_id,),
            _typed_label(row, fallback="Ordinary Talent"),
            OPTION_PICK,
        )
    # Talent requirements (rulebook: Sphere, Realm, CL, Path, earlier talent)
    # are typed prerequisites on the skeleton rows; the validator checks them
    # against the acquisitions, so the menu does too.
    return _frozen_legality_filter(request, envelope, committed, "advancement_skeleton", sorted(result.values(), key=_candidate_sort_key), planning=False, causal_cl=cl)


def _ordinary_candidates(request: Any, envelope: Any, committed: Any, route: Mapping[str, Any] | None, cl: int) -> list[_Candidate]:
    if route is None:
        return _ordinary_typed_candidates(request, envelope, committed, cl)
    acquired_talents = _committed_acquired_talent_ids(committed)
    acquired_talents.update(_background_package_acquisitions(request, envelope, committed)[1])
    known_spheres = _known_sphere_ids(request, envelope, committed, current_cl=cl)
    result: dict[tuple[str, ...], _Candidate] = {}
    for talent_id in _route_assignment(route, cl):
        if talent_id in acquired_talents:
            continue
        row = _ordinary_row(request, envelope, talent_id)
        if _is_non_talent_record(row):
            continue
        if not _talent_from_known_sphere(request, envelope, committed, talent_id, row, known_spheres):
            continue
        cue = _typed_label(row, fallback="Ordinary Talent") if isinstance(row, Mapping) else "Ordinary Talent"
        result[(talent_id,)] = _Candidate((talent_id,), cue, OPTION_PICK)
    return _frozen_legality_filter(request, envelope, committed, "advancement_skeleton", sorted(result.values(), key=_candidate_sort_key), planning=False, causal_cl=cl)


def build_ordinary_talent_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, cl: int, ordinal: int = 1, page: int = 1) -> StepMenu | None:
    if type(cl) is not int or cl < 1:
        return None
    route = _route_for_state(request, envelope, committed)
    if str(cl) in _mapping(_state_mapping(committed).get("ordinary_by_cl")):
        return None
    step_id = f"ordinary_talent:{cl}"
    if is_owner_locked(request, envelope, step_id) or is_owner_locked(request, envelope, "ordinary_talent"):
        return None
    candidates = _ordinary_candidates(request, envelope, committed, route, cl)
    if not candidates:
        return None
    # Owner decision 10: a legal owner-priority Talent is always taken before
    # any other level talent.
    candidates = _prefer_owner_priorities(candidates, _owner_planning_preferences(request, envelope)["talent_priority_ids"])
    return _make_menu(request, envelope, committed, step_id=step_id, step_kind="ordinary_talent", ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page)


def _creation_training_contract(request: Any, envelope: Any) -> Mapping[str, Any] | None:
    for source in (_mapping(envelope), _mapping(request)):
        contract = source.get("creation_training_contract")
        if isinstance(contract, Mapping):
            return contract
        authority = source.get("complete_character_source_authority")
        if isinstance(authority, Mapping) and isinstance(authority.get("creation_training_contract"), Mapping):
            return authority["creation_training_contract"]
    return None


def _creation_training_choice_rows(request: Any, envelope: Any) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for source in (_mapping(envelope), _mapping(request)):
        slots = source.get("choices_by_slot")
        if not isinstance(slots, Mapping):
            continue
        for slot_rows in slots.values():
            if isinstance(slot_rows, Mapping):
                items = slot_rows.items()
            else:
                items = ((None, value) for value in _rows(slot_rows))
            for raw_id, raw_row in items:
                if not isinstance(raw_row, Mapping):
                    continue
                record_id = str(raw_id) if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else _choice_id(raw_row)
                if isinstance(record_id, str) and record_id:
                    result.setdefault(record_id, raw_row)
    return result


def _creation_training_route_row(
    request: Any,
    envelope: Any,
    record_id: str,
    choice_type: str,
    choice_rows: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Return the row whose typed legality Stage 2 will apply to a route."""

    row = choice_rows.get(record_id)
    if isinstance(row, Mapping):
        return row
    slot_id = "sphere_priorities" if choice_type == "new_sphere" else "advancement_skeleton"
    rows = _slot_rows_by_id(request, envelope, slot_id)
    return rows.get(record_id) or {}


def _creation_training_constraint(route: Mapping[str, Any], row: Mapping[str, Any], key: str) -> Any:
    value = route.get(key)
    if value is not None:
        return value
    value = row.get(key)
    if value is not None:
        return value
    legality = row.get("legality")
    if isinstance(legality, Mapping) and legality.get(key) is not None:
        return legality.get(key)
    availability = row.get("availability")
    if key == "minimum_cl" and isinstance(availability, Mapping):
        return availability.get(key)
    return None


def _creation_training_route_legal(
    route: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    cl: int,
    present: set[str],
    choice_ids: Sequence[str],
    prior_choice_ids: Sequence[str] = (),
) -> bool:
    """Mirror typed Stage 2 legality against the state before this choice."""

    effective_route = dict(route)
    for key in ("access_category", "minimum_cl", "allowed_cls", "realm_rules", "prerequisites", "incompatibilities"):
        value = _creation_training_constraint(route, row, key)
        if value is not None:
            effective_route[key] = value
    return not creation_route_legality_errors(
        effective_route,
        cl=cl,
        present_ids=present,
        candidate_ids=tuple(choice_ids),
        prior_choice_ids=tuple(prior_choice_ids),
    )


def _owner_or_state_ids(
    request: Any,
    envelope: Any,
    committed: Any,
    slot_id: str,
) -> set[str]:
    """Return selected and sealed owner-locked IDs for one Background slot."""

    result = set(_state_slot(committed, slot_id))
    owner_slots = _owner_locks(request, envelope)
    if isinstance(owner_slots, Mapping):
        result.update(_allowed_ids(owner_slots.get(slot_id)) or set())
    for lock in _sealed_owner_locks(request, envelope):
        field = lock.get("field")
        if isinstance(field, str) and field.rsplit(".", 1)[-1] == slot_id:
            result.update(_allowed_ids(lock.get("value")) or set())
    return {value for value in result if isinstance(value, str) and value}


def _background_package_linkage(request: Any, envelope: Any) -> Mapping[str, Any]:
    """Return the sealed Background-to-canonical package relation, if present."""

    for source in (_mapping(envelope), _mapping(request)):
        typed = source.get("typed_choice_authority_by_slot")
        background = typed.get("background_choice") if isinstance(typed, Mapping) else None
        linkage = background.get("background_package_linkage") if isinstance(background, Mapping) else None
        if isinstance(linkage, Mapping):
            return linkage
        contract = background.get("authority_contract") if isinstance(background, Mapping) else None
        linkage = contract.get("background_package_linkage") if isinstance(contract, Mapping) else None
        if isinstance(linkage, Mapping):
            return linkage
    return {}


def _background_package_acquisitions(
    request: Any,
    envelope: Any,
    committed: Any,
) -> tuple[set[str], set[str]]:
    """Resolve selected Background aliases to explicit canonical holdings."""

    selected_backgrounds = _owner_or_state_ids(request, envelope, committed, "background_choice")
    selected_spheres = _owner_or_state_ids(request, envelope, committed, "background_sphere_choice")
    selected_talents = _owner_or_state_ids(request, envelope, committed, "background_talent_choice")
    if not selected_backgrounds or not selected_spheres:
        return set(), set()

    selected_by_slot = {
        "background_choice": tuple(selected_backgrounds),
        "background_sphere_choice": tuple(selected_spheres),
        "background_talent_choice": tuple(selected_talents),
    }
    choices_by_slot = _first(request, envelope, "choices_by_slot")
    choices_by_slot = choices_by_slot if isinstance(choices_by_slot, Mapping) else {}
    typed_authority = _first(request, envelope, "typed_choice_authority_by_slot")
    typed_authority = typed_authority if isinstance(typed_authority, Mapping) else {}
    try:
        canonical_background_ids = canonical_selected_background_sphere_ids(
            selected_by_slot,
            choices_by_slot,
            typed_authority,
        )
    except SealedBackgroundSphereResolutionError:
        # An explicit Sphere row or display-name match cannot establish
        # Background ownership without its selected sealed package relation.
        return set(), set()
    if not canonical_background_ids:
        return set(), set()
    package_spheres, package_talents = canonical_background_package_ids(
        selected_by_slot,
        typed_authority,
    )
    known_spheres = set(canonical_background_ids.values()) | package_spheres
    known_talents = set(package_talents)
    # Keep a selected source alias reserved for duplicate detection only after
    # the same authenticated package has established canonical ownership.
    for background_id, raw_packages in _background_package_linkage(request, envelope).items():
        if not isinstance(background_id, str):
            continue
        packages = _rows(raw_packages)
        for package in packages:
            if not isinstance(package, Mapping):
                continue
            sphere_choice_id = package.get("background_sphere_choice_id")
            talent_choice_id = package.get("background_talent_choice_id")
            if selected_backgrounds and background_id not in selected_backgrounds:
                continue
            if (
                isinstance(sphere_choice_id, str)
                and sphere_choice_id in selected_spheres
                and isinstance(talent_choice_id, str)
                and talent_choice_id in selected_talents
            ):
                known_talents.add(talent_choice_id)
    return known_spheres, known_talents


def _creation_training_known_ids(
    request: Any,
    envelope: Any,
    committed: Any,
    *,
    causal_cl: int | None = None,
) -> tuple[set[str], set[str], set[str]]:
    """Return causal holdings plus every acquisition reserved for duplicates."""

    state = _state_mapping(committed)
    known_spheres = _known_sphere_ids(request, envelope, committed, current_cl=causal_cl)
    known_talents: set[str] = set()
    used: set[str] = set()
    for pair in state.get("pairs") or ():
        if not isinstance(pair, Mapping):
            continue
        for key, target in (("sphere_id", known_spheres), ("talent_id", known_talents)):
            value = pair.get(key)
            if isinstance(value, str):
                target.add(value)
                used.add(value)
    for values in (state.get("by_slot") or {}).values() if isinstance(state.get("by_slot"), Mapping) else ():
        if isinstance(values, (list, tuple)):
            used.update(value for value in values if isinstance(value, str))
    ordinary = state.get("ordinary_by_cl")
    if isinstance(ordinary, Mapping):
        for raw_cl, value in ordinary.items():
            if not isinstance(value, str) or not value:
                continue
            used.add(value)
            if causal_cl is None:
                known_talents.add(value)
                continue
            try:
                ordinary_cl = int(raw_cl)
            except (TypeError, ValueError):
                continue
            if ordinary_cl < causal_cl:
                known_talents.add(value)
    for row in state.get("trained_choices") or ():
        if not isinstance(row, Mapping):
            continue
        record_id = row.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            continue
        used.add(record_id)
        row_cl = row.get("cl")
        visible = causal_cl is None or (type(row_cl) is int and row_cl <= causal_cl)
        bonus_id = row.get("bonus_talent_id")
        if isinstance(bonus_id, str) and bonus_id:
            used.add(bonus_id)
        if not visible:
            continue
        if row.get("choice_type") == "new_sphere":
            known_spheres.add(record_id)
            if isinstance(bonus_id, str) and bonus_id:
                known_talents.add(bonus_id)
        elif row.get("choice_type") == "known_sphere_talent":
            known_talents.add(record_id)
    background_spheres, background_talents = _background_package_acquisitions(request, envelope, committed)
    known_spheres.update(background_spheres)
    known_talents.update(background_talents)
    used.update(background_spheres)
    used.update(background_talents)
    return known_spheres, known_talents, used


def build_creation_training_menu(
    request: Mapping[str, Any],
    envelope: Mapping[str, Any],
    committed: Any = None,
    *,
    cl: int,
    slot: int,
    ordinal: int = 1,
    page: int = 1,
) -> StepMenu | None:
    """Build one bounded constructed-training choice plus its Sphere bonus."""

    if type(cl) is not int or cl < 1 or type(slot) is not int or not 1 <= slot <= CREATION_TRAINING_MAX_PER_CL:
        return None
    committed_map = _state_mapping(committed)
    skipped = committed_map.get("trained_choice_skips") or []
    if cl in skipped:
        return None
    step_id = f"creation_training:{cl}:{slot}"
    if is_owner_locked(request, envelope, step_id) or is_owner_locked(request, envelope, "creation_training"):
        return None
    contract = _creation_training_contract(request, envelope)
    if contract is None or validate_creation_training_contract(contract):
        return None
    target_cl = contract.get("target_cl")
    if type(target_cl) is not int or cl > target_cl:
        return None
    routes = contract.get("records")
    if not isinstance(routes, Mapping):
        return None
    known_spheres, known_talents, used = _creation_training_known_ids(request, envelope, committed, causal_cl=cl)
    choice_rows = _creation_training_choice_rows(request, envelope)
    sphere_allowed = _slot_allowed(request, envelope, "sphere_priorities")
    talent_allowed = _slot_allowed(request, envelope, "advancement_skeleton")
    present = _committed_present_ids(request, envelope, committed, planning=False, causal_cl=cl)
    present.update(known_spheres)
    present.update(known_talents)
    preferences = _owner_planning_preferences(request, envelope)
    sphere_priority = {value: index for index, value in enumerate(preferences["sphere_priority_ids"])}
    talent_priority = {value: index for index, value in enumerate(preferences["talent_priority_ids"])}
    candidates: list[_Candidate] = []
    for record_id, route in sorted(routes.items(), key=lambda item: str(item[0])):
        if not isinstance(record_id, str) or not isinstance(route, Mapping) or record_id in used:
            continue
        choice_type = route.get("choice_type")
        if choice_type == "new_sphere":
            if record_id in known_spheres or (sphere_allowed is not None and record_id not in sphere_allowed):
                continue
            sphere_row = _creation_training_route_row(request, envelope, record_id, "new_sphere", choice_rows)
            if not _creation_training_kind_allowed(
                request,
                envelope,
                route,
                record_id,
                "new_sphere",
                sphere_row,
                CREATION_TRAINING_SPHERE_KIND,
            ):
                continue
            if not _creation_training_route_legal(
                route,
                sphere_row,
                cl=cl,
                present=present,
                choice_ids=(record_id,),
            ):
                continue
            bonus_routes = [
                (bonus_id, bonus_route)
                for bonus_id, bonus_route in routes.items()
                if isinstance(bonus_id, str)
                and isinstance(bonus_route, Mapping)
                and bonus_route.get("choice_type") == "known_sphere_talent"
                and bonus_route.get("content_type") == "talent"
                and bonus_route.get("owning_sphere_id") == record_id
                and bonus_route.get("bonus_talent_eligible") is True
                and bonus_id not in known_talents
                and bonus_id not in used
                and (talent_allowed is None or bonus_id in talent_allowed)
                and _creation_training_kind_allowed(
                    request,
                    envelope,
                    bonus_route,
                    bonus_id,
                    "known_sphere_talent",
                    _creation_training_route_row(request, envelope, bonus_id, "known_sphere_talent", choice_rows),
                    CREATION_TRAINING_BONUS_KIND,
                )
                and _creation_training_route_legal(
                    bonus_route,
                    _creation_training_route_row(request, envelope, bonus_id, "known_sphere_talent", choice_rows),
                    cl=cl,
                    present=present,
                    choice_ids=(record_id, bonus_id),
                    prior_choice_ids=(record_id,),
                )
            ]
            if not bonus_routes:
                continue
            for bonus_id, _bonus_route in sorted(bonus_routes, key=lambda item: item[0]):
                bonus_row = _creation_training_route_row(request, envelope, bonus_id, "known_sphere_talent", choice_rows)
                sphere_cue = _typed_label(sphere_row, fallback="New Sphere") if isinstance(sphere_row, Mapping) else "New Sphere"
                bonus_cue = _typed_label(bonus_row, fallback="Bonus Talent") if isinstance(bonus_row, Mapping) else "Bonus Talent"
                candidates.append(_Candidate((record_id, bonus_id), f"{sphere_cue} + {bonus_cue}"[:MAX_CUE_LENGTH], OPTION_BUNDLE))
        elif choice_type == "known_sphere_talent":
            owning_sphere = route.get("owning_sphere_id")
            if record_id in known_talents or not isinstance(owning_sphere, str) or owning_sphere not in known_spheres:
                continue
            if talent_allowed is not None and record_id not in talent_allowed:
                continue
            source_row = _creation_training_route_row(request, envelope, record_id, "known_sphere_talent", choice_rows)
            if not _creation_training_kind_allowed(
                request,
                envelope,
                route,
                record_id,
                "known_sphere_talent",
                source_row,
                CREATION_TRAINING_TALENT_KIND,
            ):
                continue
            if not _creation_training_route_legal(
                route,
                source_row,
                cl=cl,
                present=present,
                choice_ids=(record_id,),
            ):
                continue
            candidates.append(_Candidate((record_id,), _typed_label(source_row, fallback="Known-Sphere Talent") if isinstance(source_row, Mapping) else "Known-Sphere Talent", OPTION_PICK))
    candidates = [
        candidate for candidate in candidates
        if all(_structural_gates_met(request, envelope, choice_id, set(present) | set(candidate.choice_ids)) for choice_id in candidate.choice_ids)
    ]
    # Reserve the Sphere route's planned ordinary Talents (this CL and later)
    # for the ordinary lane: training that takes them can leave a later CL
    # with no legal ordinary Talent (a single-Sphere Alchemy character
    # dead-ended at CL4).  Fall back to them only when nothing else is legal.
    planned_route = _route_for_state(request, envelope, committed)
    target_cl = _frozen_target_cl(request, envelope) or cl
    if planned_route is not None:
        reserved: set[str] = set()
        for future_cl in range(cl, int(target_cl) + 1):
            reserved.update(talent_id for talent_id in _route_assignment(planned_route, future_cl) if isinstance(talent_id, str))
        unreserved = [candidate for candidate in candidates if not reserved.intersection(candidate.choice_ids)]
        if unreserved:
            candidates = unreserved
    # The ordinary lane follows the final training slot at this CL.  Training
    # may consume its last available Talent, but only when that acquisition
    # unlocks another legal ordinary choice.  Earlier training slots may still
    # build prerequisite chains, so apply this guard at the lane boundary.
    if (
        slot == CREATION_TRAINING_MAX_PER_CL
        and cl <= _expected_count(request, envelope, "ordinary_talent_ids")
        and str(cl) not in _mapping(committed_map.get("ordinary_by_cl"))
        and not is_owner_locked(request, envelope, "ordinary_talent")
        and not is_owner_locked(request, envelope, f"ordinary_talent:{cl}")
    ):
        ordinary_route = _route_for_state(request, envelope, committed)
        ordinary_ids = {
            candidate.choice_ids[0]
            for candidate in _ordinary_candidates(request, envelope, committed, ordinary_route, cl)
        }
        viable = []
        for candidate in candidates:
            if ordinary_ids - set(candidate.choice_ids):
                viable.append(candidate)
                continue
            choice = {
                "cl": cl,
                "slot": slot,
                "choice_type": "new_sphere" if candidate.kind == OPTION_BUNDLE else "known_sphere_talent",
                "record_id": candidate.choice_ids[0],
            }
            if candidate.kind == OPTION_BUNDLE:
                choice["bonus_talent_id"] = candidate.choice_ids[1]
            trial = dict(committed_map)
            trial["trained_choices"] = [*(committed_map.get("trained_choices") or []), choice]
            if _ordinary_candidates(request, envelope, trial, ordinary_route, cl):
                viable.append(candidate)
        candidates = viable
    # The walk asks for one slot at a time.  This keeps each model decision
    # bounded while the contract enforces the cumulative three-choice cap.
    uncategorized_rank = len(routes) + len(preferences["sphere_priority_ids"]) + len(preferences["talent_priority_ids"]) + 1

    # Without an owner priority, options that fit the concept come first
    # (this list is capped below, so alphabetical order hid e.g. Poison).
    concept_stems = _concept_stems(request, envelope, committed)
    concept_index = _concept_text_index(request, envelope) if concept_stems else {}

    def concept_rank(candidate: _Candidate) -> int:
        if not concept_stems:
            return 0
        score = _concept_score(concept_stems, concept_index, candidate)
        # Depth over breadth: a new Sphere must fit the concept clearly better
        # than deepening a known one (unweighted, walks collected 10+ Spheres).
        if candidate.kind == OPTION_BUNDLE:
            score -= 2
        return -score

    def priority_key(candidate: _Candidate) -> tuple[Any, ...]:
        if candidate.kind == OPTION_BUNDLE:
            sphere_id, bonus_id = candidate.choice_ids
            sphere_rank = sphere_priority.get(sphere_id, uncategorized_rank)
            talent_rank = talent_priority.get(bonus_id, uncategorized_rank)
            if sphere_rank < uncategorized_rank:
                return (0, sphere_rank, talent_rank, *_candidate_sort_key(candidate))
            if talent_rank < uncategorized_rank:
                return (0, talent_rank, sphere_rank, *_candidate_sort_key(candidate))
            return (1, concept_rank(candidate), 1, *_candidate_sort_key(candidate))
        talent_id = candidate.choice_ids[0]
        talent_rank = talent_priority.get(talent_id, uncategorized_rank)
        return (0, talent_rank, uncategorized_rank, *_candidate_sort_key(candidate)) if talent_rank < uncategorized_rank else (1, concept_rank(candidate), 0, *_candidate_sort_key(candidate))

    candidates = sorted(candidates, key=priority_key)
    required = contract.get("required_choices_per_cl") == 3
    # This cap has to fit the pager, not just the nominal ceiling.  _page_slice
    # uses one shorter page whenever more than a full page remains, so three
    # pages drain at most (2 x (MAX_OPTIONS_PER_PAGE - 1)) + MAX_OPTIONS_PER_PAGE
    # = 34, and the deferral candidate appended below needs a slot of its own.
    # Capping at the full 36 produced a step that emptied no page and failed the
    # walk with DCC_LINEAR_PAGE_LIMIT (observed: creation_training:2:2).
    drainable = 2 * (MAX_OPTIONS_PER_PAGE - 1) + MAX_OPTIONS_PER_PAGE
    budget = drainable - (0 if required else 1)
    if len(candidates) > budget:
        candidates = candidates[:budget]
    if not required:
        candidates.append(_Candidate((), "No constructed training at this CL", OPTION_NONE))
    if not candidates:
        return None
    return _make_menu(
        request,
        envelope,
        committed,
        step_id=step_id,
        step_kind="creation_training",
        ordinal=ordinal,
        minimum=1 if required else 0,
        maximum=1,
        candidates=candidates,
        page=page,
        preserve_candidate_order=True,
    )


def creation_training_required_gap(
    request: Mapping[str, Any],
    envelope: Mapping[str, Any],
    committed: Any,
    step_id: str,
) -> dict[str, Any] | None:
    """Explain a required constructed-training step that has no legal menu.

    ``build_creation_training_menu`` returns ``None`` both when a step is not
    applicable (past the target CL, owner-locked, or skipped under a standard
    contract) and when a rival/boss contract requires a choice that no sealed
    route can satisfy.  The walk must not treat the second case as progress:
    it is a missing mandatory acquisition, and completing around it produced
    a response the final validator rejected with a bare count mismatch.
    Return bounded, source-grounded detail for that case, or ``None`` when
    the step is simply not applicable.
    """

    parts = step_id.split(":")
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        return None
    cl, slot = int(parts[1]), int(parts[2])
    if cl < 1 or not 1 <= slot <= CREATION_TRAINING_MAX_PER_CL:
        return None
    contract = _creation_training_contract(request, envelope)
    if contract is None or validate_creation_training_contract(contract):
        return None
    if contract.get("required_choices_per_cl") != 3:
        return None
    target_cl = contract.get("target_cl")
    if type(target_cl) is not int or cl > target_cl:
        return None
    if cl in (_state_mapping(committed).get("trained_choice_skips") or []):
        return None
    if is_owner_locked(request, envelope, step_id) or is_owner_locked(request, envelope, "creation_training"):
        return None
    routes = contract.get("records") if isinstance(contract.get("records"), Mapping) else {}
    known_spheres, known_talents, used = _creation_training_known_ids(request, envelope, committed, causal_cl=cl)
    choice_rows = _creation_training_choice_rows(request, envelope)
    sphere_routes = sorted(
        record_id
        for record_id, route in routes.items()
        if isinstance(record_id, str) and isinstance(route, Mapping) and route.get("choice_type") == "new_sphere"
    )
    unauthorized_spheres = [
        record_id
        for record_id in sphere_routes
        if not _creation_training_kind_allowed(
            request,
            envelope,
            routes[record_id],
            record_id,
            "new_sphere",
            _creation_training_route_row(request, envelope, record_id, "new_sphere", choice_rows),
            CREATION_TRAINING_SPHERE_KIND,
        )
    ]
    talent_routes = [
        record_id
        for record_id, route in routes.items()
        if isinstance(record_id, str) and isinstance(route, Mapping) and route.get("choice_type") == "known_sphere_talent"
    ]
    known_sphere_talent_routes = [record_id for record_id in talent_routes if routes[record_id].get("owning_sphere_id") in known_spheres]
    unused_known = [record_id for record_id in known_sphere_talent_routes if record_id not in used and record_id not in known_talents]
    preferences = _owner_planning_preferences(request, envelope)
    return {
        "step_id": step_id,
        "cl": cl,
        "slot": slot,
        "target_cl": target_cl,
        "required_choices_per_cl": 3,
        "reason": "no_legal_constructed_training_candidate",
        "known_sphere_ids": sorted(known_spheres)[:24],
        "known_talent_count": len(known_talents),
        "new_sphere_route_count": len(sphere_routes),
        "new_sphere_routes_without_exact_training_authority": len(unauthorized_spheres),
        "known_sphere_talent_route_count": len(known_sphere_talent_routes),
        "known_sphere_talent_routes_unused": len(unused_known),
        "owner_sphere_priority_ids": list(preferences["sphere_priority_ids"])[:24],
    }


def mandatory_completion_gaps(
    request: Mapping[str, Any],
    envelope: Mapping[str, Any],
    committed: Any,
) -> dict[str, Any] | None:
    """Mandatory acquisitions still missing before the walk may complete.

    The descriptor loop emits one causal step at a time and skips any step
    whose menu is ``None``.  Completion must therefore prove, independently
    of that loop, that every constructed-training slot a rival/boss contract
    requires and every ordinary level Talent the frozen count requires has
    been committed.  Owner-sealed steps were applied before any menu and are
    never gaps.  Returns ``None`` when nothing mandatory is missing.
    """

    gaps: dict[str, Any] = {}
    method_gap = method_required_gap(request, envelope, committed)
    if method_gap is None:
        target_cl_for_method = _frozen_target_cl(request, envelope)
        if type(target_cl_for_method) is int and target_cl_for_method >= 1 and not _state_slot(committed, "method_choice") and not is_owner_locked(request, envelope, "method_choice"):
            gaps["method_required"] = True
            gaps["next_step_id"] = "method_choice"
            gaps["reason"] = "mandatory_acquisitions_incomplete"
    else:
        gaps["method_required"] = True
        gaps["method_gap"] = method_gap
        gaps["next_step_id"] = "method_choice"
        gaps["reason"] = "mandatory_acquisitions_incomplete"
    missing_subpath_paths = subpath_required_path_ids(request, envelope, committed)
    if missing_subpath_paths:
        gaps["subpath_required_for_path_ids"] = list(missing_subpath_paths)
        gaps.setdefault("next_step_id", f"subpath_choice:{missing_subpath_paths[0]}:required")
        gaps["reason"] = "mandatory_acquisitions_incomplete"
    contract = _creation_training_contract(request, envelope)
    if contract is None or validate_creation_training_contract(contract):
        return gaps or None
    target_cl = contract.get("target_cl")
    if type(target_cl) is not int or target_cl < 1:
        return gaps or None
    state = _state_mapping(committed)
    next_training: tuple[int, str] | None = None
    if contract.get("required_choices_per_cl") == 3 and not is_owner_locked(request, envelope, "creation_training"):
        counts: dict[int, int] = {}
        for row in state.get("trained_choices") or ():
            if isinstance(row, Mapping) and type(row.get("cl")) is int:
                counts[row["cl"]] = counts.get(row["cl"], 0) + 1
        missing = {
            str(cl): CREATION_TRAINING_MAX_PER_CL - counts.get(cl, 0)
            for cl in range(1, target_cl + 1)
            if counts.get(cl, 0) < CREATION_TRAINING_MAX_PER_CL
            and not is_owner_locked(request, envelope, f"creation_training:{cl}:{counts.get(cl, 0) + 1}")
        }
        if missing:
            first = min(int(cl) for cl in missing)
            gaps["trained_choices_missing_by_cl"] = missing
            next_training = (first, f"creation_training:{first}:{counts.get(first, 0) + 1}")
    next_ordinary: tuple[int, str] | None = None
    expected_ordinary = _expected_count(request, envelope, "ordinary_talent_ids")
    if expected_ordinary and not is_owner_locked(request, envelope, "ordinary_talent"):
        ordinary = state.get("ordinary_by_cl") if isinstance(state.get("ordinary_by_cl"), Mapping) else {}
        missing_cls = [
            cl
            for cl in range(1, expected_ordinary + 1)
            if str(cl) not in ordinary and not is_owner_locked(request, envelope, f"ordinary_talent:{cl}")
        ]
        if missing_cls:
            gaps["ordinary_talent_missing_cls"] = missing_cls
            next_ordinary = (missing_cls[0], f"ordinary_talent:{missing_cls[0]}")
    if not gaps:
        return None
    # Training slots precede that CL's ordinary Talent in the causal order.
    candidates = [row for row in (next_training, next_ordinary) if row is not None]
    if candidates and "next_step_id" not in gaps:
        gaps["next_step_id"] = min(candidates, key=lambda row: (row[0], 0 if row[1].startswith("creation_training") else 1))[1]
    gaps["target_cl"] = target_cl
    gaps["reason"] = "mandatory_acquisitions_incomplete"
    return gaps


def _route_sphere_and_pairs(request: Any, envelope: Any, committed: Any) -> list[str]:
    route = _route_for_state(request, envelope, committed)
    ordered: list[str] = []
    allowed = _slot_allowed(request, envelope, "sphere_priorities")
    # Owner decision 10: the owner's Sphere priorities lead the planning list.
    for sphere_id in _owner_planning_preferences(request, envelope)["sphere_priority_ids"]:
        if (allowed is None or sphere_id in allowed) and sphere_id not in ordered:
            ordered.append(sphere_id)
    route_sphere = _route_sphere_id(route) if isinstance(route, Mapping) else None
    if route_sphere and route_sphere not in ordered:
        ordered.append(route_sphere)
    for row in _state_mapping(committed).get("pairs", []):
        sphere_id = row.get("sphere_id") if isinstance(row, Mapping) else None
        if isinstance(sphere_id, str) and sphere_id not in ordered:
            ordered.append(sphere_id)
    return ordered


def build_sphere_priorities_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    state = _state_mapping(committed)
    if (state.get("route_id") is None and not state.get("pairs")) or _state_slot(committed, "sphere_priorities") or is_owner_locked(request, envelope, "sphere_priorities"):
        return None
    sphere_ids = _route_sphere_and_pairs(request, envelope, committed)
    if not sphere_ids:
        return None
    candidate = _Candidate(tuple(sphere_ids), "Sphere priorities", OPTION_BUNDLE)
    return _make_menu(request, envelope, committed, step_id="sphere_priorities", step_kind="sphere_priorities", ordinal=ordinal, minimum=1, maximum=1, candidates=[candidate], page=page)


def build_insight_priorities_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, step_id: str = "insight_priorities:1", ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    # Stage 1 freezes a bounded chain of Insight windows into this slot. A
    # request frozen with that contract may serve more than the ordinary three
    # pages, so the model can reach a later window while this run walks. A
    # request without the contract keeps the ordinary ceiling.
    max_pages = paged_max_pages(request, envelope, "insight_priorities", MAX_PAGES_PER_STEP)
    return _menu_for_slot(request, envelope, committed, step_id=step_id, step_kind="insight_priorities", slot_id="insight_priorities", ordinal=ordinal, page=page, selection_index=selection_index, default_min=0, default_max=1, max_pages=max_pages)


def _milestone_rows(request: Any, envelope: Any) -> list[tuple[str, Mapping[str, Any]]]:
    contracts: list[Mapping[str, Any]] = []
    direct = _response_contract(request, envelope)
    if direct:
        contracts.append(direct)
    # The active walk carries the complete typed milestone resolution map in
    # the sealed provider projection.  Keep this fallback scoped to that
    # response contract; no milestone is inferred from display cues.
    projection_contract = _mapping(_linear_projection(request, envelope).get("response_contract"))
    if projection_contract and projection_contract not in contracts:
        contracts.append(projection_contract)
    for contract in contracts:
        value = contract.get("required_milestone_resolutions")
        if isinstance(value, Mapping):
            return [(str(key), row) for key, row in sorted(value.items(), key=lambda item: str(item[0])) if isinstance(row, Mapping)]
        if isinstance(value, (list, tuple)):
            return [(str(row.get("milestone_id")), row) for row in value if isinstance(row, Mapping) and isinstance(row.get("milestone_id"), str)]
    value = _first(request, envelope, "required_milestone_resolutions")
    if isinstance(value, Mapping):
        return [(str(key), row) for key, row in sorted(value.items(), key=lambda item: str(item[0])) if isinstance(row, Mapping)]
    if isinstance(value, (list, tuple)):
        return [(str(row.get("milestone_id")), row) for row in value if isinstance(row, Mapping) and isinstance(row.get("milestone_id"), str)]
    return []


def _milestone_cl(request: Any, envelope: Any, milestone_id: str, row: Any = None) -> int | None:
    """Return the sealed CL of one advancement milestone, or ``None``.

    Reads the typed ``cl`` on the milestone row itself, then the sealed
    ``advancement_choice_milestones`` rows on the envelope, request, or
    provider projection.  Never parses the milestone ID.
    """

    if isinstance(row, Mapping) and type(row.get("cl")) is int:
        return row["cl"]
    for source in (_mapping(envelope), _mapping(request), _linear_projection(request, envelope), _mapping(_mapping(request).get("delegated_choice_envelope"))):
        rows = source.get("advancement_choice_milestones")
        if not isinstance(rows, (list, tuple)):
            continue
        for candidate in rows:
            if isinstance(candidate, Mapping) and candidate.get("milestone_id") == milestone_id and type(candidate.get("cl")) is int:
                return candidate["cl"]
    return None


def _milestone_order_key(request: Any, envelope: Any, milestone_id: str, row: Any = None) -> tuple[int, int, str]:
    """Deterministic (CL, milestone_id) order; unknown CLs sort last by ID."""

    cl = _milestone_cl(request, envelope, milestone_id, row)
    return (0, cl, milestone_id) if cl is not None else (1, 0, milestone_id)


def _envelope_milestone(request: Any, envelope: Any, milestone_id: str) -> Mapping[str, Any] | None:
    _request_map, envelope_map = _container(request, envelope)
    return next(
        (row for row in envelope_map.get("advancement_choice_milestones") or []
         if isinstance(row, Mapping) and row.get("milestone_id") == milestone_id),
        None,
    )


def _envelope_milestone_kinds(request: Any, envelope: Any, milestone_id: str) -> set[str]:
    """The frozen milestone's own kinds; the model-facing row drops an empty Insight kind."""
    raw = _envelope_milestone(request, envelope, milestone_id)
    kinds = raw.get("allowed_kinds") if isinstance(raw, Mapping) else None
    return {kind for kind in kinds if isinstance(kind, str)} if isinstance(kinds, (list, tuple)) else set()


def _envelope_insight_option(request: Any, envelope: Any, milestone_id: str) -> Mapping[str, Any] | None:
    """Every Insight the delegated envelope allows at one milestone.

    The model-facing projection lists only prerequisite-free Insights (a
    planning rule, and a byte budget), which after Insight prerequisites were
    typed left milestones with almost no Insight.  A milestone occurrence is a
    real acquisition that the walk and the delegated validator check against
    the character's committed Paths, Spheres and Talents, so the walk offers
    every Insight the frozen typed authority allows at the milestone's CL.
    """
    _request_map, envelope_map = _container(request, envelope)
    raw = _envelope_milestone(request, envelope, milestone_id)
    # Only Insights whose typed rows (with prerequisites) are in the envelope:
    # the legality filter must be able to check every offered Insight.
    insight_ids = set(_slot_rows_by_id(request, envelope, "insight_priorities"))
    if raw is None or not insight_ids:
        return None
    from character_creation.service import _provider_milestone_resolution_contract

    contract = _provider_milestone_resolution_contract(dict(envelope_map), [dict(raw)], presented_insight_ids=sorted(insight_ids))
    option = _mapping(_mapping(_mapping(contract.get(milestone_id)).get("resolution_options")).get("cultivation_insight_acquisition"))
    return option or None


def _dual_milestone_offers_insight(request: Any, envelope: Any, milestone_id: str) -> bool:
    """Whether one frozen advancement milestone may be resolved as an Insight.

    The printed Ability Score Improvement or Cultivation Insight feature (all
    three Paths: "At CL4, CL8, CL12, CL16, and CL19 ... choose one of the
    following") lists both resolutions at every one of its levels, so the
    Insight branch is a legal choice at each of them and is never reserved
    away.  The normal ability-score increase stays available as the fallback
    ``build_asi_milestone_menu`` offers when no legal Insight exists at this
    level, and committing either one closes the other.
    """
    return "cultivation_insight_acquisition" in _envelope_milestone_kinds(request, envelope, milestone_id)


def _insight_resolution(request: Any, envelope: Any, milestone: Mapping[str, Any], milestone_id: str | None = None) -> Mapping[str, Any] | None:
    milestone_id = milestone_id or (milestone.get("milestone_id") if isinstance(milestone, Mapping) else None)
    # The frozen ``advancement_choice_milestones`` rows carry typed kinds and
    # CLs but no per-milestone ``resolution_options``; the sealed provider
    # projection rows carry both.  Derive the Insight branch from the frozen
    # typed authority whenever the milestone allows it, so both row shapes
    # resolve the same printed choice.
    derived = None
    if isinstance(milestone_id, str) and _dual_milestone_offers_insight(request, envelope, milestone_id):
        derived = _envelope_insight_option(request, envelope, milestone_id)
    options = milestone.get("resolution_options") if isinstance(milestone, Mapping) else None
    if not isinstance(options, Mapping):
        return derived
    if derived is not None:
        return derived
    insight = options.get("cultivation_insight_acquisition")
    if not isinstance(insight, Mapping):
        return None
    destination = insight.get("destination")
    if (
        not isinstance(destination, str)
        or not destination.startswith("acquisition_intent.insight_occurrences")
    ):
        return None
    if "allowed_insight_ids" not in insight and isinstance(insight.get("authority_ref"), str):
        authority = _mapping(_first(request, envelope, "milestone_resolution_authority"))
        profiles = _mapping(authority.get("cultivation_insight_profiles"))
        ref = insight["authority_ref"].rsplit(".", 1)[-1]
        profile = profiles.get(ref) if isinstance(profiles.get(ref), Mapping) else None
        if not isinstance(profile, Mapping):
            return None
        insight = {"destination": destination, **dict(profile)}
    return insight if isinstance(insight, Mapping) else None


def _parameter_abilities(parameters: Any) -> list[str]:
    if not isinstance(parameters, Mapping):
        return []
    if isinstance(parameters.get("parameters"), Mapping):
        parameters = parameters["parameters"]
    value = parameters.get("ability", parameters.get("allowed_abilities"))
    if isinstance(value, Mapping):
        value = value.get("allowed_values", value.get("values", value.get("enum")))
    if isinstance(value, str):
        return [value] if value else []
    return sorted({item for item in value or [] if isinstance(item, str) and item}) if isinstance(value, (list, tuple)) else []


_INSIGHT_ROW_MEMO: dict[tuple[Any, ...], tuple[Any, Any, Any, Any]] = {}


def _slot_fingerprint(request: Any, envelope: Any) -> tuple[Any, ...]:
    """Cheap shape of the row sources, so a memo never outlives an edit."""
    shape = []
    for source in (_mapping(envelope), _mapping(request)):
        for key in ("choices_by_slot", "allowed_choices_by_slot", "allowed_high_level", "ordinary_talent_shortlist_by_sphere"):
            slots = source.get(key)
            shape.append(tuple((name, id(rows), len(rows) if hasattr(rows, "__len__") else 0)
                               for name, rows in slots.items()) if isinstance(slots, Mapping) else id(slots))
    return tuple(shape)


def _insight_row(request: Any, envelope: Any, insight_id: str) -> Mapping[str, Any] | None:
    """Memoized per frozen request/envelope: each lookup scans every slot row,
    and automatic-build advice asks for every legal Insight on each step."""
    key = (id(request), id(envelope), insight_id)
    fingerprint = _slot_fingerprint(request, envelope)
    cached = _INSIGHT_ROW_MEMO.get(key)
    if cached is not None and cached[0] is request and cached[1] is envelope and cached[2] == fingerprint:
        return cached[3]
    row = _insight_row_uncached(request, envelope, insight_id)
    if len(_INSIGHT_ROW_MEMO) > 4096:
        _INSIGHT_ROW_MEMO.clear()
    _INSIGHT_ROW_MEMO[key] = (request, envelope, fingerprint, row)
    return row


def _insight_row_uncached(request: Any, envelope: Any, insight_id: str) -> Mapping[str, Any] | None:
    row = _ordinary_row(request, envelope, insight_id)
    if row is not None:
        return row
    # Insight choices are normally in the matching slot, not the ordinary
    # shortlist; search all typed slot rows before falling back to a
    # generic, non-authoritative cue.
    for source in (_mapping(envelope), _mapping(request)):
        for source_key in ("choices_by_slot", "allowed_choices_by_slot", "allowed_high_level"):
            slots = source.get(source_key)
            if not isinstance(slots, Mapping):
                continue
            for slot_rows in slots.values():
                for candidate_row in _rows(slot_rows):
                    if _choice_id(candidate_row) == insight_id and isinstance(candidate_row, Mapping):
                        return candidate_row
    return None


def _insight_repeat_allowed(request: Any, envelope: Any, insight: Mapping[str, Any], insight_id: str, prior_occurrences: int) -> bool:
    """Mirror Stage 2's Insight occurrence repeatability rule.

    Stage 2 reads ``repeatability`` from the record's typed authority and
    defaults to ``{"mode": "nonrepeatable", "maximum": 1}`` when absent.  A
    second causal occurrence of a nonrepeatable Insight is rejected there
    with ``CULTIVATION_INSIGHT_NOT_REPEATABLE`` even though the delegated
    validator accepts it, so the walk must never offer one.
    """

    if prior_occurrences <= 0:
        return True
    repeatability: Any = None
    params = insight.get("parameters_by_insight_id")
    parameter = params.get(insight_id) if isinstance(params, Mapping) else None
    if isinstance(parameter, Mapping) and isinstance(parameter.get("repeatability"), Mapping):
        repeatability = parameter["repeatability"]
    if repeatability is None:
        row = _insight_row(request, envelope, insight_id)
        for source in (row, _mapping(row).get("authority"), _mapping(_mapping(_mapping(_mapping(row).get("compatibility")).get("factory")).get("stage2_authority"))):
            if isinstance(source, Mapping) and isinstance(source.get("repeatability"), Mapping):
                repeatability = source["repeatability"]
                break
    if not isinstance(repeatability, Mapping):
        return False
    if repeatability.get("mode", "nonrepeatable") == "nonrepeatable":
        return False
    maximum = repeatability.get("maximum")
    return not (type(maximum) is int and prior_occurrences + 1 > maximum)


def _insight_candidates(request: Any, envelope: Any, insight: Mapping[str, Any], *, selected_insight_id: str | None = None, committed: Any = None, causal_cl: int | None = None, milestone_id: str | None = None) -> list[_Candidate]:
    allowed = insight.get("allowed_insight_ids")
    params = insight.get("parameters_by_insight_id")
    if not isinstance(allowed, (list, tuple)):
        return []
    insight_ids = sorted({item for item in allowed if isinstance(item, str) and item})
    if selected_insight_id is not None:
        if selected_insight_id not in insight_ids:
            return []
        insight_ids = [selected_insight_id]
    prior_by_id: dict[str, int] = {}
    if selected_insight_id is None:
        for occurrence in _state_mapping(committed).get("insight_occurrences") or ():
            if isinstance(occurrence, Mapping) and isinstance(occurrence.get("insight_id"), str):
                prior_by_id[occurrence["insight_id"]] = prior_by_id.get(occurrence["insight_id"], 0) + 1
    result: dict[tuple[str, ...], _Candidate] = {}
    if selected_insight_id is None:
        # A Cultivation Insight occurrence is a real acquisition: the delegated
        # validator checks its typed prerequisites and incompatibilities against
        # the final acquisitions (Paths, Spheres, Talents, other Insights, Method
        # grants), never against planning priorities.  Filter with the same
        # predicate over the committed acquisitions before offering it.
        probe = [_Candidate((insight_id,), "Insight", OPTION_PICK) for insight_id in insight_ids]
        # Stage 2 checks prerequisites against the causal state before the
        # milestone's CL, so a Talent or Sphere gained later does not count.
        # Constructed training at the milestone's own CL comes after the milestone
        # in Stage 2's event order (CL20 build 2026-09-24: Brush-Armed Guard at the
        # CL8 milestone needed Brushstroke Shield, trained at CL8).
        legal = _frozen_legality_filter(request, envelope, committed, "insight_priorities", probe, planning=False, causal_cl=causal_cl,
                                        training_cl=None if causal_cl is None else causal_cl - 1)
        insight_ids = [candidate.choice_ids[0] for candidate in legal]
    for insight_id in insight_ids:
        if selected_insight_id is None and not _insight_repeat_allowed(request, envelope, insight, insight_id, prior_by_id.get(insight_id, 0)):
            continue
        row = _insight_row(request, envelope, insight_id)
        label = _typed_label(row, fallback="Insight") if isinstance(row, Mapping) else "Insight"
        parameter = params.get(insight_id) if isinstance(params, Mapping) else None
        abilities = _parameter_abilities(parameter)
        # Offering uses only the Insight's own typed cap; the level's ASI cap
        # is advice-only headroom (``_useful_insights``), never a legality filter.
        cap = _insight_cap(request, envelope, insight_id)
        scores = _projected_ability_scores(request, envelope, committed, milestone_id)
        if type(cap) is int:
            abilities = [ability for ability in abilities if scores.get(ability, 0) < cap]
            if not abilities:
                continue
        if selected_insight_id is not None:
            for ability in abilities:
                result[(ability,)] = _Candidate((ability,), f"{label} — {ability}", OPTION_PICK)
        else:
            result[(insight_id,)] = _Candidate((insight_id,), label, OPTION_PICK)
    if selected_insight_id is not None:
        priority = _ability_priority(committed, request, envelope)
        scores = _projected_ability_scores(request, envelope, committed, milestone_id)
        return sorted((candidate for candidate in result.values()
                       if type(cap) is not int or scores.get(candidate.choice_ids[0], 0) < cap),
                      key=lambda candidate: priority.index(candidate.choice_ids[0])
                      if candidate.choice_ids[0] in priority else len(priority))
    # Legality is already settled above. Rank concept fit first, then affinity
    # to acquired Paths, Spheres and Talents; ranking never grants access.
    present = _committed_present_ids(request, envelope, committed, planning=False)
    concept = _concept_stems(request, envelope, committed)
    concept_index = _concept_text_index(request, envelope) if concept else {}

    def relevance(candidate: _Candidate) -> tuple[int, int, str]:
        row = _insight_row(request, envelope, candidate.choice_ids[0])
        targets: set[str] = set()
        if isinstance(row, Mapping):
            for relation in list(_row_relations(row, "prerequisites") or []) + list(row.get("parent_relationships") or []):
                targets.update(_relation_targets(relation))
        return (-_concept_score(concept, concept_index, candidate), -len(targets & present), candidate.choice_ids[0])

    ordered = sorted(result.values(), key=relevance)
    useful = _useful_insights(request, envelope, committed, insight, ordered, milestone_id)
    ranked = [item for item in useful if item[1][3]] + [item for item in useful if not item[1][3]]
    # A useful Insight's cue says what the build uses it for.
    purposeful = [_Candidate(candidate.choice_ids, f"{candidate.cue} — {info[2]}"[:MAX_CUE_LENGTH], candidate.kind)
                  for candidate, info in ranked]
    chosen = {candidate.choice_ids for candidate, _info in ranked}
    return [*purposeful, *(candidate for candidate in ordered if candidate.choice_ids not in chosen)]


def _insight_advice_row(request: Any, envelope: Any, insight_id: str) -> Mapping[str, Any]:
    """The Insight row with its sealed typed authority and prerequisites.

    Production envelopes keep Stage 2 authority in
    ``typed_choice_authority_by_slot.insight_priorities`` and prerequisites in
    ``prerequisites_and_availability``; compact rows omit them (SOL200: every
    real build therefore saw no Realm cap and recommended no Insight).
    """
    row = dict(_insight_row(request, envelope, insight_id) or {})
    for source in (_mapping(envelope), _mapping(request)):
        typed = _mapping(_mapping(_mapping(source.get("typed_choice_authority_by_slot")).get("insight_priorities")).get("stage2_authority_by_choice")).get(insight_id)
        if isinstance(typed, Mapping) and not isinstance(row.get("stage2_authority"), Mapping):
            row["stage2_authority"] = typed
        availability = _mapping(_mapping(source.get("prerequisites_and_availability")).get("insight_priorities")).get(insight_id)
        if isinstance(availability, Mapping) and not row.get("prerequisites"):
            row["prerequisites"] = list(availability.get("prerequisites") or [])
    return row


def _insight_cap(request: Any, envelope: Any, insight_id: str, milestone_id: str | None = None) -> int | None:
    """The Realm cap on an Insight's +1: its typed cap, else the level's ASI cap."""
    authority = _mapping(_insight_advice_row(request, envelope, insight_id).get("stage2_authority"))
    for key in ("ability_change", "insight_ability_change"):
        cap = _mapping(authority.get(key)).get("cap")
        if type(cap) is int:
            return cap
    return _milestone_asi_cap(request, envelope, milestone_id)


def _milestone_asi_cap(request: Any, envelope: Any, milestone_id: str | None) -> int | None:
    if not isinstance(milestone_id, str):
        return None
    milestone = next((row for key, row in _milestone_rows(request, envelope) if key == milestone_id), None)
    resolved = _asi_resolution(request, envelope, milestone, milestone_id) if isinstance(milestone, Mapping) else None
    return resolved[0]["cap"] if resolved else None


def _projected_ability_scores(request: Any, envelope: Any, committed: Any, milestone_id: str | None = None) -> dict[str, int]:
    """Scores this level will build on, including earlier levels' pending answers.

    The walk records every level's branch before resolving any of them, so an
    earlier level that chose the increase (or an Insight) has not yet changed
    the scores. Project those answers as the menus will resolve them, so the
    branch, Insight and +1 advice for this level agree with the later steps.
    """
    from character_creation.insight_build_policy import advancement_target, focused_increase

    scores = _effective_ability_scores(committed, request, envelope)
    if not isinstance(milestone_id, str) or not scores:
        return scores
    this_cl = _milestone_cl(request, envelope, milestone_id)
    if type(this_cl) is not int:
        return scores
    priority = _ability_priority(committed, request, envelope)
    branches = _milestone_branch_map(committed)
    state = _state_mapping(committed)
    changes = _mapping(_mapping(state.get("bounded")).get("ability_score_changes_by_milestone_id"))
    with_ability = {row.get("milestone_id") for row in state.get("insight_occurrences") or ()
                    if isinstance(row, Mapping) and _mapping(row.get("parameters")).get("ability")}
    for other_id, row in sorted(_milestone_rows(request, envelope), key=lambda item: _milestone_order_key(request, envelope, item[0], item[1])):
        cl = _milestone_cl(request, envelope, other_id, row)
        if other_id == milestone_id or type(cl) is not int or cl >= this_cl:
            continue
        cap = _milestone_asi_cap(request, envelope, other_id) or 20
        if branches.get(other_id) == MILESTONE_BRANCH_ABILITY_INCREASE and other_id not in changes:
            scores = focused_increase(scores, priority, cap)
        elif branches.get(other_id) == MILESTONE_BRANCH_INSIGHT and other_id not in with_ability:
            target = advancement_target(scores, priority, cap)
            if target is not None:
                scores[target] += 1
    return scores


def _useful_insights(request, envelope, committed, insight, candidates, milestone_id=None):
    """Legal Insights whose benefit the build uses, best evidence first.

    Returns ``[(candidate, (tier, name, why, lists_target))]``. This is
    automatic-build advice only; it never opens or closes access.
    """
    from character_creation.insight_build_policy import advancement_target, insight_use

    scores = _projected_ability_scores(request, envelope, committed, milestone_id)
    priority = _ability_priority(committed, request, envelope)
    present = _committed_present_ids(request, envelope, committed, planning=False)
    params = insight.get("parameters_by_insight_id") or {}
    names = _DisplayNames(request, envelope)
    level_cap = _milestone_asi_cap(request, envelope, milestone_id)
    result = []
    for index, candidate in enumerate(candidates):
        insight_id = candidate.choice_ids[0]
        cap = _insight_cap(request, envelope, insight_id, milestone_id)
        if type(cap) is not int:
            continue  # An automatic recommendation needs proven headroom.
        # Each Insight's own cap decides which listed abilities its +1 can raise.
        listed = tuple(ability for ability in _parameter_abilities(params.get(insight_id)) if scores.get(ability, cap) < cap)
        if not listed:
            continue
        row = _insight_advice_row(request, envelope, insight_id)
        use = insight_use(row, present, names)
        if use is None:
            continue
        # The level's target is the same one the increase would raise.
        target = advancement_target(scores, priority, level_cap if type(level_cap) is int else cap)
        result.append((index, candidate, (use[0], _typed_label(row, fallback="Insight"), use[1], target in listed, listed)))
    result.sort(key=lambda item: (-item[2][0], item[0]))
    return [(candidate, info) for _index, candidate, info in result]


class _DisplayNames:
    """Lazy id -> player-facing name lookup from the frozen typed rows."""

    def __init__(self, request: Any, envelope: Any) -> None:
        self.request, self.envelope = request, envelope

    def get(self, choice_id: Any, default: Any = None) -> Any:
        row = _insight_row(self.request, self.envelope, choice_id) if isinstance(choice_id, str) else None
        label = _typed_label(row, fallback="") if isinstance(row, Mapping) else ""
        return label or default


def _purposeful_insights(request, envelope, committed, insight, candidates, milestone_id=None):
    """Useful legal Insights listing the next ability to raise (SOL190 API)."""
    return [candidate for candidate, info in _useful_insights(request, envelope, committed, insight, candidates, milestone_id) if info[3]]


STEP_KIND_ASI_OR_INSIGHT = "asi_or_insight"
MILESTONE_BRANCH_ABILITY_INCREASE = "ability_score_increase"
MILESTONE_BRANCH_INSIGHT = "cultivation_insight"
MILESTONE_BRANCHES = (MILESTONE_BRANCH_ABILITY_INCREASE, MILESTONE_BRANCH_INSIGHT)
# One frozen milestone's typed ``allowed_kinds`` entry -> the printed branch the
# walk asks about.  A milestone that advertises both kinds resolves as one of
# them, never both (owner text, authority/typed_mechanics/rules_text.json,
# tianxia.path.*.feature.ability_score_improvement_or_cultivation_insight: "At
# CL4, CL8, CL12, CL16, and CL19, choose one of the following").  Each branch is
# answered by its own menu, listed here in the printed order.
MILESTONE_BRANCH_BY_KIND = {
    "ability_score_change": MILESTONE_BRANCH_ABILITY_INCREASE,
    "cultivation_insight_acquisition": MILESTONE_BRANCH_INSIGHT,
}


def _milestone_branch_map(committed: Any) -> dict[str, str]:
    """Every level milestone whose printed resolution the walk has recorded.

    ``bounded.advancement_milestone_branch_by_milestone_id`` is a transient walk
    fact (like ``point_buy_preset`` and ``forged_design_ids``): it records which
    printed resolution the level chose so the other branch's menu is closed and
    never re-asked.  Values are plain branch-name strings, so the record
    survives the walk snapshot's commit and reload unchanged.
    """
    rows = _mapping(_mapping(_state_mapping(committed).get("bounded")).get("advancement_milestone_branch_by_milestone_id"))
    return {
        str(milestone_id): value
        for milestone_id, value in rows.items()
        if isinstance(milestone_id, str) and isinstance(value, str) and value in MILESTONE_BRANCHES
    }


def _milestone_branches(committed: Any, milestone_id: str) -> str:
    """The branch already committed for one milestone, or ``""``."""
    return _milestone_branch_map(committed).get(milestone_id, "")


def recorded_milestone_branch(committed: Any, milestone_id: str) -> str | None:
    """The committed branch name for ``milestone_id``, or ``None``."""
    return _milestone_branches(committed, milestone_id) or None


def _milestone_resolved_as_ability_increase(committed: Any, milestone_id: str) -> bool:
    """Whether the level already resolved as the printed ability-score increase.

    True when the increase's deltas are committed (the validator's "cannot
    receive both" rule) or when the level chose the increase branch and is about
    to answer which scores it raises.
    """
    if milestone_id in _mapping(_mapping(_state_mapping(committed).get("bounded")).get("ability_score_changes_by_milestone_id")):
        return True
    return _milestone_branches(committed, milestone_id) == MILESTONE_BRANCH_ABILITY_INCREASE


def _milestone_resolved_as_insight(committed: Any, milestone_id: str) -> bool:
    """Whether the level already resolved as a Cultivation Insight."""
    if any(
        isinstance(row, Mapping) and row.get("milestone_id") == milestone_id
        for row in _state_mapping(committed).get("insight_occurrences") or ()
    ):
        return True
    return _milestone_branches(committed, milestone_id) == MILESTONE_BRANCH_INSIGHT


def branch_recommendation(request: Any, envelope: Any, committed: Any, milestone_id: str) -> tuple[str, str]:
    """Shared ``(branch, plain reason)`` for one ASI-or-Insight level."""
    from character_creation.insight_build_policy import branch_advice

    milestone = next((row for key, row in _milestone_rows(request, envelope) if key == milestone_id), None)
    insight = _insight_resolution(request, envelope, milestone, milestone_id) if isinstance(milestone, Mapping) else None
    useful_by_ability: dict[str, tuple[Any, ...]] = {}
    if insight:
        legal = _insight_candidates(request, envelope, insight, committed=committed,
                                   causal_cl=_milestone_cl(request, envelope, milestone_id, milestone),
                                   milestone_id=milestone_id)
        for _candidate, (tier, name, why, _lists_target, listed) in _useful_insights(request, envelope, committed, insight, legal, milestone_id):
            for ability in listed:  # only abilities below this Insight's own cap
                useful_by_ability.setdefault(ability, (tier, name, why))
    cap = _milestone_asi_cap(request, envelope, milestone_id) or 20
    take_insight, reason = branch_advice(_projected_ability_scores(request, envelope, committed, milestone_id),
                                         _ability_priority(committed, request, envelope), cap, useful_by_ability)
    return (MILESTONE_BRANCH_INSIGHT if take_insight else MILESTONE_BRANCH_ABILITY_INCREASE), reason


def mechanical_choice_detail(request: Any, envelope: Any, committed: Any, menu: Any, option: Any) -> str:
    """The specific reason recorded with an automatic mechanical choice."""
    if getattr(menu, "step_kind", None) == "asi_or_insight":
        milestone_id = menu.step_id.split(":", 1)[1]
        branch, reason = branch_recommendation(request, envelope, committed, milestone_id)
        if tuple(option.choice_ids) == (branch,):
            return reason
        return f"Chosen instead of the recommendation ({reason})"
    return option.cue


def build_asi_or_insight_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, milestone_id: str, ordinal: int = 1, page: int = 1) -> StepMenu | None:
    """Which printed resolution one level milestone takes.

    The printed *Ability Score Improvement or Cultivation Insight* feature
    (all three Paths) reads "At CL4, CL8, CL12, CL16, and CL19, choose one of
    the following", so a level whose frozen milestone advertises both kinds is a
    CHOICE, not a queue.  This menu is that choice: one option per printed
    resolution the character can legally take at this level, each naming what it
    does.  Answering it only records the branch; the next step asks which ability
    scores the increase raises, or which Cultivation Insight (and which of its
    printed ability scores the +1 goes to) the Insight branch takes.

    A branch is offered only when its own menu is, so the answer can never
    dead-end the walk.  Returns ``None`` when the level advertises one kind
    only, when the character legally meets no option of one branch, when the
    level is not the character's, or when it is already resolved.
    """
    if not isinstance(milestone_id, str) or not milestone_id:
        return None
    milestone = next((row for key, row in _milestone_rows(request, envelope) if key == milestone_id), None)
    # The branch question is one character-level answer, so it is offered only
    # on the milestone copy that represents the level: when a selected Path's
    # copy at this CL already carries a recorded answer (or the frozen Path
    # progression names another Path as this level's representative), the other
    # copy must never become a second, competing question for the same level.
    if not isinstance(milestone, Mapping) or milestone_shadowed(request, envelope, committed, milestone):
        return None
    if _milestone_resolved_as_ability_increase(committed, milestone_id) or _milestone_resolved_as_insight(committed, milestone_id):
        return None
    if _milestone_branches(committed, milestone_id):
        return None
    step_id = f"asi_or_insight:{milestone_id}"
    if is_owner_locked(request, envelope, step_id) or is_owner_locked(request, envelope, "asi_or_insight"):
        return None
    advertised = [kind for kind in ("ability_score_change", "cultivation_insight_acquisition") if kind in _envelope_milestone_kinds(request, envelope, milestone_id)]
    candidates: list[_Candidate] = []
    for kind in advertised:
        branch = MILESTONE_BRANCH_BY_KIND[kind]
        if branch == MILESTONE_BRANCH_ABILITY_INCREASE:
            if build_asi_milestone_menu(request, envelope, committed, milestone_id=milestone_id, ordinal=ordinal, page=page) is None:
                continue
            cue = "Normal Ability Score Improvement: raise one ability score by 2, or two different ability scores by 1 each, never past the maximum your Realm allows."
        else:
            if build_insight_occurrence_menu(request, envelope, committed, milestone_id=milestone_id, ordinal=ordinal, page=page) is None:
                continue
            cue = "Cultivation Insight: take one Cultivation Insight you meet every prerequisite for, and raise one of that Insight's listed ability scores by 1."
        candidates.append(_Candidate((branch,), cue[:MAX_CUE_LENGTH], OPTION_PICK))
    # One option is not a choice: the walk resolves such a level with the single
    # printed resolution directly instead of asking a question with one answer.
    if len(candidates) < 2:
        return None
    preferred, _reason = branch_recommendation(request, envelope, committed, milestone_id)
    candidates.sort(key=lambda candidate: candidate.choice_ids != (preferred,))
    first = candidates[0]
    # Keep the complete printed choice within the 160-character cue budget.
    # The reason is recorded with the commit and shown in the step prompt.
    cue = first.cue.replace("Normal Ability Score Improvement:", "Recommended:").replace("Cultivation Insight:", "Recommended:")
    candidates[0] = _Candidate(first.choice_ids, cue, first.kind)
    return _make_menu(request, envelope, committed, step_id=step_id, step_kind="asi_or_insight", ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page, preserve_candidate_order=True)


def build_insight_occurrence_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, milestone_id: str, ordinal: int = 1, page: int = 1, step_id: str | None = None, ability_follow_up: bool | None = None) -> StepMenu | None:
    """The Cultivation Insights a character may take at one level milestone.

    One printed branch of the level milestone "Ability Score Improvement or
    Cultivation Insight": ``build_asi_or_insight_menu`` asks which branch the
    level takes first, then this menu asks which Insight that branch takes (and
    ``insight_occurrence:<milestone_id>:ability`` which of the Insight's printed
    ability scores the +1 goes to).  Returns ``None`` when this milestone is
    not the character's, is not this branch, has already been resolved, or has
    no Insight the character legally meets.
    """
    if not isinstance(milestone_id, str) or not milestone_id:
        return None
    state = _state_mapping(committed)
    paths = set(_state_slot(committed, "path_choice"))
    milestone = next((row for key, row in _milestone_rows(request, envelope) if key == milestone_id), None)
    if milestone is None or (isinstance(milestone.get("path_id"), str) and milestone["path_id"] not in paths):
        return None
    if milestone_shadowed(request, envelope, committed, milestone):
        return None
    insight = _insight_resolution(request, envelope, milestone, milestone_id)
    if insight is None:
        return None
    # Dual-kind milestones (e.g. CL8 ASI-or-Insight) resolve exactly once.
    # Mirror the validator's "cannot receive both" rule: an ASI commit for
    # this milestone -- or a committed choice of the printed increase branch --
    # closes the Insight occurrence menu.
    if _milestone_resolved_as_ability_increase(committed, milestone_id):
        return None
    base_step_id = f"insight_occurrence:{milestone_id}"
    explicit_follow_up = step_id == f"{base_step_id}:ability"
    follow_up = explicit_follow_up if ability_follow_up is None else ability_follow_up
    existing = next(
        (row for row in state.get("insight_occurrences", []) if isinstance(row, Mapping) and row.get("milestone_id") == milestone_id),
        None,
    )
    selected_insight_id = existing.get("insight_id") if isinstance(existing, Mapping) else None
    parameters_by_insight_id = insight.get("parameters_by_insight_id")
    parameter = parameters_by_insight_id.get(selected_insight_id) if isinstance(parameters_by_insight_id, Mapping) and isinstance(selected_insight_id, str) else None
    advertised_abilities = _parameter_abilities(parameter)
    existing_parameters = existing.get("parameters") if isinstance(existing, Mapping) else None
    existing_ability = existing_parameters.get("ability") if isinstance(existing_parameters, Mapping) else None
    if existing is not None:
        if not advertised_abilities or existing_ability:
            return None
        follow_up = True
    elif follow_up:
        return None
    actual_step_id = f"{base_step_id}:ability" if follow_up else base_step_id
    # An owner may name the Insight a level takes instead of letting the walk
    # choose.  The printed +1 ability increase is a separate question the owner
    # has not answered, so the follow-up is still asked: the compiler requires
    # an exact printed ability on every level-selected Insight.  Only a lock on
    # the follow-up itself, or on the whole occurrence slot, closes it.
    if not follow_up and (
        is_owner_locked(request, envelope, base_step_id)
        or is_owner_locked(request, envelope, "insight_occurrence")
    ):
        return None
    if is_owner_locked(request, envelope, actual_step_id):
        return None
    milestone_cl = _milestone_cl(request, envelope, milestone_id, milestone)
    candidates = _insight_candidates(
        request,
        envelope,
        insight,
        selected_insight_id=selected_insight_id if follow_up else None,
        committed=committed,
        causal_cl=milestone_cl if type(milestone_cl) is int else None,
        milestone_id=milestone_id,
    )
    if not candidates:
        return None
    return _make_menu(request, envelope, committed, step_id=actual_step_id, step_kind="insight_occurrence", ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page, preserve_candidate_order=True)


# ---------------------------------------------------------------------------
# S3 bounded choices

_POINT_BUY_ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
_PROFICIENCY_FIELDS = (
    "path_skill_choices_by_path_id",
    "origin_skill_choices_by_origin_id",
    "background_language_choices_by_background_id",
)
_PROFICIENCY_SLOTS = {
    "path_skill_choices_by_path_id": "path_choice",
    "origin_skill_choices_by_origin_id": "origin_insight_choice",
    "background_language_choices_by_background_id": "background_choice",
}
_PROFICIENCY_KINDS = {
    "path_skill_choices_by_path_id": "path_skill",
    "origin_skill_choices_by_origin_id": "origin_skill",
    "background_language_choices_by_background_id": "background_language",
}


def _bounded_choice_contract(request: Any, envelope: Any) -> Mapping[str, Any]:
    value = _first(request, envelope, "bounded_choice_contract")
    return value if isinstance(value, Mapping) else {}


def _starting_proficiency_contract(request: Any, envelope: Any) -> Mapping[str, Any]:
    """Resolve the full typed starting-proficiency contract."""

    bounded = _bounded_choice_contract(request, envelope)
    starting = bounded.get("starting_proficiency_choice_contract")
    if isinstance(starting, Mapping):
        return starting

    # Linear walks also carry a provider projection.  Some production-shaped
    # envelopes place the full contract under that projection rather than on
    # the compact request; use it only when the typed contract is present.
    projection = _linear_projection(request, envelope)
    projection_contract = projection.get("bounded_choice_contract")
    if isinstance(projection_contract, Mapping):
        starting = projection_contract.get("starting_proficiency_choice_contract")
        if isinstance(starting, Mapping):
            return starting
    for candidate in (
        projection.get("starting_proficiency_choice_contract"),
        _mapping(projection.get("response_contract")).get("starting_proficiency_choice_contract"),
    ):
        if isinstance(candidate, Mapping):
            return candidate
    return {}


def _origin_unresolved_ids(request: Any, envelope: Any) -> set[str]:
    """Return only origin IDs explicitly marked mechanically unresolved."""

    contract = _starting_proficiency_contract(request, envelope)
    unresolved = contract.get("unresolved")
    if not isinstance(unresolved, (list, tuple)):
        return set()
    return {
        row.get("choice_id")
        for row in unresolved
        if isinstance(row, Mapping)
        and row.get("field") == "origin_skill_choices_by_origin_id"
        and row.get("proficiency_mechanics_present") is True
        and isinstance(row.get("choice_id"), str)
        and row.get("choice_id")
    }


def _contract_field(request: Any, envelope: Any, field_name: str) -> Any:
    contract = _bounded_choice_contract(request, envelope)
    fields = contract.get("fields")
    if isinstance(fields, Mapping) and field_name in fields:
        return fields[field_name]
    return contract.get(field_name)


def _ability_score_summary(request: Any, envelope: Any) -> Mapping[str, Any]:
    direct = _first(request, envelope, "bounded_choice_summary")
    projection = _linear_projection(request, envelope)
    sources = [
        direct,
        projection.get("bounded_choice_summary"),
        projection.get("point_buy_summary"),
    ]
    fallback: Mapping[str, Any] | None = None
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        nested = source.get("ability_scores")
        candidate = nested if isinstance(nested, Mapping) else source
        if fallback is None:
            fallback = candidate
        # Prefer the complete typed projection when a compact direct summary
        # exists but only carries display/selection context.
        if isinstance(candidate.get("legal_score_presets"), (list, tuple)):
            return candidate
    return fallback or {}


def _point_buy_spec(request: Any, envelope: Any) -> tuple[tuple[str, ...], tuple[int, ...], int, Mapping[str, Any]] | None:
    summary = _ability_score_summary(request, envelope)
    field = _contract_field(request, envelope, "ability_scores")
    field = field if isinstance(field, Mapping) else {}
    raw_abilities = summary.get("abilities", field.get("abilities"))
    abilities = tuple(value for value in raw_abilities if isinstance(value, str) and value) if isinstance(raw_abilities, (list, tuple)) else ()
    if len(abilities) != 6 or len(set(abilities)) != 6:
        return None
    raw_values = summary.get("allowed_values", field.get("allowed_values"))
    allowed_values = tuple(value for value in raw_values if type(value) is int) if isinstance(raw_values, (list, tuple)) else ()
    if not allowed_values:
        return None
    budget = summary.get("budget", field.get("budget"))
    exact_budget = summary.get("exact_budget", budget)
    if type(budget) is not int or budget <= 0 or type(exact_budget) is not int or exact_budget != budget:
        return None
    presets = summary.get("legal_score_presets")
    if not isinstance(presets, (list, tuple)):
        return None
    # Keep a private, normalized spec.  The original rows remain the only
    # authority; no preset is inferred from a generic point-buy policy.
    costs = summary.get("cost_by_score", summary.get("cost_by_value"))
    if not isinstance(costs, Mapping):
        return None
    normalized_costs: dict[int, int] = {}
    for value in allowed_values:
        cost = costs.get(str(value), costs.get(value))
        if type(cost) is not int or cost < 0:
            return None
        normalized_costs[value] = cost
    valid_rows: list[dict[str, Any]] = []
    for row in presets:
        if not isinstance(row, Mapping):
            continue
        raw_scores = row.get("scores")
        if isinstance(raw_scores, Mapping):
            scores = tuple(raw_scores.get(ability) for ability in abilities)
        elif isinstance(raw_scores, (list, tuple)):
            scores = tuple(raw_scores)
        else:
            continue
        if len(scores) != 6 or any(type(value) is not int or value not in allowed_values for value in scores):
            continue
        cost = row.get("cost")
        if type(cost) is not int or cost != sum(normalized_costs[value] for value in scores) or cost != exact_budget:
            continue
        permutable = row.get("permutable_across_abilities")
        if type(permutable) is not bool:
            continue
        valid_rows.append({
            "scores": list(scores),
            "abilities": list(abilities),
            "cost": cost,
            "budget": exact_budget,
            "permutable_across_abilities": permutable,
        })
    return abilities, allowed_values, exact_budget, {"presets": valid_rows, "costs": normalized_costs}


def _score_bundle(prefix: str, abilities: Sequence[str], scores: Sequence[int], *, mode: str | None = None) -> tuple[str, ...]:
    if mode is None:
        return tuple(f"{prefix}:{ability}:{score}" for ability, score in zip(abilities, scores))
    return tuple(f"{prefix}:{mode}:{ability}:{score}" for ability, score in zip(abilities, scores))


def _decode_score_bundle(choice_ids: Sequence[str], prefix: str, *, mode: str | None = None) -> dict[str, int] | None:
    result: dict[str, int] = {}
    for token in choice_ids:
        if not isinstance(token, str):
            return None
        parts = token.split(":")
        if mode is None:
            if len(parts) != 3 or parts[0] != prefix:
                return None
            _, ability, raw_score = parts
        else:
            if len(parts) != 4 or parts[0] != prefix or parts[1] != mode:
                return None
            _, _, ability, raw_score = parts
        if not ability or ability in result:
            return None
        try:
            score = int(raw_score)
        except (TypeError, ValueError):
            return None
        result[ability] = score
    return result if result else None


def _preset_choice_ids(preset: Mapping[str, Any]) -> tuple[str, ...] | None:
    abilities = preset.get("abilities")
    scores = preset.get("scores")
    permutable = preset.get("permutable_across_abilities")
    if not isinstance(abilities, (list, tuple)) or not isinstance(scores, (list, tuple)) or type(permutable) is not bool:
        return None
    mode = "permutable" if permutable else "fixed"
    return _score_bundle("point_buy_preset", abilities, scores, mode=mode)


def _point_buy_preset_candidates(request: Any, envelope: Any) -> list[_Candidate]:
    spec = _point_buy_spec(request, envelope)
    if spec is None:
        return []
    abilities, _allowed_values, _budget, normalized = spec
    result: list[_Candidate] = []
    for index, preset in enumerate(normalized["presets"], start=1):
        choice_ids = _preset_choice_ids(preset)
        if choice_ids is None:
            continue
        values = preset.get("scores") if isinstance(preset, Mapping) else None
        spread = "/".join(str(value) for value in sorted(values, reverse=True)) if isinstance(values, (list, tuple)) else ""
        result.append(_Candidate(choice_ids, f"Point-buy preset {index}: scores {spread}" if spread else f"Point-buy preset {index}", OPTION_BUNDLE))
    return result


def build_point_buy_preset_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, ordinal: int = 1, page: int = 1) -> StepMenu | None:
    state = _state_mapping(committed)
    bounded = _mapping(state.get("bounded"))
    if isinstance(bounded.get("ability_scores"), Mapping) or isinstance(bounded.get("point_buy_preset"), Mapping):
        return None
    if is_owner_locked(request, envelope, "point_buy_preset"):
        return None
    candidates = _point_buy_preset_candidates(request, envelope)
    if not candidates:
        return None
    # Rule: a fixed spread must give the key ability its highest score. A
    # permutable spread is always kept; its assignment step offers the key-first arrangements.
    key = _ability_priority(committed, request, envelope)[0]

    def key_first(candidate: _Candidate) -> bool:
        if ":permutable:" in candidate.choice_ids[0]:
            return True
        mapped = {token.split(":")[-2]: int(token.split(":")[-1]) for token in candidate.choice_ids}
        return mapped.get(key, 0) == max(mapped.values())

    if _generated_build(request, envelope):
        candidates = [candidate for candidate in candidates if key_first(candidate)]
    # Lexicographic descending scores maximize the key ability and then its
    # supports within the frozen legal presets, without inventing a new array.
    priority = _ability_priority(committed, request, envelope)
    def preset_rank(candidate):
        mapped = {token.split(":")[-2]: int(token.split(":")[-1]) for token in candidate.choice_ids}
        attainable = (sorted(mapped.values(), reverse=True) if candidate.choice_ids[0].split(":")[1] == "permutable"
                      else [mapped.get(ability, 0) for ability in priority])
        return tuple(-value for value in attainable)
    candidates.sort(key=preset_rank)
    return _make_menu(request, envelope, committed, step_id="point_buy_preset", step_kind="point_buy_preset", ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page, preserve_candidate_order=True)


# Ability priorities by Path (key ability first).  Used to rank ability-score
# options so the best-fitting assignment is offered first and the first-option
# fallback is sound; every legal option is still offered on later pages.
_PATH_ABILITY_PRIORITY = {
    "tianxia.path.body_refining": ("CON", "STR", "DEX", "WIS", "CHA", "INT"),
    "tianxia.path.qi_cultivation": ("INT", "CON", "DEX", "WIS", "CHA", "STR"),
    # DEX second (owner 2026-09-24): the Path has no armour in its kit, so DEX is
    # its AC; with CHA and CON first every Spirit Awakening build had DEX 10, AC 10.
    "tianxia.path.spirit_awakening": ("WIS", "DEX", "CON", "CHA", "INT", "STR"),
}
_DEFAULT_ABILITY_PRIORITY = ("CON", "DEX", "STR", "WIS", "INT", "CHA")


def _ability_priority(committed: Any, request: Any = None, envelope: Any = None) -> tuple[str, ...]:
    paths = [value for value in _state_slot(committed, "path_choice") if value in _PATH_ABILITY_PRIORITY]
    if not paths:
        return _DEFAULT_ABILITY_PRIORITY
    order: list[str] = []
    # Frozen Path authority carries the actual selected attack/save ability
    # (including Qi's legal INT/CHA choice). Do not infer it from a Dao name.
    for path_id in paths:
        rows, _ = _slot_rows(request, envelope, "path_choice")
        row = next((row for row in rows if isinstance(row, Mapping) and _choice_id(row) == path_id), {})
        key = _mapping(_mapping(row).get("stage2_authority")).get("key_ability")
        if key not in _POINT_BUY_ABILITIES:
            key = _PATH_ABILITY_PRIORITY[path_id][0]
        if key not in order:
            order.append(key)
    from character_creation.insight_build_policy import sphere_attack_abilities
    used = sphere_attack_abilities(_known_sphere_ids(request, envelope, committed))
    for ability in _DEFAULT_ABILITY_PRIORITY:
        if ability in used and ability not in order:
            order.append(ability)
    # The default key is an alternative, not a second attack/save ability.
    # Owned Sphere formulas above may independently establish its use.
    for rank in range(1, 6):
        for path_id in paths:
            ability = _PATH_ABILITY_PRIORITY[path_id][rank]
            if ability not in order:
                order.append(ability)
    for ability in _DEFAULT_ABILITY_PRIORITY:
        if ability not in order:
            order.append(ability)
    return tuple(order)


def _score_cue(scores: Mapping[str, int], priority: Sequence[str]) -> str:
    ordered = [ability for ability in priority if ability in scores] + [ability for ability in scores if ability not in priority]
    return ", ".join(f"{ability} {scores[ability]}" for ability in ordered)


def _assignment_candidates(preset: Mapping[str, Any], committed: Any = None, request: Any = None, envelope: Any = None) -> list[_Candidate]:
    abilities = tuple(value for value in preset.get("abilities", ()) if isinstance(value, str) and value)
    raw_scores = preset.get("scores")
    if len(abilities) != 6 or not isinstance(raw_scores, (list, tuple)) or len(raw_scores) != 6 or any(type(value) is not int for value in raw_scores):
        return []
    # Every permutation of the frozen preset is legal. Keep the mechanical
    # fallback first, but also show a different leading ability for each
    # rotation of its priority order before the remaining ranked assignments.
    # This is concept-neutral: the model chooses from the character's brief.
    scores = tuple(sorted(raw_scores, reverse=True))
    priority = _ability_priority(committed, request, envelope)
    distinct = sorted(
        set(itertools.permutations(scores, len(abilities))),
        key=lambda assignment: tuple(-dict(zip(abilities, assignment)).get(ability, 0) for ability in priority),
    )
    # Rule: the key ability (first in priority) holds the highest score. Only
    # those permutations are offered; concept chooses among them, never below.
    key = priority[0]
    if _generated_build(request, envelope):
        distinct = [assignment for assignment in distinct
                    if dict(zip(abilities, assignment)).get(key, 0) == max(assignment)]
    anchors = []
    for offset in range(len(priority)):
        rotated = priority[offset:] + priority[:offset]
        assignment = min(distinct, key=lambda values: tuple(
            -dict(zip(abilities, values)).get(ability, 0) for ability in rotated))
        if assignment not in anchors:
            anchors.append(assignment)
    distinct = anchors + [assignment for assignment in distinct if assignment not in anchors]
    result: list[_Candidate] = []
    for assignment in distinct:
        mapped = dict(zip(abilities, assignment))
        result.append(_Candidate(_score_bundle("point_buy_assignment", abilities, assignment), _score_cue(mapped, priority)[:MAX_CUE_LENGTH], OPTION_BUNDLE))
    return result


def point_buy_assignment_page_limit(request: Any, envelope: Any, committed: Any) -> int:
    """Shared menu/service ceiling for the key-highest permutations of a sealed preset."""
    preset = _mapping(_mapping(_state_mapping(committed).get("bounded")).get("point_buy_preset"))
    scores = preset.get("scores")
    abilities = preset.get("abilities")
    if not isinstance(scores, (list, tuple)) or len(scores) != 6 or any(type(value) is not int for value in scores):
        return 1
    if not isinstance(abilities, (list, tuple)) or len(abilities) != 6:
        return 1
    permutations = set(itertools.permutations(scores))
    if _generated_build(request, envelope):
        key = _ability_priority(committed, request, envelope)[0]
        permutations = {assignment for assignment in permutations
                       if dict(zip(abilities, assignment)).get(key, 0) == max(assignment)}
    count = len(permutations)
    return max(1, (count - 1) // (MAX_OPTIONS_PER_PAGE - 1) + 1)


def build_point_buy_assignment_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, ordinal: int = 1, page: int = 1) -> StepMenu | None:
    state = _state_mapping(committed)
    bounded = _mapping(state.get("bounded"))
    preset = bounded.get("point_buy_preset")
    if not isinstance(preset, Mapping) or preset.get("permutable_across_abilities") is not True or isinstance(bounded.get("ability_scores"), Mapping):
        return None
    if is_owner_locked(request, envelope, "point_buy_assignment"):
        return None
    candidates = _assignment_candidates(preset, committed, request, envelope)
    if not candidates:
        return None
    # A continuation consumes one of the twelve visible options. Give this
    # bounded six-score menu enough pages to reach every legal permutation.
    max_pages = point_buy_assignment_page_limit(request, envelope, committed)
    return _make_menu(request, envelope, committed, step_id="point_buy_assignment", step_kind="point_buy_assignment", ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page, preserve_candidate_order=True, max_pages=max_pages)


def _asi_rule(request: Any, envelope: Any, milestone_id: str, raw_option: Mapping[str, Any]) -> Mapping[str, Any] | None:
    contract = _bounded_choice_contract(request, envelope)
    field = _contract_field(request, envelope, "ability_score_changes_by_milestone_id")
    maps: list[Any] = [field, contract.get("ability_score_changes_by_milestone_id"), _first(request, envelope, "ability_score_changes_by_milestone_id")]
    rule: Any = None
    for source in maps:
        if not isinstance(source, Mapping):
            continue
        candidate = source.get(milestone_id)
        if candidate is None and isinstance(source.get("choices"), Mapping):
            candidate = source["choices"].get(milestone_id)
        if isinstance(candidate, Mapping):
            rule = candidate
            break
    if not isinstance(rule, Mapping):
        constraints = raw_option.get("constraints")
        if isinstance(constraints, Mapping):
            rule = constraints
        else:
            reference = raw_option.get("constraints_ref")
            authority = _mapping(_first(request, envelope, "milestone_resolution_authority"))
            authority_rules = _mapping(authority.get("ability_score_change_rules"))
            if isinstance(reference, str):
                rule = authority_rules.get(reference.rsplit(".", 1)[-1])
    if not isinstance(rule, Mapping):
        return None
    if isinstance(rule.get("constraints"), Mapping):
        rule = rule["constraints"]
    abilities = rule.get("allowed_abilities")
    if abilities is None or (isinstance(abilities, (list, tuple)) and not abilities):
        # The frozen source-backed rule leaves allowed_abilities absent when
        # any ability may take the improvement.  Mirror the unchanged
        # validator default instead of treating the rule as unprojectable.
        abilities = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
    deltas = rule.get("allowed_deltas")
    budget = rule.get("budget")
    cap = rule.get("cap")
    if not isinstance(abilities, (list, tuple)) or not isinstance(deltas, (list, tuple)) or type(budget) is not int or budget <= 0 or type(cap) is not int or cap <= 0:
        return None
    abilities = sorted({value for value in abilities if isinstance(value, str) and value})
    deltas = sorted({value for value in deltas if type(value) is int and value > 0})
    if not abilities or not deltas:
        return None
    cl = next((row.get("cl") for key, row in _milestone_rows(request, envelope) if key == milestone_id), None)
    allowed_cls = rule.get("allowed_cls")
    if isinstance(allowed_cls, (list, tuple)) and type(cl) is int and cl not in {value for value in allowed_cls if type(value) is int}:
        return None
    cardinality = raw_option.get("resolution_cardinality")
    if cardinality is None:
        cardinality = rule.get("resolution_cardinality")
    if cardinality == "exactly_one":
        cardinality = 1
    if type(cardinality) is not int or cardinality <= 0:
        return None
    return {
        "allowed_abilities": abilities,
        "allowed_deltas": deltas,
        "budget": budget,
        "cap": cap,
        "cardinality": cardinality,
    }


def _asi_resolution(request: Any, envelope: Any, milestone: Mapping[str, Any], milestone_id: str) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    options = milestone.get("resolution_options")
    if not isinstance(options, Mapping):
        return None
    raw = options.get("ability_score_change")
    if not isinstance(raw, Mapping):
        return None
    destination = raw.get("destination")
    expected = f"bounded_choices.ability_score_changes_by_milestone_id.{milestone_id}"
    if not isinstance(destination, str) or destination != expected:
        return None
    option = dict(raw)
    if "resolution_cardinality" not in option and "resolution_cardinality" in milestone:
        option["resolution_cardinality"] = milestone["resolution_cardinality"]
    rule = _asi_rule(request, envelope, milestone_id, option)
    return (rule, option) if rule is not None else None


def _background_ability_bonus(request: Any, envelope: Any, committed: Any) -> tuple[str, int] | None:
    """The committed Background ability increase, as the service applies it."""
    bounded = _mapping(_state_mapping(committed).get("bounded"))
    ability = bounded.get("background_ability")
    if not isinstance(ability, str) or ability not in _POINT_BUY_ABILITIES:
        return None
    chosen = bounded.get("background_ability_amount")
    if type(chosen) is int and chosen > 0:
        return ability, chosen
    background_ids = _state_slot(committed, "background_choice")
    background_id = background_ids[-1] if background_ids else None
    for source in (_mapping(envelope), _mapping(request)):
        typed = source.get("typed_choice_authority_by_slot")
        authority = typed.get("background_choice") if isinstance(typed, Mapping) else None
        adjustments = authority.get("ability_adjustment_by_choice") if isinstance(authority, Mapping) else None
        if isinstance(adjustments, Mapping) and background_id in adjustments:
            _abilities, amounts, fixed = _background_ability_typed_values(adjustments[background_id])
            amount = fixed if fixed is not None else (min(amounts) if amounts else None)
            if type(amount) is int and amount > 0:
                return ability, amount
    return None


def _effective_ability_scores(committed: Any, request: Any = None, envelope: Any = None) -> dict[str, int]:
    """Point-buy scores plus every committed increase the validator applies.

    With the request, the Background ability bonus is included; Insight
    ability increases always are.  Without them an ASI could be offered past
    the cap (WIS 19 + 2 at CL8, build 24).
    """
    bounded = _mapping(_state_mapping(committed).get("bounded"))
    scores = bounded.get("ability_scores")
    result = {key: value for key, value in scores.items()} if isinstance(scores, Mapping) and all(type(value) is int for value in scores.values()) else {}
    if result and request is not None:
        bonus = _background_ability_bonus(request, envelope, committed)
        if bonus is not None and bonus[0] in result:
            result[bonus[0]] += bonus[1]
    for occurrence in _state_mapping(committed).get("insight_occurrences") or ():
        parameters = occurrence.get("parameters") if isinstance(occurrence, Mapping) else None
        ability = parameters.get("ability") if isinstance(parameters, Mapping) else None
        if isinstance(ability, str) and ability in result:
            result[ability] += 1
    changes = bounded.get("ability_score_changes_by_milestone_id")
    if isinstance(changes, Mapping):
        for value in changes.values():
            deltas = value.get("deltas") if isinstance(value, Mapping) else value
            if not isinstance(deltas, Mapping):
                continue
            for ability, delta in deltas.items():
                if ability in result and type(delta) is int:
                    result[ability] += delta
    return result


def _asi_candidates(rule: Mapping[str, Any], committed: Any, request: Any = None, envelope: Any = None) -> list[_Candidate]:
    scores = _effective_ability_scores(committed, request, envelope)
    abilities = [ability for ability in rule["allowed_abilities"] if ability in scores]
    deltas = list(rule["allowed_deltas"])
    priority = _ability_priority(committed, request, envelope)
    candidates: list[_Candidate] = []
    # ``resolution_cardinality`` counts the milestone resolution (one
    # resolution object), while the bounded ASI object may contain one to
    # six distinct ability keys.  The source contract's budget is exact, as
    # reflected by the response schema's oneOf alternatives.
    for count in range(1, len(abilities) + 1):
        for selected_abilities in itertools.combinations(sorted(abilities), count):
            for selected_deltas in itertools.product(deltas, repeat=count):
                if sum(selected_deltas) != rule["budget"]:
                    continue
                if any(scores[ability] + delta > rule["cap"] for ability, delta in zip(selected_abilities, selected_deltas)):
                    continue
                choices = tuple(
                    f"asi:{ability}:{delta}"
                    for ability, delta in zip(selected_abilities, selected_deltas)
                )
                cue = "Improve " + ", ".join(f"{ability} {scores[ability]}→{scores[ability] + delta}" for ability, delta in zip(selected_abilities, selected_deltas))
                candidates.append(_Candidate(choices, cue[:MAX_CUE_LENGTH], OPTION_BUNDLE))

    def rank(candidate: _Candidate) -> tuple[int, ...]:
        after = dict(scores)
        for token in candidate.choice_ids:
            _prefix, ability, delta = token.split(":")
            after[ability] = after[ability] + int(delta)
        # Concentrate on the Path's priority ability to its printed cap before
        # supporting another ability. Even secondary totals cannot displace it.
        return tuple(-after.get(ability, 0) for ability in priority)

    return sorted(candidates, key=rank)[:MAX_OPTIONS_PER_PAGE]


def _milestone_cl_and_path(milestone: Any) -> tuple[str, str] | None:
    if not isinstance(milestone, Mapping):
        return None
    cl = milestone.get("cl")
    path_id = milestone.get("path_id")
    if not isinstance(path_id, str) or not path_id or cl is None or isinstance(cl, bool):
        return None
    return str(cl), path_id


def resolved_milestone_path_by_cl(request: Any, envelope: Any, committed: Any) -> dict[str, str]:
    """Which selected Path's advancement milestone is already resolved at each CL.

    A committed ability-score change or Insight occurrence for a milestone
    names that milestone's Path as the level's representative.  A recorded
    level-milestone branch names it as well: from the moment the walk records
    which printed resolution a level takes, that answer is the owner's decision
    for the level.  Every selected Path carries the same printed milestone at
    the same CL, so the other Path's copy must not be offered as a second,
    competing question for the level -- resolving one there
    (``milestone_shadowed``) would silently discard the answer already given
    and replace it with the other branch.
    """
    state = _state_mapping(committed)
    changes = _mapping(_mapping(state.get("bounded")).get("ability_score_changes_by_milestone_id"))
    occurrences = {
        row.get("milestone_id")
        for row in state.get("insight_occurrences", [])
        if isinstance(row, Mapping) and isinstance(row.get("milestone_id"), str)
    }
    resolved_ids = set(changes) | occurrences | set(_milestone_branch_map(state))
    result: dict[str, str] = {}
    for milestone_id, row in _milestone_rows(request, envelope):
        if milestone_id not in resolved_ids:
            continue
        located = _milestone_cl_and_path(row)
        if located is not None:
            result.setdefault(located[0], located[1])
    return result


def milestone_shadowed(request: Any, envelope: Any, committed: Any, milestone: Any) -> bool:
    """Advancement milestones are character-level, not per-Path.

    Owner ruling 2026-09-13: every chosen Path advances at every level, but
    the ability-score-improvement-or-Insight milestone at a CL is one
    character choice.  When several selected Paths carry that milestone at
    the same CL, only the Path named as that level's representative (the
    committed ``path_progression_by_cl`` entry, or the Path whose milestone
    was already resolved there -- its committed deltas, its Insight
    occurrence, or the printed branch recorded for it) keeps it; the others
    are shadowed and never offered.  The compiler applies exactly that single
    milestone.
    """
    located = _milestone_cl_and_path(milestone)
    if located is None:
        return False
    cl, path_id = located
    progression = _mapping(_mapping(_state_mapping(committed).get("bounded")).get("path_progression_by_cl"))
    representative = progression.get(cl)
    if isinstance(representative, str) and representative and representative != path_id:
        return True
    resolved = resolved_milestone_path_by_cl(request, envelope, committed).get(cl)
    return isinstance(resolved, str) and resolved != path_id


def build_asi_milestone_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, milestone_id: str, ordinal: int = 1, page: int = 1) -> StepMenu | None:
    """Which ability scores one printed normal increase raises.

    One printed branch of the level milestone "Ability Score Improvement or
    Cultivation Insight"; ``build_asi_or_insight_menu`` asks which branch the
    level takes before this menu asks its detail question.
    """
    if not isinstance(milestone_id, str) or not milestone_id:
        return None
    state = _state_mapping(committed)
    paths = set(_state_slot(committed, "path_choice"))
    milestone = next((row for key, row in _milestone_rows(request, envelope) if key == milestone_id), None)
    if not isinstance(milestone, Mapping) or (isinstance(milestone.get("path_id"), str) and milestone["path_id"] not in paths):
        return None
    if milestone_shadowed(request, envelope, committed, milestone):
        return None
    changes = _mapping(_mapping(state.get("bounded")).get("ability_score_changes_by_milestone_id"))
    if milestone_id in changes:
        return None
    # Dual-kind milestones (e.g. CL8 ASI-or-Insight) resolve exactly once.
    # Mirror the validator's "cannot receive both" rule: a committed Insight --
    # or a committed choice of the Insight branch -- closes this menu.
    if _milestone_resolved_as_insight(committed, milestone_id):
        return None
    resolved = _asi_resolution(request, envelope, milestone, milestone_id)
    if resolved is None or is_owner_locked(request, envelope, f"asi_milestone:{milestone_id}") or is_owner_locked(request, envelope, "asi_milestone"):
        return None
    candidates = _asi_candidates(resolved[0], committed, request, envelope)
    # Build policy: while the key ability is below 19, an increase must raise
    # it (the owner found CL18 builds with an unraised key ability).
    key = _ability_priority(committed, request, envelope)[0]
    scores = _effective_ability_scores(committed, request, envelope)
    if type(scores.get(key)) is int and scores[key] < 19:
        focused = [candidate for candidate in candidates if any(str(choice_id).startswith(f"asi:{key}:") for choice_id in candidate.choice_ids)]
        candidates = focused or candidates
    if not candidates:
        return None
    return _make_menu(request, envelope, committed, step_id=f"asi_milestone:{milestone_id}", step_kind="asi_milestone", ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page, preserve_candidate_order=True)


def _progression_id_list(raw: Any) -> list[str]:
    """Normalize one CL entry to its sorted distinct Path IDs.

    Mirrors the per-CL extraction in ``_progression_candidates`` so the
    merged response-side map keeps the exact historical candidate shape.
    """

    if isinstance(raw, Mapping):
        raw = raw.get("allowed_values", raw.get("path_ids", raw.get("ids", raw)))
    if isinstance(raw, (list, tuple, set, frozenset)):
        return sorted({value for value in raw if isinstance(value, str)})
    return []


def _progression_map(request: Any, envelope: Any) -> Mapping[str, Any]:
    # The production delegated envelope carries the sealed progression
    # authority as rows (CL plus exact Path IDs), rather than as the response
    # contract's CL-keyed map.  Project those typed rows without consulting
    # labels or the live catalog.
    typed_rows: list[Any] = []
    for source in (_mapping(envelope), _mapping(request)):
        value = source.get("path_progression_choices")
        if isinstance(value, (list, tuple)):
            typed_rows.extend(value)
    typed_map: dict[str, list[str]] = {}
    for row in typed_rows:
        if not isinstance(row, Mapping):
            continue
        raw_cl = row.get("cl")
        if type(raw_cl) is not int and not (isinstance(raw_cl, str) and raw_cl.isdigit()):
            continue
        path_ids = row.get("path_ids")
        if not isinstance(path_ids, (list, tuple, set, frozenset)):
            continue
        values = sorted({value for value in path_ids if isinstance(value, str) and value})
        if values:
            typed_map.setdefault(str(raw_cl), []).extend(values)
    typed_map = {
        cl: sorted(set(values))
        for cl, values in typed_map.items()
    }
    # The sealed typed rows and the response contract's presented map are
    # both frozen response-side authority for the same CL ambiguity.  Union
    # them per CL instead of letting one shadow the other: a CL advertised
    # as ambiguous by either source still requires an explicit walk pick,
    # and the bounded contract below only narrows the legal set.
    fallback_map: dict[str, list[str]] = {}
    response = _response_contract(request, envelope)
    for source in (response, _contract_field(request, envelope, "path_progression_by_cl"), _bounded_choice_contract(request, envelope), _mapping(_first(request, envelope, "path_progression_by_cl"))):
        if not isinstance(source, Mapping):
            continue
        if source and all(str(key).isdigit() for key in source):
            fallback_map = {str(key): _progression_id_list(value) for key, value in source.items()}
            break
        value = source.get("presented_legal_path_progression_ids_by_cl", source.get("path_progression_by_cl"))
        if isinstance(value, Mapping):
            fallback_map = {str(key): _progression_id_list(item) for key, item in value.items()}
            break
    if not typed_map:
        return fallback_map
    if not fallback_map:
        return typed_map
    return {
        cl: sorted(set(typed_map.get(cl, ())) | set(fallback_map.get(cl, ())))
        for cl in set(typed_map) | set(fallback_map)
    }


def _bounded_progression_map(request: Any, envelope: Any) -> Mapping[str, Any]:
    """Return a direct bounded contract map when one is frozen."""

    contract = _bounded_choice_contract(request, envelope)
    for source in (_contract_field(request, envelope, "path_progression_by_cl"), contract.get("path_progression_by_cl")):
        if not isinstance(source, Mapping):
            continue
        if source and all(str(key).isdigit() for key in source):
            return source
        value = source.get("allowed_values", source.get("path_ids"))
        if isinstance(value, Mapping):
            return value
    return {}


def _progression_candidates(request: Any, envelope: Any, cl: str) -> list[_Candidate]:
    response_map = _progression_map(request, envelope)
    contract_map = _bounded_progression_map(request, envelope)
    response_present = cl in response_map
    raw = response_map.get(cl)
    if raw is None and not response_present:
        try:
            raw = response_map.get(int(cl))
            response_present = int(cl) in response_map
        except (TypeError, ValueError):
            raw = None
    if isinstance(raw, Mapping):
        raw = raw.get("allowed_values", raw.get("path_ids", raw.get("ids", raw)))
    values = sorted({value for value in (raw or []) if isinstance(value, str)}) if isinstance(raw, (list, tuple, set, frozenset)) else []
    contract_raw = contract_map.get(cl)
    if contract_raw is None:
        try:
            contract_raw = contract_map.get(int(cl))
        except (TypeError, ValueError):
            contract_raw = None
    if isinstance(contract_raw, Mapping):
        contract_raw = contract_raw.get("allowed_values", contract_raw.get("path_ids", contract_raw.get("ids", contract_raw)))
    if isinstance(contract_raw, (list, tuple, set, frozenset)):
        contract_values = {value for value in contract_raw if isinstance(value, str)}
        values = sorted(set(values) & contract_values) if response_present else sorted(contract_values)
    return [_Candidate((value,), "Path progression", OPTION_PICK) for value in values]


def _response_progression_values(request: Any, envelope: Any, cl: str) -> list[str]:
    """Return the merged response-side Path IDs advertised for one CL.

    This is the frozen ambiguity signal, before the bounded contract
    narrows it: more than one advertised ID means the delegated validator
    requires one exact Path route at this CL.
    """

    response_map = _progression_map(request, envelope)
    raw = response_map.get(cl)
    if raw is None and str(cl).isdigit():
        raw = response_map.get(int(cl))
    return _progression_id_list(raw)


def _frozen_target_cl(request: Any, envelope: Any) -> int | None:
    """Read the target CL only from the sealed owner-target authority."""

    value = _first(request, envelope, "frozen_owner_target_cl")
    if isinstance(value, Mapping):
        value = value.get("value", value.get("target_cl"))
    return value if type(value) is int and value > 0 else None


DEFAULT_SUBPATH_MINIMUM_ATTAINMENT = 3


def _required_path_attainment(request: Any, envelope: Any, committed: Any, selected_paths: set[str]) -> dict[str, int]:
    """Minimum attainment each selected Path must reach by the target CL.

    Every selected Path must advance at least once.  A Path whose Subpath or
    Tradition is committed must reach that Subpath's minimum attainment, read
    from the sealed slot authority (``minimum_attainment_by_choice``, which
    Stage 1 derives from the same NS1R rule Stage 2 applies), default 3.
    """

    required = {path_id: 1 for path_id in selected_paths}
    subpath_rows = _slot_rows_by_id(request, envelope, "subpath_choice")
    minimum_by_choice: Mapping[str, Any] = {}
    for source in (_mapping(envelope), _mapping(request)):
        typed = _mapping(_mapping(_mapping(source.get("typed_choice_authority_by_slot")).get("subpath_choice")).get("minimum_attainment_by_choice"))
        if typed:
            minimum_by_choice = typed
            break
    for subpath_id in _state_slot(committed, "subpath_choice"):
        row = subpath_rows.get(subpath_id) or {}
        owner = row.get("owning_path_id", row.get("path_id", row.get("parent_path_id")))
        if not isinstance(owner, str) or owner not in required:
            continue
        minimum = minimum_by_choice.get(subpath_id, row.get("minimum_cl"))
        try:
            minimum = int(minimum) if minimum is not None else DEFAULT_SUBPATH_MINIMUM_ATTAINMENT
        except (TypeError, ValueError):
            minimum = DEFAULT_SUBPATH_MINIMUM_ATTAINMENT
        required[owner] = max(required[owner], minimum)
    return required


_METHOD_RULE_PATH_IDS = {
    "Body Refining": "tianxia.path.body_refining",
    "Qi Cultivation": "tianxia.path.qi_cultivation",
    "Spirit Awakening": "tianxia.path.spirit_awakening",
}
_SECONDARY_MINIMUM_RE = re.compile(r"For every\s+(\d+)\s+AP to\s+([A-Za-z ]+),\s+at least\s+(\d+)\s+AP to\s+([A-Za-z ]+)")


def _governing_method_id(request: Any, envelope: Any, committed: Any) -> str | None:
    """The Method whose allocation rule Stage 2 will apply to Path progression.

    A committed Method choice wins; otherwise the owner's EXACT access plan or
    exact planning choice, which Stage 2 sets as Primary Method even when the
    sealed envelope offered no Method row.
    """

    committed_methods = _state_slot(committed, "method_choice")
    if committed_methods:
        return committed_methods[0]
    for lock in _sealed_owner_locks(request, envelope):
        if lock.get("field") == "character_sheet.method_access_plan":
            value = lock.get("value")
            method_id = value.get("method_id") if isinstance(value, Mapping) else None
            if isinstance(method_id, str) and method_id:
                return method_id
    for lock in _sealed_owner_locks(request, envelope):
        if lock.get("field") == "character_sheet.planning_preferences":
            value = lock.get("value")
            method_id = value.get("method_exact_choice_id") if isinstance(value, Mapping) else None
            if isinstance(method_id, str) and method_id:
                return method_id
    return None


def _method_progression_constraints(request: Any, envelope: Any, committed: Any) -> list[dict[str, Any]]:
    """Mirror NS1R ``validate_allocation_state`` for the governing Method.

    Reads the sealed ``path_method_authority.method_allocation_by_id`` row and
    returns typed constraints on final Path attainment: the secondary-minimum
    inequality ``secondary * primary_ratio >= primary * secondary_ratio`` parsed
    with the same regex Stage 2 uses, EQUAL_SPLIT (all granted Paths equal),
    and MILESTONE_LOCKED (granted Paths within one level of each other).
    """

    method_id = _governing_method_id(request, envelope, committed)
    if not method_id:
        return []
    allocation: Mapping[str, Any] = {}
    for source in (_mapping(envelope), _mapping(request)):
        by_id = _mapping(_mapping(source.get("path_method_authority")).get("method_allocation_by_id"))
        if isinstance(by_id.get(method_id), Mapping):
            allocation = by_id[method_id]
            break
    if not allocation:
        return []
    granted = [value for value in allocation.get("granted_path_ids") or [] if isinstance(value, str)]
    rule = allocation.get("allocation_rule")
    constraints: list[dict[str, Any]] = []
    if rule == "PRIMARY_WITH_SECONDARY_MINIMUM":
        text = " ".join(str(value) for value in allocation.get("minimum_commitments") or [])
        for match in _SECONDARY_MINIMUM_RE.finditer(text):
            primary = _METHOD_RULE_PATH_IDS.get(match.group(2).strip())
            secondary = _METHOD_RULE_PATH_IDS.get(match.group(4).strip())
            if primary and secondary:
                constraints.append({"kind": "secondary_minimum", "primary": primary, "primary_ratio": int(match.group(1)), "secondary": secondary, "secondary_ratio": int(match.group(3))})
    elif rule == "EQUAL_SPLIT" and len(granted) > 1:
        constraints.append({"kind": "equal_split", "paths": granted})
    elif rule == "MILESTONE_LOCKED" and len(granted) > 1:
        # NS1R: granted Paths within one level of each other AND never
        # straddling a Realm boundary (MILESTONE_LOCKED_REALM_BOUNDARY_VIOLATION).
        constraints.append({"kind": "milestone_locked", "paths": granted})
        constraints.append({"kind": "realm_boundaries", "paths": granted})
    elif rule == "OWNER_DISTRIBUTED" and len(granted) > 1:
        # NS1R: "At least 1 AP to each" granted Path and no Realm-boundary
        # straddle (OWNER_DISTRIBUTED_REALM_MINIMUM_VIOLATION).
        constraints.append({"kind": "each_at_least_one", "paths": granted})
        constraints.append({"kind": "realm_boundaries", "paths": granted})
    return constraints


# NS1R REALM_BOUNDARIES: a milestone-locked or owner-distributed Method may not
# leave one granted Path at or past a boundary while another is still below it.
_REALM_BOUNDARIES = (5, 10, 15, 20)


def _constraints_hold(attained: Mapping[str, int], required: Mapping[str, int], constraints: Sequence[Mapping[str, Any]]) -> bool:
    if any(attained.get(path_id, 0) < minimum for path_id, minimum in required.items()):
        return False
    for constraint in constraints:
        kind = constraint.get("kind")
        if kind == "secondary_minimum":
            primary = attained.get(constraint["primary"], 0)
            secondary = attained.get(constraint["secondary"], 0)
            if secondary * constraint["primary_ratio"] < primary * constraint["secondary_ratio"]:
                return False
        elif kind in {"equal_split", "milestone_locked", "realm_boundaries", "each_at_least_one"}:
            values = [attained.get(path_id, 0) for path_id in constraint["paths"]]
            if kind == "equal_split" and len(set(values)) > 1:
                return False
            if kind == "milestone_locked" and values and max(values) - min(values) > 1:
                return False
            if kind == "each_at_least_one" and values and min(values) < 1:
                return False
            if kind == "realm_boundaries" and values and any(max(values) >= boundary > min(values) for boundary in _REALM_BOUNDARIES):
                return False
    return True


def _completion_feasible(attained: Mapping[str, int], remaining: Any, required: Mapping[str, int], constraints: Sequence[Mapping[str, Any]]) -> bool:
    """Can the still-unassigned advances be placed so every rule holds at the end?

    ``remaining`` is either an integer count of free advances (any Path) or
    the explicit list of unassigned future slots, each the list of Path IDs
    legal at that CL.  Owner-locked future CLs are already inside
    ``attained`` and must not appear as free slots.  Paths and CLs are small
    (at most three Paths, at most twenty CLs); the search backtracks over
    slots with memoisation on the attainment reached so far.
    """

    paths = sorted(set(attained) | set(required))
    if isinstance(remaining, int):
        if remaining < 0:
            return False
        slots: list[list[str]] = [list(paths) for _ in range(remaining)]
    else:
        slots = [[path_id for path_id in slot if isinstance(path_id, str)] for slot in remaining]
        if any(not slot for slot in slots):
            return False
    if not paths:
        return not slots
    seen: set[tuple[int, tuple[int, ...]]] = set()

    def search(index: int, current: dict[str, int]) -> bool:
        key = (index, tuple(current.get(path_id, 0) for path_id in paths))
        if key in seen:
            return False
        seen.add(key)
        if index == len(slots):
            return _constraints_hold(current, required, constraints)
        for path_id in slots[index]:
            current[path_id] = current.get(path_id, 0) + 1
            ok = search(index + 1, current)
            current[path_id] -= 1
            if ok:
                return True
        return False

    return search(0, {path_id: int(attained.get(path_id, 0)) for path_id in paths})


def _future_progression_slots(request: Any, envelope: Any, existing: Mapping[str, Any], selected_paths: set[str], current_cl: int, target_cl: int) -> list[list[str]]:
    """Unassigned future progression slots after ``current_cl`` with their legal Paths.

    A CL already committed or owner-locked is not free: its advance is
    counted in the attainment instead.  A CL the sealed contract leaves
    without any selected Path yields an empty slot, which makes completion
    infeasible.
    """

    slots: list[list[str]] = []
    for cl in range(current_cl + 1, target_cl + 1):
        key = str(cl)
        if key in existing or is_owner_locked(request, envelope, f"path_progression:{key}"):
            continue
        allowed = [
            candidate.choice_ids[0]
            for candidate in _progression_candidates(request, envelope, key)
            if candidate.choice_ids and candidate.choice_ids[0] in selected_paths
        ]
        slots.append(allowed)
    return slots


def progression_step_expected(request: Any, envelope: Any, committed: Any, cl: Any) -> bool:
    """Cheap test for whether a CL is a progression step worth building.

    Mirrors the early exits of ``build_path_progression_menu`` without the
    completion search: the CL is within the sealed target, not committed or
    owner-locked, at least one selected Path can advance there, and the CL is
    ambiguous (a lone selected Path at an unambiguous CL auto-resolves).  The
    walk lists descriptors with this and builds only the menu it reaches.
    """

    key = str(cl)
    target_cl = _frozen_target_cl(request, envelope)
    try:
        if target_cl is not None and int(key) > target_cl:
            return False
    except (TypeError, ValueError):
        return False
    existing = _mapping(_mapping(_state_mapping(committed).get("bounded")).get("path_progression_by_cl"))
    if key in existing or is_owner_locked(request, envelope, f"path_progression:{key}") or is_owner_locked(request, envelope, "path_progression"):
        return False
    selected_paths = set(_state_slot(committed, "path_choice"))
    if not selected_paths:
        return False
    candidates = [c for c in _progression_candidates(request, envelope, key) if c.choice_ids and c.choice_ids[0] in selected_paths]
    if not candidates:
        return False
    pinned = resolved_milestone_path_by_cl(request, envelope, committed).get(key)
    if isinstance(pinned, str) and any(c.choice_ids[0] == pinned for c in candidates):
        candidates = [c for c in candidates if c.choice_ids[0] == pinned]
    advertised = [value for value in _response_progression_values(request, envelope, key) if value in selected_paths]
    return not (len(candidates) == 1 and len(advertised) <= 1)


def build_path_progression_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, cl: int | str, ordinal: int = 1, page: int = 1) -> StepMenu | None:
    key = str(cl)
    target_cl = _frozen_target_cl(request, envelope)
    if target_cl is not None:
        try:
            if int(key) > target_cl:
                return None
        except (TypeError, ValueError):
            return None
    existing = _mapping(_mapping(_state_mapping(committed).get("bounded")).get("path_progression_by_cl"))
    if key in existing or is_owner_locked(request, envelope, f"path_progression:{key}") or is_owner_locked(request, envelope, "path_progression"):
        return None
    # The sealed progression rows advertise every selectable Path that can
    # advance at a CL.  The delegated validator only admits a route among the
    # Paths the plan actually selected, and auto-resolves when exactly one of
    # those advances.  Mirror that: no selected Path means no legal route yet,
    # and only the selected Paths count toward ambiguity.
    selected_paths = set(_state_slot(committed, "path_choice"))
    if not selected_paths:
        return None
    candidates = [
        candidate
        for candidate in _progression_candidates(request, envelope, key)
        if candidate.choice_ids and candidate.choice_ids[0] in selected_paths
    ]
    if not candidates:
        return None
    # A milestone already resolved at this CL names the level's representative
    # Path (advancement milestones are one character choice per level).
    pinned = resolved_milestone_path_by_cl(request, envelope, committed).get(key)
    if isinstance(pinned, str) and any(candidate.choice_ids[0] == pinned for candidate in candidates):
        candidates = [candidate for candidate in candidates if candidate.choice_ids[0] == pinned]
    advertised = [value for value in _response_progression_values(request, envelope, key) if value in selected_paths]
    # The initial-creation compiler requires every selected Path to advance
    # at least once across CL 1..target (NS1R_INITIAL_CREATION_PROGRESS_MAP_
    # INVALID otherwise), and a Path whose Subpath or Tradition is selected
    # must reach that Subpath's minimum attainment (NS1R_SUBPATH_CL_NOT_MET /
    # NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID otherwise; Stage 1
    # publishes the minimum on the Subpath row, default 3).  The first real
    # two-Path Granite walk advanced one Path at all ten CLs.  Once the CLs
    # left cannot complete a legal split, only Paths from which a legal
    # completion still exists remain legal at this CL.  The governing Method's
    # allocation rule (secondary minimum, equal split, milestone lock) is
    # mirrored from NS1R the same way.
    try:
        current_cl = int(key)
    except (TypeError, ValueError):
        current_cl = None
    equal_mode = equal_initial_path_attainment(_mapping(request))
    if target_cl is not None and equal_mode:
        vector = initial_path_attainment_vector(sorted(selected_paths), target_cl)
        required = _required_path_attainment(request, envelope, committed, selected_paths)
        constraints = _method_progression_constraints(request, envelope, committed)
        if not _constraints_hold(vector, required, constraints):
            raise LinearMenuError("DCC_LINEAR_PROGRESSION_UNSATISFIABLE", "The selected Method cannot support the requested equal Path attainment.", details={"target_cl": target_cl, "path_attainment": vector, "constraints": constraints})
    if target_cl is not None and current_cl is not None and len(selected_paths) > 1 and not equal_mode:
        required = _required_path_attainment(request, envelope, committed, selected_paths)
        attained: dict[str, int] = {path_id: 0 for path_id in selected_paths}
        for value in existing.values():
            if isinstance(value, str) and value in attained:
                attained[value] += 1
        future_slots = _future_progression_slots(request, envelope, existing, selected_paths, current_cl, target_cl)
        constraints = _method_progression_constraints(request, envelope, committed)
        feasible = []
        for candidate in candidates:
            path_id = candidate.choice_ids[0]
            trial = dict(attained)
            trial[path_id] = trial.get(path_id, 0) + 1
            if _completion_feasible(trial, future_slots, required, constraints):
                feasible.append(candidate)
        if not feasible:
            # No pick at this CL can still reach a legal final split: earlier
            # choices or owner locks contradict the Subpath minima or the
            # Method's allocation rule.  Stop here with the exact facts rather
            # than offering options the compiler will reject (a ``None`` menu
            # would be treated as a skippable step).
            raise LinearMenuError(
                "DCC_LINEAR_PROGRESSION_UNSATISFIABLE",
                "No Path progression choice at this CL can still complete a legal allocation.",
                details={
                    "cl": current_cl,
                    "target_cl": target_cl,
                    "attained_including_locks": attained,
                    "required_minimum_attainment": required,
                    "unassigned_future_slots": future_slots,
                    "method_constraints": constraints,
                    "candidate_path_ids": [candidate.choice_ids[0] for candidate in candidates],
                },
            )
        candidates = feasible
    if len(candidates) == 1 and len(advertised) <= 1:
        # A genuinely unambiguous CL resolves without an explicit pick,
        # mirroring the validator's single-route rule.  A singleton narrowed
        # from an ambiguous response authority is still offered as an
        # explicit 1/1 choice: the validator requires one exact Path route
        # at that CL, and the narrowed ID is the contract-legal one.
        return None
    return _make_menu(request, envelope, committed, step_id=f"path_progression:{key}", step_kind="path_progression", ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page)


def _proficiency_entries(request: Any, envelope: Any, field: str) -> Mapping[str, Any]:
    contract = _bounded_choice_contract(request, envelope)
    contract_fields = contract.get("fields")
    starting = _starting_proficiency_contract(request, envelope)
    starting_fields = starting.get("fields") if isinstance(starting, Mapping) else None
    direct_fields = contract.get("fields")
    candidates: list[Any] = []
    if isinstance(starting_fields, Mapping):
        candidates.append(starting_fields.get(field))
    if isinstance(direct_fields, Mapping):
        direct = direct_fields.get(field)
        if isinstance(direct, Mapping) and isinstance(direct.get("selection_map"), str) and isinstance(starting_fields, Mapping):
            candidates.append(starting_fields.get(direct["selection_map"]))
        candidates.append(direct)
    candidates.extend((contract.get(field), _first(request, envelope, field)))
    for candidate in candidates:
        if isinstance(candidate, Mapping) and any(isinstance(value, Mapping) for value in candidate.values()):
            return candidate
    return {}


def _proficiency_entry(request: Any, envelope: Any, field: str, owner_id: str) -> Mapping[str, Any] | None:
    entries = _proficiency_entries(request, envelope, field)
    value = entries.get(owner_id)
    return value if isinstance(value, Mapping) else None


def _proficiency_values(entry: Mapping[str, Any], field: str) -> tuple[list[str], int]:
    raw = entry.get("allowed_values")
    values = sorted({value for value in raw if isinstance(value, str) and value} ) if isinstance(raw, (list, tuple)) else []
    count = entry.get("language_choice_count") if field == "background_language_choices_by_background_id" else entry.get("required_count", 1)
    if type(count) is not int or count < 1:
        return [], 0
    return values, count


def _proficiency_menu(request: Any, envelope: Any, committed: Any, *, field: str, owner_id: str, selection_index: int, ordinal: int, page: int, step_id: str | None = None) -> StepMenu | None:
    if owner_id not in _state_slot(committed, _PROFICIENCY_SLOTS[field]):
        return None
    entry = _proficiency_entry(request, envelope, field, owner_id)
    if entry is None:
        return None
    values, required = _proficiency_values(entry, field)
    if not values:
        return None
    bounded = _mapping(_state_mapping(committed).get("bounded"))
    chosen_map = _mapping(bounded.get(field))
    chosen = [value for value in chosen_map.get(owner_id, []) if isinstance(value, str)] if isinstance(chosen_map.get(owner_id), (list, tuple)) else []
    index = selection_index if type(selection_index) is int and selection_index > 0 else len(chosen) + 1
    index = max(index, len(chosen) + 1)
    if len(chosen) >= required or index > required:
        return None
    actual_step_id = step_id or f"{_PROFICIENCY_KINDS[field]}:{owner_id}" + (f":{index}" if index > 1 else "")
    base_step_id = f"{_PROFICIENCY_KINDS[field]}:{owner_id}"
    if any(is_owner_locked(request, envelope, key) for key in (actual_step_id, base_step_id, _PROFICIENCY_KINDS[field])):
        return None
    candidates = [_Candidate((value,), value[:MAX_CUE_LENGTH], OPTION_PICK) for value in values if value not in chosen]
    if not candidates:
        return None
    return _make_menu(request, envelope, committed, step_id=actual_step_id, step_kind=_PROFICIENCY_KINDS[field], ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page)


def build_path_skill_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, path_id: str, ordinal: int = 1, page: int = 1, selection_index: int = 1, step_id: str | None = None) -> StepMenu | None:
    return _proficiency_menu(request, envelope, committed, field="path_skill_choices_by_path_id", owner_id=path_id, selection_index=selection_index, ordinal=ordinal, page=page, step_id=step_id)


def build_origin_skill_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, origin_id: str, ordinal: int = 1, page: int = 1, selection_index: int = 1, step_id: str | None = None) -> StepMenu | None:
    return _proficiency_menu(request, envelope, committed, field="origin_skill_choices_by_origin_id", owner_id=origin_id, selection_index=selection_index, ordinal=ordinal, page=page, step_id=step_id)


def build_background_language_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, background_id: str, ordinal: int = 1, page: int = 1, selection_index: int = 1, step_id: str | None = None) -> StepMenu | None:
    return _proficiency_menu(request, envelope, committed, field="background_language_choices_by_background_id", owner_id=background_id, selection_index=selection_index, ordinal=ordinal, page=page, step_id=step_id)


def build_item_priorities_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, step_id: str = "item_priorities", ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    return _menu_for_slot(request, envelope, committed, step_id=step_id, step_kind="item_priorities", slot_id="item_priorities", ordinal=ordinal, page=page, selection_index=selection_index, default_min=0, default_max=1)


def starting_kit_context(committed: Any) -> tuple[str, str, Mapping[str, Any]] | None:
    """(Background ID, highest Path ID, committed kit decision) once both are chosen."""

    from factory_authoring.starting_kits import has_starting_kit, highest_path

    backgrounds = _state_slot(committed, "background_choice")
    paths = _state_slot(committed, "path_choice")
    if not backgrounds or not paths:
        return None
    bounded = _mapping(_state_mapping(committed).get("bounded"))
    path_id = highest_path(list(dict.fromkeys(paths)), _mapping(bounded.get("path_progression_by_cl")))
    # Only a Background and Path with a published starting kit get kit steps.
    if not has_starting_kit(backgrounds[0], path_id):
        return None
    return backgrounds[0], path_id, _mapping(bounded.get("starting_kit"))


def owner_gear_preferences(request: Any, envelope: Any) -> list[str]:
    """The owner's preferred weapons and armour, sealed into the run request."""

    value = _first(request, envelope, "owner_gear_preferences")
    return [item for item in value if isinstance(item, str) and item] if isinstance(value, (list, tuple)) else []


def owner_kit_plan(request: Any, envelope: Any, committed: Any) -> Mapping[str, Any] | None:
    """The kit decision that honours the owner's preferred gear, if any."""

    from factory_authoring.starting_kits import preferred_kit_plan

    preferences = owner_gear_preferences(request, envelope)
    context = starting_kit_context(committed)
    if not preferences or context is None:
        return None
    return preferred_kit_plan(context[0], context[1], preferences, picks=context[2].get("picks"))


def build_starting_kit_option_menu(request, envelope, committed=None, *, ordinal=1, page=1, selection_index=1):
    """5.5e-style starting kit: option A (gear) or option B (coin to buy gear)."""

    from factory_authoring.starting_kits import PATH_OPTIONS, path_kit_summary

    context = starting_kit_context(committed)
    if context is None or context[2].get("path_option"):
        return None
    _background_id, path_id, _kit = context
    plan = owner_kit_plan(request, envelope, committed)
    options = [plan["path_option"]] if plan else list(PATH_OPTIONS)
    candidates = [
        _Candidate((option,), f"{'A' if option == 'option_a' else 'B'}: {path_kit_summary(path_id, option)}"[:MAX_CUE_LENGTH])
        for option in options
    ]
    return _make_menu(
        request, envelope, committed, step_id="starting_kit_option", step_kind="starting_kit_option",
        ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page, preserve_candidate_order=True,
    )


def build_starting_kit_choice_menu(request, envelope, committed=None, *, step_id, ordinal=1, page=1, selection_index=1):
    """One closed choice from the printed Background kit or the Path kit."""

    from factory_authoring.starting_kits import choice_menus

    context = starting_kit_context(committed)
    if context is None or not context[2].get("path_option"):
        return None
    background_id, path_id, kit = context
    choice_id = step_id.split(":", 1)[1]
    if choice_id in _mapping(kit.get("picks")):
        return None
    menu = next((row for row in choice_menus(background_id, path_id, kit["path_option"]) if row["choice_id"] == choice_id), None)
    if menu is None:
        return None
    prefix = f"For \"{menu['printed']}\": " if menu.get("printed") else ""
    candidates = [
        _Candidate((f"{choice_id}={index}",), f"{prefix}{label}"[:MAX_CUE_LENGTH])
        for index, label in enumerate(menu["options"])
    ]
    # The owner's preferred weapon or armour pins its menu.
    plan = owner_kit_plan(request, envelope, committed)
    pinned = _mapping(plan.get("picks")).get(choice_id) if plan and plan.get("path_option") == kit["path_option"] else None
    if type(pinned) is int and 0 <= pinned < len(candidates):
        candidates = [candidates[pinned]]
    return _make_menu(
        request, envelope, committed, step_id=step_id, step_kind="starting_kit_choice",
        ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page, preserve_candidate_order=True,
    )


def treasure_context(request: Any, envelope: Any, committed: Any) -> dict[str, Any] | None:
    """The character's treasure inputs once the starting kit's Background and Path are known.

    Item Book Chapters 2-5: the server sets every finished grade and the budget
    split (``factory_authoring.treasure_catalog.treasure_plan``); the model picks
    the weapon, the armour, Wondrous Treasures and consumables from closed
    menus.  All of it is carried by the constructed starting-kit record.
    """
    kit = starting_kit_context(committed)
    target_cl = _frozen_target_cl(request, envelope)
    if kit is None or type(target_cl) is not int:
        return None
    bounded = _mapping(_state_mapping(committed).get("bounded"))
    return {
        "target_cl": target_cl,
        "background_id": kit[0],
        "path_id": kit[1],
        "weapon": _mapping(bounded.get("treasure_weapon")),
        "armor": _mapping(bounded.get("treasure_armor")),
        "wondrous": _mapping(bounded.get("treasure_wondrous")),
        "consumables": _mapping(bounded.get("treasure_consumables")),
        "ability_scores": _mapping(bounded.get("ability_scores")),
    }


def treasure_next_step(request: Any, envelope: Any, committed: Any) -> str | None:
    """The next open treasure step: weapon, then armour, then Wondrous Treasures, then consumables."""
    from factory_authoring.treasure_armor import armor_grade, chassis_options as armor_chassis_options, enhancement_options
    from factory_authoring.treasure_catalog import consumable_options, treasure_plan, wondrous_options
    from factory_authoring.treasure_weapons import enchantment_options, weapon_grade

    context = treasure_context(request, envelope, committed)
    if context is None:
        return None
    grade = weapon_grade(context["target_cl"], context["background_id"])
    if grade is None:
        return None
    weapon = context["weapon"]
    if not weapon.get("chassis_id"):
        return "treasure_weapon_chassis"
    if not weapon.get("material_id"):
        return "treasure_weapon_material"
    chosen = list(weapon.get("enchantment_ids") or [])
    if not weapon.get("done") and enchantment_options(weapon["chassis_id"], weapon["material_id"], grade["grade"], chosen):
        return f"treasure_weapon_enchantment:{len(chosen) + 1}"
    armor_info = armor_grade(context["target_cl"], context["background_id"])
    if armor_info is not None and armor_chassis_options(context["path_id"]):
        armor = context["armor"]
        if not armor.get("chassis_id"):
            return "treasure_armor_chassis"
        if not armor.get("material_id"):
            return "treasure_armor_material"
        chosen = list(armor.get("enhancement_ids") or [])
        if not armor.get("done") and enhancement_options(armor["chassis_id"], armor["material_id"], armor_info["grade"], chosen):
            return f"treasure_armor_enhancement:{len(chosen) + 1}"
    plan = treasure_plan(context["target_cl"], context["background_id"], context["path_id"])
    for key, kind, options in (("wondrous", "treasure_wondrous", wondrous_options), ("consumables", "treasure_consumable", consumable_options)):
        bought = list(context[key].get("ids") or [])
        if not context[key].get("done") and options(plan, bought):
            return f"{kind}:{len(bought) + 1}"
    return None


def _treasure_menu(request, envelope, committed, step_id, step_kind, candidates, *, ordinal, page, finish_cue=None):
    if treasure_next_step(request, envelope, committed) != step_id or not candidates:
        return None
    if finish_cue is not None:
        candidates = [*candidates, _Candidate((), finish_cue, OPTION_NONE)]
    return _make_menu(request, envelope, committed, step_id=step_id, step_kind=step_kind,
                      ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page, concept_ranked_order=True)


_GRADE_RANK = {"Spiritual": 1, "Saint": 2, "Sovereign": 3, "Imperial": 4}


def _best_first(rows, *, bonus_key: str | None = None):
    """Highest grade (or largest Equivalent Bonus) first, then by name."""
    if bonus_key is not None:
        return sorted(rows, key=lambda row: (-int(row[bonus_key]), row["name"]))
    return sorted(rows, key=lambda row: (-_GRADE_RANK.get(row["grade"], 0), row["name"]))


def build_treasure_weapon_chassis_menu(request, envelope, committed=None, *, ordinal=1, page=1, selection_index=1):
    from factory_authoring.treasure_weapons import sphere_fit_chassis, weapon_grade

    context = treasure_context(request, envelope, committed)
    grade = weapon_grade(context["target_cl"], context["background_id"]) if context else None
    if grade is None:
        return None
    # Owner 2026-09-24: a Sabers character got a dagger.  Only weapons the
    # character's weapon Spheres can use are offered, best fit first.
    known = _known_sphere_ids(request, envelope, committed)
    candidates = [
        _Candidate((row["item_id"],), f"{grade['grade']} Treasure: {row['name']} ({row['damage']}; {row.get('properties') or 'no properties'})"[:MAX_CUE_LENGTH])
        for row in sphere_fit_chassis(known, path_id=context.get("path_id"), scores=context.get("ability_scores"))
    ]
    return _treasure_menu(request, envelope, committed, "treasure_weapon_chassis", "treasure_weapon_chassis", candidates, ordinal=ordinal, page=page)


def build_treasure_weapon_material_menu(request, envelope, committed=None, *, ordinal=1, page=1, selection_index=1):
    from factory_authoring.treasure_weapons import material_options, weapon_grade

    context = treasure_context(request, envelope, committed)
    grade = weapon_grade(context["target_cl"], context["background_id"]) if context else None
    if grade is None:
        return None
    candidates = [
        _Candidate((row["material_id"],), f"{row['name']} ({row['grade']}; {', '.join(row['affinities'])}): {row['property_name']}"[:MAX_CUE_LENGTH])
        for row in _best_first(material_options(grade["grade"]))
    ]
    return _treasure_menu(request, envelope, committed, "treasure_weapon_material", "treasure_weapon_material", candidates, ordinal=ordinal, page=page)


def build_treasure_weapon_enchantment_menu(request, envelope, committed=None, *, step_id="treasure_weapon_enchantment:1", ordinal=1, page=1, selection_index=1):
    from factory_authoring.treasure_weapons import enchantment_options, weapon_grade

    context = treasure_context(request, envelope, committed)
    grade = weapon_grade(context["target_cl"], context["background_id"]) if context else None
    weapon = context["weapon"] if context else {}
    if grade is None or not weapon.get("material_id"):
        return None
    chosen = list(weapon.get("enchantment_ids") or [])
    candidates = [
        _Candidate((row["enchantment_id"],), f"+{row['equivalent_bonus']} {row['name']} ({row['family']})"[:MAX_CUE_LENGTH])
        for row in _best_first(enchantment_options(weapon["chassis_id"], weapon["material_id"], grade["grade"], chosen), bonus_key="equivalent_bonus")
    ]
    return _treasure_menu(request, envelope, committed, step_id, "treasure_weapon_enchantment", candidates, ordinal=ordinal, page=page,
                          finish_cue="Finish the weapon" if chosen else None)


def build_treasure_armor_chassis_menu(request, envelope, committed=None, *, ordinal=1, page=1, selection_index=1):
    from factory_authoring.treasure_armor import armor_grade, chassis_options

    context = treasure_context(request, envelope, committed)
    grade = armor_grade(context["target_cl"], context["background_id"]) if context else None
    if grade is None:
        return None
    candidates = [
        _Candidate((row["item_id"],), f"{grade['grade']} Treasure: {row['name']} ({row['armor_category']}; AC {row['armor_class']}; Stealth {row['stealth']})"[:MAX_CUE_LENGTH])
        for row in chassis_options(context["path_id"])
    ]
    return _treasure_menu(request, envelope, committed, "treasure_armor_chassis", "treasure_armor_chassis", candidates, ordinal=ordinal, page=page)


def build_treasure_armor_material_menu(request, envelope, committed=None, *, ordinal=1, page=1, selection_index=1):
    from factory_authoring.treasure_armor import armor_grade, material_options

    context = treasure_context(request, envelope, committed)
    grade = armor_grade(context["target_cl"], context["background_id"]) if context else None
    armor = context["armor"] if context else {}
    if grade is None or not armor.get("chassis_id"):
        return None
    candidates = [
        _Candidate((row["material_id"],), f"{row['name']} ({row['grade']}; {', '.join(row['affinities'])}): {row['property_name']}"[:MAX_CUE_LENGTH])
        for row in _best_first(material_options(grade["grade"], armor["chassis_id"]))
    ]
    return _treasure_menu(request, envelope, committed, "treasure_armor_material", "treasure_armor_material", candidates, ordinal=ordinal, page=page)


def build_treasure_armor_enhancement_menu(request, envelope, committed=None, *, step_id="treasure_armor_enhancement:1", ordinal=1, page=1, selection_index=1):
    from factory_authoring.treasure_armor import armor_grade, enhancement_options

    context = treasure_context(request, envelope, committed)
    grade = armor_grade(context["target_cl"], context["background_id"]) if context else None
    armor = context["armor"] if context else {}
    if grade is None or not armor.get("material_id"):
        return None
    chosen = list(armor.get("enhancement_ids") or [])
    candidates = [
        _Candidate((row["enhancement_id"],), f"+{row['equivalent_bonus']} {row['name']} ({row['family']})"[:MAX_CUE_LENGTH])
        for row in _best_first(enhancement_options(armor["chassis_id"], armor["material_id"], grade["grade"], chosen), bonus_key="equivalent_bonus")
    ]
    return _treasure_menu(request, envelope, committed, step_id, "treasure_armor_enhancement", candidates, ordinal=ordinal, page=page,
                          finish_cue="Finish the armour" if chosen else None)


def build_treasure_wondrous_menu(request, envelope, committed=None, *, step_id="treasure_wondrous:1", ordinal=1, page=1, selection_index=1):
    from factory_authoring.treasure_catalog import treasure_plan, wondrous_options

    context = treasure_context(request, envelope, committed)
    plan = treasure_plan(context["target_cl"], context["background_id"], context["path_id"]) if context else None
    if plan is None:
        return None
    bought = list(context["wondrous"].get("ids") or [])
    candidates = [
        _Candidate((row["treasure_id"],), f"{row['grade']} {row['item_type']}: {row['name']} ({row['family']}{'; attunement' if row['attunement_slots'] else ''})"[:MAX_CUE_LENGTH])
        for row in _best_first(wondrous_options(plan, bought))
    ]
    return _treasure_menu(request, envelope, committed, step_id, "treasure_wondrous", candidates, ordinal=ordinal, page=page,
                          finish_cue="Buy no more Wondrous Treasures" if bought else None)


def build_treasure_consumable_menu(request, envelope, committed=None, *, step_id="treasure_consumable:1", ordinal=1, page=1, selection_index=1):
    from factory_authoring.treasure_catalog import consumable_options, treasure_plan

    context = treasure_context(request, envelope, committed)
    plan = treasure_plan(context["target_cl"], context["background_id"], context["path_id"]) if context else None
    if plan is None:
        return None
    bought = list(context["consumables"].get("ids") or [])
    candidates = [
        _Candidate((row["consumable_id"],), f"{row['grade']} {row['family']}: {row['name']} x{row['batch_quantity']} {row['batch_unit']}"[:MAX_CUE_LENGTH])
        for row in _best_first(consumable_options(plan, bought))
    ]
    return _treasure_menu(request, envelope, committed, step_id, "treasure_consumable", candidates, ordinal=ordinal, page=page,
                          finish_cue="Buy no more consumables" if bought else None)


def build_forged_design_menu(request, envelope, committed=None, *, step_id="forged_design:1", ordinal=1, page=1, selection_index=1):
    from app.core import FoundryError
    from character_creation.constructed_arts.explicit_forging import DESIGNS, has_explicit_forging_contract, validate_required_design_selection

    if not has_explicit_forging_contract(envelope):
        return None
    bounded = _mapping(_state_mapping(committed).get("bounded"))
    chosen = bounded.get("forged_design_ids") or []
    missing = validate_required_design_selection(envelope, chosen, complete=bounded.get("forged_design_done") is True, request=request)
    if bounded.get("forged_design_done") is True:
        return None
    known = _committed_acquired_talent_ids(committed)
    cl = _frozen_target_cl(request, envelope) or 0
    unavailable = [key for key in missing if DESIGNS[key]["minimum_cl"] > cl or DESIGNS[key]["concept"]["primary_talent_id"] not in known]
    if unavailable:
        raise FoundryError("DCC_REQUIRED_FORGED_DESIGN_UNAVAILABLE", "A required Forge design lacks its acquired primary Talent or minimum cultivation level.", details={"design_ids": unavailable})
    candidates = [
        _Candidate((key,), row["cue"], OPTION_PICK)
        for key, row in DESIGNS.items()
        if key not in chosen and row["minimum_cl"] <= cl and row["concept"]["primary_talent_id"] in known
    ] if len(chosen) < 2 else []
    if not missing:
        candidates.append(_Candidate((), "Finish Forge designs; acquire no additional technique", OPTION_NONE))
    return _make_menu(request, envelope, committed, step_id=step_id, step_kind="forged_design", ordinal=ordinal, minimum=1, maximum=1, candidates=candidates, page=page)


def build_identity_menu(request: Mapping[str, Any], envelope: Mapping[str, Any], committed: Any = None, *, ordinal: int = 1, page: int = 1, selection_index: int = 1) -> StepMenu | None:
    if owner_lock_for(request, envelope, "identity") is not _MISSING:
        return None
    return _make_menu(request, envelope, committed, step_id="identity", step_kind="identity", ordinal=ordinal, minimum=1, maximum=1, candidates=[_Candidate((), "Provide a bounded name and title", OPTION_NONE)], page=page)


def build_step_menu(
    request: Mapping[str, Any] | str,
    envelope: Mapping[str, Any] | Mapping[str, Any] | None = None,
    committed: Any = None,
    *,
    step_id: str | None = None,
    step_kind: str | None = None,
    ordinal: int = 1,
    page: int = 1,
    selection_index: int = 1,
) -> StepMenu | None:
    """Dispatch one step builder.

    ``step_id`` is preferred.  For compatibility with small provider-free
    callers, ``step_kind`` may be supplied for simple singleton steps.
    """

    request_map = request if isinstance(request, Mapping) else {}
    envelope_map = envelope if isinstance(envelope, Mapping) else {}
    step_id = step_id or step_kind
    if not isinstance(step_id, str) or not step_id:
        _error("DCC_LINEAR_STEP_ID", "build_step_menu requires step_id or step_kind.")
    base_kind = step_id.split(":", 1)[0]
    if base_kind == "forged_design":
        return build_forged_design_menu(request_map, envelope_map, committed, step_id=step_id, ordinal=ordinal, page=page)
    if base_kind == "subpath_choice":
        suffix = step_id.split(":", 1)[1] if ":" in step_id else ""
        require_choice = suffix.endswith(":required")
        path_id = suffix[: -len(":required")] if require_choice else (suffix or None)
        return build_subpath_choice_menu(request_map, envelope_map, committed, path_id=path_id, ordinal=ordinal, page=page, selection_index=selection_index, require_choice=require_choice)
    if base_kind == "sphere_free_talent_pair":
        pair_index = step_id.split(":", 1)[1] if ":" in step_id else ""
        return build_sphere_free_talent_pair_menu(request_map, envelope_map, committed, pair_index=int(pair_index) if pair_index.isdigit() else 0, ordinal=ordinal, page=page)
    if base_kind == "ordinary_talent":
        cl = step_id.split(":", 1)[1] if ":" in step_id else ""
        return build_ordinary_talent_menu(request_map, envelope_map, committed, cl=int(cl) if cl.isdigit() else 0, ordinal=ordinal, page=page)
    if base_kind == "creation_training":
        parts = step_id.split(":")
        cl = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        slot = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        return build_creation_training_menu(request_map, envelope_map, committed, cl=cl, slot=slot, ordinal=ordinal, page=page)
    if base_kind == "insight_occurrence":
        suffix = step_id.split(":", 1)[1] if ":" in step_id else ""
        ability_follow_up = suffix.endswith(":ability")
        milestone_id = suffix[:-len(":ability")] if ability_follow_up else suffix
        return build_insight_occurrence_menu(
            request_map,
            envelope_map,
            committed,
            milestone_id=milestone_id,
            ordinal=ordinal,
            page=page,
            step_id=step_id,
            ability_follow_up=ability_follow_up,
        )
    if base_kind == "point_buy_preset":
        return build_point_buy_preset_menu(request_map, envelope_map, committed, ordinal=ordinal, page=page)
    if base_kind == "point_buy_assignment":
        return build_point_buy_assignment_menu(request_map, envelope_map, committed, ordinal=ordinal, page=page)
    if base_kind == "asi_or_insight":
        milestone_id = step_id.split(":", 1)[1] if ":" in step_id else ""
        return build_asi_or_insight_menu(request_map, envelope_map, committed, milestone_id=milestone_id, ordinal=ordinal, page=page)
    if base_kind == "asi_milestone":
        milestone_id = step_id.split(":", 1)[1] if ":" in step_id else ""
        return build_asi_milestone_menu(request_map, envelope_map, committed, milestone_id=milestone_id, ordinal=ordinal, page=page)
    if base_kind == "path_progression":
        cl = step_id.split(":", 1)[1] if ":" in step_id else ""
        return build_path_progression_menu(request_map, envelope_map, committed, cl=cl, ordinal=ordinal, page=page)
    if base_kind in {"path_skill", "origin_skill", "background_language"}:
        suffix = step_id.split(":", 1)[1] if ":" in step_id else ""
        owner_id = suffix
        indexed = 1
        if ":" in suffix and suffix.rsplit(":", 1)[1].isdigit():
            owner_id, raw_index = suffix.rsplit(":", 1)
            indexed = int(raw_index)
        builder = {
            "path_skill": build_path_skill_menu,
            "origin_skill": build_origin_skill_menu,
            "background_language": build_background_language_menu,
        }[base_kind]
        owner_key = {
            "path_skill": "path_id",
            "origin_skill": "origin_id",
            "background_language": "background_id",
        }[base_kind]
        return builder(
            request_map,
            envelope_map,
            committed,
            **{owner_key: owner_id, "ordinal": ordinal, "page": page, "selection_index": indexed, "step_id": step_id},
        )
    builders = {
        "path_choice": build_path_choice_menu,
        "method_choice": build_method_choice_menu,
        "foundation_choice": build_foundation_choice_menu,
        "foundation_initial_stage": build_foundation_initial_stage_menu,
        "background_choice": build_background_choice_menu,
        "background_sphere_choice": build_background_sphere_choice_menu,
        "background_talent_choice": build_background_talent_choice_menu,
        "background_ability": build_background_ability_menu,
        "origin_insight_choice": build_origin_insight_choice_menu,
        "sphere_route": build_sphere_route_menu,
        "sphere_priorities": build_sphere_priorities_menu,
        "insight_priorities": build_insight_priorities_menu,
        "item_priorities": build_item_priorities_menu,
        "starting_kit_option": build_starting_kit_option_menu,
        "starting_kit_choice": build_starting_kit_choice_menu,
        "treasure_weapon_chassis": build_treasure_weapon_chassis_menu,
        "treasure_weapon_material": build_treasure_weapon_material_menu,
        "treasure_weapon_enchantment": build_treasure_weapon_enchantment_menu,
        "treasure_armor_chassis": build_treasure_armor_chassis_menu,
        "treasure_armor_material": build_treasure_armor_material_menu,
        "treasure_armor_enhancement": build_treasure_armor_enhancement_menu,
        "treasure_wondrous": build_treasure_wondrous_menu,
        "treasure_consumable": build_treasure_consumable_menu,
        "identity": build_identity_menu,
    }
    builder = builders.get(base_kind)
    if builder is None:
        _error("DCC_LINEAR_STEP_KIND", "Unsupported linear step ID.", details={"step_id": step_id})
    builder_kwargs = {"ordinal": ordinal, "page": page, "selection_index": selection_index}
    if base_kind in {"path_choice", "item_priorities", "insight_priorities", "starting_kit_choice", "treasure_weapon_enchantment",
                     "treasure_armor_enhancement", "treasure_wondrous", "treasure_consumable"}:
        builder_kwargs["step_id"] = step_id
    return builder(request_map, envelope_map, committed, **builder_kwargs)


def menu_for_step(*args: Any, **kwargs: Any) -> StepMenu | None:
    return build_step_menu(*args, **kwargs)


def build_linear_menu(*args: Any, **kwargs: Any) -> StepMenu | None:
    return build_step_menu(*args, **kwargs)


def validate_step_menu(menu: StepMenu) -> StepMenu:
    if not isinstance(menu, StepMenu):
        _error("DCC_LINEAR_MENU_TYPE", "Expected a StepMenu.")
    # Re-running the dataclass checks also catches mutation of nested options
    # by an external caller after construction.
    StepMenu(
        step_id=menu.step_id,
        step_kind=menu.step_kind,
        ordinal=menu.ordinal,
        title=menu.title,
        min_choices=menu.min_choices,
        max_choices=menu.max_choices,
        options=tuple(menu.options),
        page_id=menu.page_id,
        next_page_id=menu.next_page_id,
        authority_sha256=menu.authority_sha256,
        menu_sha256=menu.menu_sha256,
    )
    return menu


__all__ = [
    "LINEAR_MENU_SCHEMA",
    "LINEAR_OPTION_SCHEMA",
    "LINEAR_STATE_SCHEMA",
    "MAX_OPTIONS_PER_PAGE",
    "MAX_PAGES_PER_STEP",
    "MAX_WALK_STEPS",
    "OPTION_PICK",
    "OPTION_BUNDLE",
    "OPTION_NONE",
    "LinearMenuError",
    "StepOption",
    "StepMenu",
    "CommittedState",
    "owner_lock_for",
    "is_owner_locked",
    "build_path_choice_menu",
    "build_subpath_choice_menu",
    "build_method_choice_menu",
    "build_foundation_choice_menu",
    "build_background_choice_menu",
    "build_background_sphere_choice_menu",
    "build_background_talent_choice_menu",
    "build_background_ability_menu",
    "build_origin_insight_choice_menu",
    "build_point_buy_preset_menu",
    "build_point_buy_assignment_menu",
    "build_sphere_free_talent_pair_menu",
    "build_sphere_route_menu",
    "build_ordinary_talent_menu",
    "build_sphere_priorities_menu",
    "build_insight_priorities_menu",
    "build_insight_occurrence_menu",
    "build_asi_or_insight_menu",
    "STEP_KIND_ASI_OR_INSIGHT",
    "MILESTONE_BRANCH_ABILITY_INCREASE",
    "MILESTONE_BRANCH_INSIGHT",
    "MILESTONE_BRANCHES",
    "recorded_milestone_branch",
    "treasure_context",
    "treasure_next_step",
    "build_asi_milestone_menu",
    "build_path_progression_menu",
    "progression_step_expected",
    "build_path_skill_menu",
    "build_origin_skill_menu",
    "build_background_language_menu",
    "build_item_priorities_menu",
    "build_identity_menu",
    "build_step_menu",
    "menu_for_step",
    "build_linear_menu",
    "validate_step_menu",
]
