"""Pure step ordering and commit engine for DCC linear walk Slices S1-S3.

The engine does not perform transport or persistence.  Callers hand the
returned state and event facts back to it on the next turn.  This keeps the
walk deterministic and makes an option from a previous menu impossible to
replay into a later menu.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping, Sequence

from creation_training_authority import CREATION_TRAINING_MAX_PER_CL

from .linear_menus import (
    progression_step_expected,
    starting_kit_context,
    treasure_next_step,
    MAX_WALK_STEPS,
    BACKGROUND_ABILITY_AMOUNT_PREFIX,
    CommittedState,
    LinearMenuError,
    StepMenu,
    StepOption,
    build_step_menu,
    build_sphere_free_talent_pair_menu,
    build_sphere_route_menu,
    build_ordinary_talent_menu,
    build_sphere_priorities_menu,
    build_insight_priorities_menu,
    build_insight_occurrence_menu,
    build_asi_milestone_menu,
    build_asi_or_insight_menu,
    recorded_milestone_branch,
    MILESTONE_BRANCH_ABILITY_INCREASE,
    MILESTONE_BRANCH_INSIGHT,
    MILESTONE_BRANCHES,
    milestone_shadowed,
    _expected_count,
    _milestone_order_key,
    _milestone_rows,
    _insight_resolution,
    _parameter_abilities,
    _selection_limits,
    _decode_score_bundle,
    _proficiency_entries,
    _proficiency_values,
    _PROFICIENCY_FIELDS,
    _PROFICIENCY_SLOTS,
    _PROFICIENCY_KINDS,
    _progression_map,
    creation_training_required_gap,
    is_owner_locked,
    mandatory_completion_gaps,
    method_required_gap,
    subpath_owner_by_id,
    subpath_required_path_ids,
    owner_lock_for,
    validate_step_menu,
)
from .linear_prompt import parse_identity_response, parse_step_response


ACTION_MENU = "MENU"
ACTION_AUTOCOMMITTED = "AUTOCOMMITTED"
ACTION_COMPLETE = "COMPLETE"
ACTION_SKIPPED = "SKIPPED"
ACTION_FAILED = "FAILED"

EVENT_STEP_COMMITTED = "STEP_COMMITTED"
EVENT_STEP_AUTOCOMMITTED = "STEP_AUTOCOMMITTED"


class LinearWalkError(LinearMenuError):
    """A fail-closed error raised before changing committed state."""


def _error(code: str, message: str, *, details: Any = None) -> None:
    raise LinearWalkError(code, message, details=details, status_code=400)


def _background_ability_parts(choice_ids: Sequence[str]) -> tuple[str, int | None]:
    if len(choice_ids) not in {1, 2}:
        _error("DCC_LINEAR_BACKGROUND_ABILITY", "A Background ability option has an invalid typed shape.")
    ability = choice_ids[0]
    amount: int | None = None
    if len(choice_ids) == 2:
        token = choice_ids[1]
        if not token.startswith(BACKGROUND_ABILITY_AMOUNT_PREFIX):
            _error("DCC_LINEAR_BACKGROUND_ABILITY_AMOUNT", "A Background ability amount must use the typed amount token.")
        raw_amount = token[len(BACKGROUND_ABILITY_AMOUNT_PREFIX):]
        try:
            amount = int(raw_amount)
        except (TypeError, ValueError) as exc:
            raise LinearWalkError(
                "DCC_LINEAR_BACKGROUND_ABILITY_AMOUNT",
                "A Background ability amount must be a positive integer.",
            ) from exc
        if amount <= 0:
            _error("DCC_LINEAR_BACKGROUND_ABILITY_AMOUNT", "A Background ability amount must be a positive integer.")
    return ability, amount


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _state(value: CommittedState | Mapping[str, Any] | None) -> CommittedState:
    if isinstance(value, CommittedState):
        return value
    if not isinstance(value, Mapping):
        return CommittedState.empty()
    return CommittedState(
        by_slot=value.get("by_slot") or {},
        pairs=value.get("pairs") or (),
        ordinary_by_cl=value.get("ordinary_by_cl") or {},
        insight_occurrences=value.get("insight_occurrences") or (),
        bounded=value.get("bounded") or {},
        route_id=value.get("route_id"),
        trained_choices=value.get("trained_choices") or (),
        trained_choice_skips=value.get("trained_choice_skips") or (),
    )


def _locks(request: Any, envelope: Any) -> Mapping[str, Any]:
    for source in (_map(envelope), _map(request)):
        raw = source.get("owner_locks")
        if isinstance(raw, Mapping):
            by_slot = raw.get("by_slot")
            return by_slot if isinstance(by_slot, Mapping) else raw
    return {}


def _lock_values(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        for key in ("choice_ids", "choices", "selected", "value", "id"):
            if key in value:
                return _lock_values(value[key])
        return []
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str) and item]
    return [value] if isinstance(value, str) and value else []


def _lock_pairs(value: Any) -> list[tuple[str, str]]:
    if isinstance(value, Mapping) and isinstance(value.get("pairs"), (list, tuple)):
        value = value["pairs"]
    rows = value if isinstance(value, (list, tuple)) else [value]
    result: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        sphere_id = row.get("sphere_id")
        talent_id = row.get("talent_id")
        if isinstance(sphere_id, str) and sphere_id and isinstance(talent_id, str) and talent_id:
            result.append((sphere_id, talent_id))
    return result


def _lock_for_step(request: Any, envelope: Any, step_id: str, slot_id: str) -> Any:
    locks = _locks(request, envelope)
    if step_id in locks:
        return locks[step_id]
    if slot_id in locks:
        return locks[slot_id]
    if ":" in step_id:
        base, suffix = step_id.split(":", 1)
        value = locks.get(base)
        if isinstance(value, Mapping) and suffix in value:
            return value[suffix]
    return None


def _apply_owner_locks(request: Any, envelope: Any, state: CommittedState) -> CommittedState:
    """Pre-commit the frozen owner choices before exposing any menu."""

    result = state
    locks = _locks(request, envelope)
    # The known S1 slots are intentionally explicit.  Unknown lock keys are
    # left for a later slice rather than interpreted speculatively.
    known = (
        "path_choice",
        "subpath_choice",
        "method_choice",
        "foundation_choice",
        "foundation_initial_stage",
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
        "identity",
    )
    for key in known:
        if key not in locks or not is_owner_locked(request, envelope, key):
            continue
        value = locks[key]
        if key == "point_buy_preset":
            preset = value.get("preset") if isinstance(value, Mapping) and isinstance(value.get("preset"), Mapping) else value
            if isinstance(preset, Mapping) and "scores" in preset and "permutable_across_abilities" in preset:
                current = result.bounded.get("point_buy_preset")
                if current is not None and current != preset:
                    _error("DCC_LINEAR_OWNER_LOCK_CONFLICT", "Committed state conflicts with an owner point-buy preset lock.", details={"slot_id": key})
                if current is None:
                    result = result.with_point_buy_preset(preset)
                if preset.get("permutable_across_abilities") is not True and "ability_scores" not in result.bounded:
                    abilities = preset.get("abilities")
                    scores = preset.get("scores")
                    if isinstance(abilities, (list, tuple)) and isinstance(scores, (list, tuple)):
                        result = result.with_ability_scores(dict(zip(abilities, scores)))
            continue
        if key == "point_buy_assignment":
            scores = value.get("ability_scores", value.get("scores")) if isinstance(value, Mapping) else value
            if isinstance(scores, Mapping) and "ability_scores" not in result.bounded:
                result = result.with_ability_scores(scores)
            continue
        if key == "asi_or_insight":
            # An owner may name, per level, which printed resolution the level
            # takes (the normal ability-score increase or a Cultivation
            # Insight) without the walk asking.  ``branch``/``choice_id``/``value``
            # carry the branch name; a locked branch alone does not answer the
            # detail question the branch's own menu asks.
            rows = value if isinstance(value, Mapping) else {}
            rows = rows.get("advancement_milestone_branch_by_milestone_id", rows.get("branches", rows)) if isinstance(rows, Mapping) else {}
            if isinstance(rows, Mapping):
                existing = _map(result.bounded.get("advancement_milestone_branch_by_milestone_id"))
                for milestone_id, raw in sorted(rows.items(), key=lambda item: str(item[0])):
                    branch = raw
                    if isinstance(raw, Mapping):
                        branch = raw.get("branch", raw.get("choice_id", raw.get("value")))
                    if not isinstance(milestone_id, str) or branch not in MILESTONE_BRANCHES:
                        continue
                    prior = existing.get(milestone_id)
                    if prior is None:
                        result = result.with_milestone_branch(milestone_id, branch)
                    elif prior != branch:
                        _error("DCC_LINEAR_OWNER_LOCK_CONFLICT", "Committed state conflicts with an owner lock.", details={"slot_id": key})
            continue
        if key == "asi_milestone":
            rows = value if isinstance(value, Mapping) else {}
            rows = rows.get("ability_score_changes_by_milestone_id", rows.get("changes", rows)) if isinstance(rows, Mapping) else {}
            if isinstance(rows, Mapping):
                for milestone_id, raw in sorted(rows.items(), key=lambda item: str(item[0])):
                    if not isinstance(milestone_id, str):
                        continue
                    deltas = raw.get("deltas", raw) if isinstance(raw, Mapping) else None
                    if isinstance(deltas, Mapping) and milestone_id not in result.bounded.get("ability_score_changes_by_milestone_id", {}):
                        result = result.with_ability_score_changes(milestone_id, deltas)
            continue
        if key == "path_progression":
            rows = value if isinstance(value, Mapping) else {}
            rows = rows.get("path_progression_by_cl", rows.get("choices", rows)) if isinstance(rows, Mapping) else {}
            if isinstance(rows, Mapping):
                for cl, path_id in sorted(rows.items(), key=lambda item: str(item[0])):
                    if isinstance(path_id, str) and str(cl) not in result.bounded.get("path_progression_by_cl", {}):
                        result = result.with_path_progression(cl, path_id)
            continue
        if key in {"path_skill", "origin_skill", "background_language"}:
            field = {
                "path_skill": "path_skill_choices_by_path_id",
                "origin_skill": "origin_skill_choices_by_origin_id",
                "background_language": "background_language_choices_by_background_id",
            }[key]
            rows = value if isinstance(value, Mapping) else {}
            rows = rows.get(field, rows.get("choices", rows)) if isinstance(rows, Mapping) else {}
            if isinstance(rows, Mapping):
                for owner_id, values in sorted(rows.items(), key=lambda item: str(item[0])):
                    clean = _lock_values(values)
                    if isinstance(owner_id, str) and clean and owner_id not in result.bounded.get(field, {}):
                        result = result.with_proficiency(field, owner_id, clean)
            continue
        if key == "foundation_initial_stage":
            raw = value.get("value", value.get("stage")) if isinstance(value, Mapping) else value
            if isinstance(raw, str) and raw and "foundation_initial_stage" not in result.bounded:
                result = result.with_bounded("foundation_initial_stage", raw)
            continue
        if key == "background_ability":
            if "background_ability" not in result.bounded:
                if isinstance(value, Mapping):
                    raw = value.get("ability", value.get("value"))
                    amount = value.get("amount")
                else:
                    raw = value
                    amount = None
                if isinstance(raw, str) and raw:
                    result = result.with_bounded("background_ability", deepcopy(raw))
                    if type(amount) is int and amount > 0:
                        result = result.with_bounded("background_ability_amount", amount)
            continue
        if key == "identity":
            if "identity" not in result.bounded:
                if isinstance(value, Mapping) and "name" in value and "title" in value:
                    result = result.with_identity(str(value["name"]), str(value["title"]))
                else:
                    result = result.with_bounded("identity", deepcopy(value))
            continue
        if key == "sphere_route":
            route_id = value.get("route_id") if isinstance(value, Mapping) else value
            if isinstance(route_id, str) and result.route_id is None:
                result = result.with_route(route_id)
            continue
        if key == "sphere_free_talent_pair":
            for sphere_id, talent_id in _lock_pairs(value):
                if not any(
                    row.get("sphere_id") == sphere_id and row.get("talent_id") == talent_id
                    for row in result.pairs
                    if isinstance(row, Mapping)
                ):
                    result = result.with_pair(sphere_id, talent_id)
            continue
        if key == "ordinary_talent" and isinstance(value, Mapping):
            for cl, talent_id in sorted(value.items(), key=lambda item: str(item[0])):
                if isinstance(talent_id, str) and talent_id:
                    result = result.with_ordinary(cl, talent_id)
            continue
        if key == "insight_occurrence":
            rows = value if isinstance(value, (list, tuple)) else [value]
            for occurrence in rows:
                if isinstance(occurrence, Mapping) and isinstance(occurrence.get("insight_id"), str) and isinstance(occurrence.get("milestone_id"), str):
                    if not any(row.get("milestone_id") == occurrence["milestone_id"] for row in result.insight_occurrences if isinstance(row, Mapping)):
                        result = result.with_insight_occurrence(occurrence)
            continue
        if key == "subpath_choice" and isinstance(value, Mapping):
            # Some frozen envelopes retain the path-keyed form.  Keep those
            # IDs in aggregate selection order; the per-path menu remains
            # hidden because the base slot is explicitly owner locked.
            nested_values: list[str] = []
            for path_id in sorted(value):
                nested_values.extend(_lock_values(value[path_id]))
            values = nested_values
        else:
            values = _lock_values(value)
        if not values:
            # An explicit empty lock still hides the slot from the model.  A
            # marker in bounded state prevents a repeated pre-commit pass from
            # changing the hash while preserving the slot's empty selection.
            if key not in result.by_slot:
                result = result.with_slot(key, [])
            continue
        existing = list(result.by_slot.get(key, []))
        if key == "subpath_choice" and existing:
            # A Subpath lock is per Path.  Replay rebuilds state from committed
            # events alone, so the owner's Subpaths are merged back in here;
            # the walk may legally have added another selected Path's Subpath
            # beside them.  Only a committed Subpath that displaces the
            # owner's choice for the same Path is a conflict.
            owners = subpath_owner_by_id(request, envelope)
            locked_owners = {owners[value] for value in values if value in owners}
            replaced = [value for value in existing if value not in values and owners.get(value) in locked_owners]
            if replaced:
                _error("DCC_LINEAR_OWNER_LOCK_CONFLICT", "Committed state conflicts with an owner lock.", details={"slot_id": key, "replaced_owner_choice_ids": replaced})
            merged = list(values) + [value for value in existing if value not in values]
            if merged != existing:
                result = result.with_slot(key, merged)
            continue
        if existing and existing != values:
            _error("DCC_LINEAR_OWNER_LOCK_CONFLICT", "Committed state conflicts with an owner lock.", details={"slot_id": key})
        if existing != values:
            result = result.with_slot(key, values)
    # Indexed S2 locks are valid owner decisions as well as the base-slot
    # forms above.  Apply them before descriptor construction so the model
    # never sees a menu for an already-owned pair, CL Talent, or occurrence.
    for key in sorted(locks):
        if key.startswith("sphere_free_talent_pair:") and key != "sphere_free_talent_pair":
            for sphere_id, talent_id in _lock_pairs(locks[key]):
                if not any(
                    row.get("sphere_id") == sphere_id and row.get("talent_id") == talent_id
                    for row in result.pairs
                    if isinstance(row, Mapping)
                ):
                    result = result.with_pair(sphere_id, talent_id)
        elif key.startswith("ordinary_talent:") and key != "ordinary_talent":
            cl = key.split(":", 1)[1]
            value = locks[key]
            if isinstance(value, Mapping):
                value = value.get("talent_id", value.get("choice_id", value.get("id")))
            values = _lock_values(value)
            if values:
                result = result.with_ordinary(cl, values[0])
        elif key.startswith("insight_occurrence:") and key != "insight_occurrence":
            suffix = key.split(":", 1)[1]
            value = locks[key]
            if suffix.endswith(":ability"):
                milestone_id = suffix[:-len(":ability")]
                ability = value.get("ability") if isinstance(value, Mapping) else value
                if not isinstance(ability, str) and isinstance(value, Mapping):
                    parameters = value.get("parameters")
                    ability = parameters.get("ability") if isinstance(parameters, Mapping) else value.get("choice_id", value.get("id", value.get("value")))
                if isinstance(ability, str) and ability:
                    existing = next(
                        (row for row in result.insight_occurrences if isinstance(row, Mapping) and row.get("milestone_id") == milestone_id),
                        None,
                    )
                    if isinstance(existing, Mapping):
                        parameters = existing.get("parameters")
                        prior = parameters.get("ability") if isinstance(parameters, Mapping) else None
                        if prior is None:
                            result = result.with_insight_ability(milestone_id, ability)
                        elif prior != ability:
                            _error("DCC_LINEAR_OWNER_LOCK_CONFLICT", "Committed state conflicts with an owner lock.", details={"slot_id": key})
                continue
            milestone_id = suffix
            if isinstance(value, Mapping):
                insight_id = value.get("insight_id", value.get("choice_id", value.get("id")))
                if isinstance(insight_id, str) and insight_id:
                    occurrence = {"insight_id": insight_id, "milestone_id": milestone_id}
                    if isinstance(value.get("parameters"), Mapping):
                        occurrence["parameters"] = deepcopy(dict(value["parameters"]))
                    if not any(
                        row.get("milestone_id") == milestone_id
                        for row in result.insight_occurrences
                        if isinstance(row, Mapping)
                    ):
                        result = result.with_insight_occurrence(occurrence)
        elif key.startswith("asi_or_insight:") and key != "asi_or_insight":
            milestone_id = key.split(":", 1)[1]
            value = locks[key]
            branch = value.get("branch", value.get("choice_id", value.get("value"))) if isinstance(value, Mapping) else value
            existing = _map(result.bounded.get("advancement_milestone_branch_by_milestone_id"))
            if branch in MILESTONE_BRANCHES and existing.get(milestone_id) != branch:
                result = result.with_milestone_branch(milestone_id, branch)
        elif key.startswith("asi_milestone:") and key != "asi_milestone":
            milestone_id = key.split(":", 1)[1]
            value = locks[key]
            deltas = value.get("deltas", value.get("changes", value)) if isinstance(value, Mapping) else None
            existing = _map(result.bounded.get("ability_score_changes_by_milestone_id"))
            if isinstance(deltas, Mapping) and milestone_id not in existing:
                result = result.with_ability_score_changes(milestone_id, deltas)
        elif key.startswith("path_progression:") and key != "path_progression":
            cl = key.split(":", 1)[1]
            value = locks[key]
            path_id = value.get("path_id", value.get("choice_id", value.get("id", value.get("value")))) if isinstance(value, Mapping) else value
            existing = _map(result.bounded.get("path_progression_by_cl"))
            if isinstance(path_id, str) and cl not in existing:
                result = result.with_path_progression(cl, path_id)
        elif any(key.startswith(f"{kind}:") for kind in ("path_skill", "origin_skill", "background_language")):
            kind = key.split(":", 1)[0]
            suffix = key.split(":", 1)[1]
            owner_id = suffix.rsplit(":", 1)[0] if ":" in suffix and suffix.rsplit(":", 1)[1].isdigit() else suffix
            field = {
                "path_skill": "path_skill_choices_by_path_id",
                "origin_skill": "origin_skill_choices_by_origin_id",
                "background_language": "background_language_choices_by_background_id",
            }[kind]
            values = _lock_values(locks[key])
            existing = _map(result.bounded.get(field))
            if isinstance(owner_id, str) and values and owner_id not in existing:
                result = result.with_proficiency(field, owner_id, values)
    return result


def _events(value: Sequence[Mapping[str, Any]] | None) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    return tuple(row for row in value if isinstance(row, Mapping))


def _event_step_id(event: Mapping[str, Any]) -> str | None:
    for key in ("step_id", "step", "subject"):
        if isinstance(event.get(key), str):
            return event[key]
    payload = event.get("payload")
    return payload.get("step_id") if isinstance(payload, Mapping) and isinstance(payload.get("step_id"), str) else None


def _event_type(event: Mapping[str, Any]) -> str | None:
    for key in ("event_type", "type"):
        if isinstance(event.get(key), str):
            return event[key]
    return None


def _done_steps(events: Sequence[Mapping[str, Any]]) -> set[str]:
    return {
        step_id
        for event in events
        if _event_type(event) in {EVENT_STEP_COMMITTED, EVENT_STEP_AUTOCOMMITTED}
        for step_id in [_event_step_id(event)]
        if step_id
    }


def _with_forged_design_decision(state: CommittedState, step_id: str, choice_ids: Sequence[str]) -> CommittedState:
    from character_creation.constructed_arts.explicit_forging import concepts_for_design_ids

    selected = list(state.bounded.get("forged_design_ids") or [])
    if state.bounded.get("forged_design_done") is True or step_id != f"forged_design:{len(selected) + 1}" or len(choice_ids) > 1:
        _error("DCC_LINEAR_FORGED_DESIGN_ORDER", "Forge decisions must be contiguous and cannot follow the explicit finish decision.")
    if not choice_ids:
        return state.with_bounded("forged_design_done", True)
    selected.extend(choice_ids)
    concepts_for_design_ids(selected)
    return state.with_bounded("forged_design_ids", selected)


def _with_starting_kit_decision(state: CommittedState, step_id: str, choice_ids: Sequence[str]) -> CommittedState:
    """Record the Path kit option or one closed kit pick under ``bounded.starting_kit``."""

    if len(choice_ids) != 1 or not isinstance(choice_ids[0], str):
        _error("DCC_LINEAR_STARTING_KIT", "A starting-kit step commits exactly one value.")
    kit = deepcopy(dict(_map(state.bounded.get("starting_kit"))))
    if step_id == "starting_kit_option":
        if choice_ids[0] not in {"option_a", "option_b"} or kit.get("path_option"):
            _error("DCC_LINEAR_STARTING_KIT", "The Path kit option is committed once, as option_a or option_b.")
        # A pre-pinned Background choice can supply the guaranteed kit budget.
        # Preserve it when the player commits the Path's A/B option.
        return state.with_bounded("starting_kit", {"path_option": choice_ids[0], "picks": dict(_map(kit.get("picks")))})
    choice_id, separator, raw_index = choice_ids[0].rpartition("=")
    picks = dict(_map(kit.get("picks")))
    if (not kit.get("path_option") or not separator or not raw_index.isdigit()
            or step_id != f"starting_kit_choice:{choice_id}" or choice_id in picks):
        _error("DCC_LINEAR_STARTING_KIT", "A starting-kit pick must answer its own open choice once.")
    picks[choice_id] = int(raw_index)
    kit["picks"] = picks
    return state.with_bounded("starting_kit", kit)


_TREASURE_BUILDS = {
    "treasure_weapon": ("treasure_weapon", "enchantment_ids"),
    "treasure_armor": ("treasure_armor", "enhancement_ids"),
}
_TREASURE_PURCHASES = {"treasure_wondrous": "treasure_wondrous", "treasure_consumable": "treasure_consumables"}


def _with_treasure_decision(state: CommittedState, step_id: str, choice_ids: Sequence[str]) -> CommittedState:
    """Record one treasure step under ``bounded``: a built item's chassis, material or
    enhancement (``treasure_weapon`` / ``treasure_armor``), or one purchase
    (``treasure_wondrous`` / ``treasure_consumables``).  An empty commit finishes
    the item or the purchases, and only after at least one pick."""

    kind, _, index = step_id.partition(":")
    for prefix, (field, list_key) in _TREASURE_BUILDS.items():
        if not kind.startswith(prefix + "_"):
            continue
        item = deepcopy(dict(_map(state.bounded.get(field))))
        part = kind[len(prefix) + 1:]
        if item.get("done"):
            _error("DCC_LINEAR_TREASURE", "This treasure is already finished.")
        if part in {"enchantment", "enhancement"}:
            chosen = list(item.get(list_key) or [])
            if not item.get("material_id") or index != str(len(chosen) + 1):
                _error("DCC_LINEAR_TREASURE", "Enhancements follow the material, one step at a time.")
            if not choice_ids:
                if not chosen:
                    _error("DCC_LINEAR_TREASURE", "A treasure carries at least one enhancement before it is finished.")
                item["done"] = True
                return state.with_bounded(field, item)
            if len(choice_ids) != 1 or not isinstance(choice_ids[0], str) or choice_ids[0] in chosen:
                _error("DCC_LINEAR_TREASURE", "An enhancement step commits one new enhancement.")
            item[list_key] = chosen + [choice_ids[0]]
            return state.with_bounded(field, item)
        if len(choice_ids) != 1 or not isinstance(choice_ids[0], str):
            _error("DCC_LINEAR_TREASURE", "A treasure step commits exactly one value.")
        if part == "chassis" and not item.get("chassis_id"):
            return state.with_bounded(field, {"chassis_id": choice_ids[0], list_key: []})
        if part == "material" and item.get("chassis_id") and not item.get("material_id"):
            item["material_id"] = choice_ids[0]
            return state.with_bounded(field, item)
        _error("DCC_LINEAR_TREASURE", "Treasure steps run chassis, material, then enhancements.")
    field = _TREASURE_PURCHASES.get(kind)
    if field is None:
        _error("DCC_LINEAR_TREASURE", "Unknown treasure step.")
    purchases = deepcopy(dict(_map(state.bounded.get(field))))
    bought = list(purchases.get("ids") or [])
    if purchases.get("done") or index != str(len(bought) + 1):
        _error("DCC_LINEAR_TREASURE", "Purchases are made one step at a time until finished.")
    if not choice_ids:
        if not bought:
            _error("DCC_LINEAR_TREASURE", "At least one purchase comes before finishing.")
        return state.with_bounded(field, {"ids": bought, "done": True})
    if len(choice_ids) != 1 or not isinstance(choice_ids[0], str) or choice_ids[0] in bought:
        _error("DCC_LINEAR_TREASURE", "A purchase step buys one new item.")
    return state.with_bounded(field, {"ids": bought + [choice_ids[0]]})


def replay_committed_state(events: Sequence[Mapping[str, Any]] | None, initial: CommittedState | Mapping[str, Any] | None = None, *, request=None, envelope=None) -> CommittedState:
    """Replay simple step facts without trusting any display text."""

    result = _state(initial)
    for event in _events(events):
        event_type = _event_type(event)
        if event_type not in {EVENT_STEP_COMMITTED, EVENT_STEP_AUTOCOMMITTED}:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else event
        step_id = _event_step_id(event)
        if not step_id:
            continue
        choice_ids = payload.get("choice_ids", payload.get("committed_choice_ids"))
        if not isinstance(choice_ids, (list, tuple)):
            continue
        ids = [value for value in choice_ids if isinstance(value, str)]
        if step_id.startswith("forged_design:"):
            from character_creation.constructed_arts.explicit_forging import required_design_ids
            if required_design_ids(envelope or {}, request):
                menu = build_step_menu(request, envelope, result, step_id=step_id)
                if menu is None or not any(list(option.choice_ids) == list(choice_ids) for option in menu.options):
                    _error("DCC_REQUIRED_FORGED_DESIGNS_INCOMPLETE", "A committed Forge decision was not legal under the frozen requirement.")
            result = _with_forged_design_decision(result, step_id, choice_ids)
            continue
        if step_id == "starting_kit_option" or step_id.startswith("starting_kit_choice:"):
            result = _with_starting_kit_decision(result, step_id, ids)
            continue
        if step_id.startswith("treasure_"):
            result = _with_treasure_decision(result, step_id, ids)
            continue
        if step_id == "identity":
            continue
        if step_id.startswith("sphere_free_talent_pair:"):
            if len(ids) >= 2:
                result = result.with_pair(ids[0], ids[1])
            continue
        if step_id == "sphere_route":
            route_id = payload.get("route_id") if isinstance(payload.get("route_id"), str) else (ids[0] if ids else None)
            if route_id:
                result = result.with_route(route_id)
            continue
        if step_id.startswith("ordinary_talent:"):
            cl = step_id.split(":", 1)[1]
            if ids:
                result = result.with_ordinary(cl, ids[0])
            continue
        if step_id.startswith("creation_training:"):
            parts = step_id.split(":")
            if len(parts) == 3:
                try:
                    cl = int(parts[1])
                    slot = int(parts[2])
                except (TypeError, ValueError):
                    continue
                if not ids:
                    result = result.with_trained_choice_skip(cl)
                    continue
                if len(ids) == 2:
                    result = result.with_trained_choice({
                        "cl": cl,
                        "slot": slot,
                        "choice_type": "new_sphere",
                        "record_id": ids[0],
                        "bonus_talent_id": ids[1],
                    })
                elif len(ids) == 1:
                    result = result.with_trained_choice({
                        "cl": cl,
                        "slot": slot,
                        "choice_type": "known_sphere_talent",
                        "record_id": ids[0],
                    })
            continue
        if step_id.startswith("insight_occurrence:"):
            suffix = step_id.split(":", 1)[1]
            if suffix.endswith(":ability"):
                milestone_id = suffix[:-len(":ability")]
                parameters = payload.get("parameters")
                ability = parameters.get("ability") if isinstance(parameters, Mapping) else (ids[0] if ids else None)
                if isinstance(ability, str) and ability:
                    result = result.with_insight_ability(milestone_id, ability)
                continue
            if ids:
                occurrence: dict[str, Any] = {"insight_id": ids[0], "milestone_id": suffix}
                parameters = payload.get("parameters")
                if isinstance(parameters, Mapping):
                    occurrence["parameters"] = deepcopy(dict(parameters))
                result = result.with_insight_occurrence(occurrence)
            continue
        if step_id == "point_buy_preset":
            mode = None
            parsed: dict[str, int] | None = None
            for candidate_mode in ("permutable", "fixed"):
                parsed = _decode_score_bundle(ids, "point_buy_preset", mode=candidate_mode)
                if parsed is not None:
                    mode = candidate_mode
                    break
            if parsed is not None and mode is not None:
                abilities = list(parsed)
                result = result.with_point_buy_preset({
                    "abilities": abilities,
                    "scores": [parsed[ability] for ability in abilities],
                    "permutable_across_abilities": mode == "permutable",
                })
                if mode == "fixed":
                    result = result.with_ability_scores(parsed)
            continue
        if step_id == "point_buy_assignment":
            parsed = _decode_score_bundle(ids, "point_buy_assignment")
            if parsed is not None:
                result = result.with_ability_scores(parsed)
            continue
        if step_id.startswith("asi_or_insight:"):
            milestone_id = step_id.split(":", 1)[1]
            if len(ids) == 1 and ids[0] in MILESTONE_BRANCHES:
                result = result.with_milestone_branch(milestone_id, ids[0])
            continue
        if step_id.startswith("asi_milestone:"):
            milestone_id = step_id.split(":", 1)[1]
            deltas: dict[str, int] = {}
            for token in ids:
                parts = token.split(":")
                if len(parts) != 3 or parts[0] != "asi" or parts[1] in deltas:
                    deltas = {}
                    break
                try:
                    deltas[parts[1]] = int(parts[2])
                except (TypeError, ValueError):
                    deltas = {}
                    break
            if deltas:
                result = result.with_ability_score_changes(milestone_id, deltas)
            continue
        if step_id.startswith("path_progression:"):
            cl = step_id.split(":", 1)[1]
            if ids:
                result = result.with_path_progression(cl, ids[0])
            continue
        if step_id.startswith(("path_skill:", "origin_skill:", "background_language:")):
            kind = step_id.split(":", 1)[0]
            suffix = step_id.split(":", 1)[1]
            owner_id = suffix.rsplit(":", 1)[0] if ":" in suffix and suffix.rsplit(":", 1)[1].isdigit() else suffix
            field = {
                "path_skill": "path_skill_choices_by_path_id",
                "origin_skill": "origin_skill_choices_by_origin_id",
                "background_language": "background_language_choices_by_background_id",
            }[kind]
            if ids:
                prior_map = _map(result.bounded.get(field))
                prior = prior_map.get(owner_id) if isinstance(prior_map.get(owner_id), (list, tuple)) else []
                result = result.with_proficiency(field, owner_id, [*prior, ids[0]])
            continue
        if step_id == "foundation_initial_stage":
            if len(ids) == 1:
                result = result.with_bounded("foundation_initial_stage", ids[0])
            continue
        if step_id == "background_ability":
            if ids:
                ability, amount = _background_ability_parts(ids)
                result = result.with_bounded("background_ability", ability)
                if amount is not None:
                    result = result.with_bounded("background_ability_amount", amount)
            continue
        slot_id = step_id.split(":", 1)[0]
        if ids:
            current = list(result.by_slot.get(slot_id, []))
            result = result.with_slot(slot_id, current + [value for value in ids if value not in current])
    return result


def _selected_count(state: CommittedState, slot_id: str) -> int:
    return len(state.by_slot.get(slot_id, []))


def _has_identity(state: CommittedState) -> bool:
    value = state.bounded.get("identity")
    return isinstance(value, Mapping) and isinstance(value.get("name"), str) and isinstance(value.get("title"), str)


def _subpath_complete(request: Any, envelope: Any, state: CommittedState, path_id: str) -> bool:
    # The builder filters by owning_path_id.  Looking at its legal IDs keeps
    # this completion test authority-based and works for the flat and indexed
    # envelope representations.
    menu = build_step_menu(request, envelope, state, step_id=f"subpath_choice:{path_id}", ordinal=1)
    if menu is None:
        limits = _map(_map(envelope).get("selection_limits_by_slot"))
        row = _map(limits.get("subpath_choice"))
        return not bool(row.get("final_min", 0))
    legal = {choice_id for option in menu.options for choice_id in option.choice_ids}
    return bool(legal & set(state.by_slot.get("subpath_choice", [])))


def _subpath_required(request: Any, envelope: Any) -> bool:
    value = _map(envelope).get("subpath_choice_required", _map(request).get("subpath_choice_required"))
    if not isinstance(value, bool):
        value = _map(_map(envelope).get("response_contract")).get("subpath_choice_required", value)
    if not isinstance(value, bool):
        value = _map(_map(request).get("response_contract")).get("subpath_choice_required", value)
    if isinstance(value, bool):
        return value
    value = _map(envelope).get("subpath_required", _map(request).get("subpath_required"))
    return value is True


def _step_descriptors(request: Any, envelope: Any, state: CommittedState) -> list[tuple[str, str, str]]:
    """Return the deterministic S1-S3 order from frozen typed authority."""

    descriptors: list[tuple[str, str, str]] = []
    # The character is conceived first: the identity step (name, title and a
    # one-sentence concept) opens the walk so every later choice is made for
    # that concept instead of at random.
    if not _has_identity(state):
        descriptors.append(("identity", "identity", "identity"))
    paths = list(state.by_slot.get("path_choice", []))
    # Repeated path picks use one opaque menu per selection.
    limits = _map(_map(envelope).get("selection_limits_by_slot"))
    if not limits:
        limits = _map(_map(request).get("selection_limits_by_slot"))
    path_limits = _map(limits.get("path_choice"))
    path_max = path_limits.get("final_max", path_limits.get("max_choices", 3))
    path_max = path_max if type(path_max) is int and path_max > 0 else 3
    # Most characters walk one Path: the walk offers a single Path unless the
    # owner locked more (owner ruling 2026-09-23).
    owner_paths = _lock_values(owner_lock_for(request, envelope, "path_choice")) if is_owner_locked(request, envelope, "path_choice") else []
    path_max = min(path_max, max(1, len(owner_paths)))
    if len(paths) < path_max:
        descriptors.append((f"path_choice:{len(paths) + 1}", "path_choice", "path_choice"))
    # Subpaths are evaluated in canonical path order and only after all path
    # picks currently present have been committed.
    if paths:
        for path_id in sorted(set(paths)):
            if not _subpath_complete(request, envelope, state, path_id):
                # The descriptor's lock key is the per-Path step: an owner
                # lock on another Path's Subpath must not silence this one.
                descriptors.append((f"subpath_choice:{path_id}", "subpath_choice", f"subpath_choice:{path_id}"))
                break
    if paths and not state.by_slot.get("method_choice"):
        descriptors.append(("method_choice", "method_choice", "method_choice"))
    # A Foundation does not depend on a Method: the menu offers nothing below
    # CL 5 and requires a pick at CL 5 and above, filtering by Method
    # compatibility only when a Method was committed.  Gating the step on a
    # committed Method silently dropped the Foundation whenever the Method was
    # deferred (a CL 10 build reached review with no Foundation).
    if paths and not state.by_slot.get("foundation_choice"):
        descriptors.append(("foundation_choice", "foundation_choice", "foundation_choice"))
    if (state.by_slot.get("foundation_choice") and "foundation_initial_stage" not in state.bounded
            and build_step_menu(request, envelope, state, step_id="foundation_initial_stage", ordinal=1) is not None):
        descriptors.append(("foundation_initial_stage", "foundation_initial_stage", "foundation_initial_stage"))
    if not state.by_slot.get("background_choice"):
        descriptors.append(("background_choice", "background_choice", "background_choice"))
    if state.by_slot.get("background_choice") and not state.by_slot.get("background_sphere_choice"):
        descriptors.append(("background_sphere_choice", "background_sphere_choice", "background_sphere_choice"))
    if state.by_slot.get("background_sphere_choice") and not state.by_slot.get("background_talent_choice"):
        descriptors.append(("background_talent_choice", "background_talent_choice", "background_talent_choice"))
    if state.by_slot.get("background_choice") and "background_ability" not in state.bounded:
        descriptors.append(("background_ability", "background_ability", "background_ability"))
    if state.by_slot.get("background_choice") and not state.by_slot.get("origin_insight_choice"):
        descriptors.append(("origin_insight_choice", "origin_insight_choice", "origin_insight_choice"))
    # Select all free Spheres before assigning starting scores: their printed
    # attack/save formulas may use a different ability from the Path key.
    # Existing scores (including owner locks and resumed walks) stay intact.
    expected_pairs = _expected_count(request, envelope, "sphere_free_talent_pairs")
    bounded = _map(state.bounded)
    if len(state.pairs) >= expected_pairs and not isinstance(bounded.get("ability_scores"), Mapping):
        if not isinstance(bounded.get("point_buy_preset"), Mapping):
            if build_step_menu(request, envelope, state, step_id="point_buy_preset", ordinal=1) is not None:
                descriptors.append(("point_buy_preset", "point_buy_preset", "point_buy_preset"))
        elif bounded.get("point_buy_preset", {}).get("permutable_across_abilities") is True:
            if build_step_menu(request, envelope, state, step_id="point_buy_assignment", ordinal=1) is not None:
                descriptors.append(("point_buy_assignment", "point_buy_assignment", "point_buy_assignment"))
    if expected_pairs and len(state.pairs) < expected_pairs:
        descriptors.append((f"sphere_free_talent_pair:{len(state.pairs) + 1}", "sphere_free_talent_pair", "sphere_free_talent_pair"))
    elif expected_pairs and state.route_id is None and build_sphere_route_menu(request, envelope, state) is not None:
        # A server route script exists only for the sample Spheres it
        # shortlisted.  An owner-priority Sphere outside that sample has no
        # route; its level talents come from the typed rows below instead.
        descriptors.append(("sphere_route", "sphere_route", "sphere_route"))
    else:
        # Newer frozen envelopes name this capacity as ordinary_talent_count
        # and publish the typed advancement rows directly, without the
        # model-facing route projection.  The menu builder applies the exact
        # typed row predicate in that no-route case.
        creation_contract = _map(envelope).get("creation_training_contract")
        if not isinstance(creation_contract, Mapping):
            creation_authority = _map(_map(envelope).get("complete_character_source_authority"))
            creation_contract = creation_authority.get("creation_training_contract")
        expected_ordinary = _expected_count(request, envelope, "ordinary_talent_ids")
        # Training and ordinary Talents share one causal timeline.  A CL's
        # constructed-training slots are committed before that CL's ordinary
        # Talent, while the next CL cannot borrow either lane from the future.
        # Emit only the next descriptor so the walk cannot batch all training
        # CLs ahead of the ordinary lane.
        if isinstance(creation_contract, Mapping) and type(creation_contract.get("target_cl")) is int:
            target_cl = creation_contract["target_cl"]
            committed_training = [
                row for row in state.trained_choices
                if isinstance(row, Mapping) and type(row.get("cl")) is int and row.get("cl") >= 1
            ]
            for cl in range(1, max(target_cl, expected_ordinary) + 1):
                if cl <= target_cl and cl not in state.trained_choice_skips:
                    count = sum(1 for row in committed_training if row.get("cl") == cl)
                    if count < CREATION_TRAINING_MAX_PER_CL:
                        descriptors.append((f"creation_training:{cl}:{count + 1}", "creation_training", f"creation_training:{cl}"))
                        break
                if cl <= expected_ordinary and str(cl) not in state.ordinary_by_cl:
                    descriptors.append((f"ordinary_talent:{cl}", "ordinary_talent", f"ordinary_talent:{cl}"))
                    break
        else:
            for cl in range(1, expected_ordinary + 1):
                if str(cl) not in state.ordinary_by_cl:
                    descriptors.append((f"ordinary_talent:{cl}", "ordinary_talent", f"ordinary_talent:{cl}"))
                    break
        if expected_ordinary and len(state.ordinary_by_cl) >= expected_ordinary and not state.by_slot.get("sphere_priorities"):
            descriptors.append(("sphere_priorities", "sphere_priorities", "sphere_priorities"))
    _insight_min, insight_max, _ = _selection_limits(
        request,
        envelope,
        "insight_priorities",
        default_min=0,
        default_max=1,
    )
    if len(state.by_slot.get("insight_priorities", [])) < insight_max:
        descriptors.append((f"insight_priorities:{len(state.by_slot.get('insight_priorities', [])) + 1}", "insight_priorities", "insight_priorities"))
    selected_paths = set(state.by_slot.get("path_choice", []))
    for milestone_id, row in sorted(_milestone_rows(request, envelope), key=lambda item: _milestone_order_key(request, envelope, item[0], item[1])):
        if not isinstance(row.get("path_id"), str) or row["path_id"] not in selected_paths:
            continue
        # One advancement milestone per level: the other Path's copy at the
        # same CL is shadowed once a representative is known.
        if milestone_shadowed(request, envelope, state, row):
            continue
        insight = _insight_resolution(request, envelope, row, milestone_id)
        if insight is None:
            continue
        # Dual-kind milestones resolve exactly once: an ASI commit closes the
        # Insight occurrence descriptor, mirroring the validator.
        if milestone_id in _map(_map(state.bounded).get("ability_score_changes_by_milestone_id")):
            continue
        existing = next(
            (occurrence for occurrence in state.insight_occurrences if isinstance(occurrence, Mapping) and occurrence.get("milestone_id") == milestone_id),
            None,
        )
        base_step_id = f"insight_occurrence:{milestone_id}"
        if existing is None:
            # The printed level milestone is a choice between the normal
            # increase and a Cultivation Insight, so an unresolved level that
            # legally offers both is asked which one it takes before either
            # branch's detail menu.
            branch = recorded_milestone_branch(state, milestone_id)
            if branch == MILESTONE_BRANCH_ABILITY_INCREASE:
                continue
            if branch is None:
                if build_asi_or_insight_menu(request, envelope, state, milestone_id=milestone_id, ordinal=1) is not None:
                    descriptors.append((f"asi_or_insight:{milestone_id}", "asi_or_insight", f"asi_or_insight:{milestone_id}"))
                    continue
                if build_asi_milestone_menu(request, envelope, state, milestone_id=milestone_id, ordinal=1) is not None:
                    # Both printed resolutions are legal but the branch
                    # question itself is owner-locked; the printed rule lists
                    # the normal increase first, so that is the one asked.
                    continue
            descriptors.append((base_step_id, "insight_occurrence", base_step_id))
            continue
        selected_insight_id = existing.get("insight_id") if isinstance(existing, Mapping) else None
        parameters_by_insight_id = insight.get("parameters_by_insight_id")
        parameter = parameters_by_insight_id.get(selected_insight_id) if isinstance(parameters_by_insight_id, Mapping) and isinstance(selected_insight_id, str) else None
        if not _parameter_abilities(parameter):
            continue
        existing_parameters = existing.get("parameters") if isinstance(existing, Mapping) else None
        if isinstance(existing_parameters, Mapping) and isinstance(existing_parameters.get("ability"), str) and existing_parameters.get("ability"):
            continue
        # The follow-up carries its own step id so that an owner lock on the
        # occurrence itself (which already answered "which Insight") does not
        # also close the printed +1 ability question the owner has not answered.
        descriptors.append((f"{base_step_id}:ability", "insight_occurrence", f"{base_step_id}:ability"))
    # S3 advancement resolutions follow all S2 Insight occurrences.  The
    # menu builder performs the same applicability and contract checks, so a
    # malformed/missing typed rule simply contributes no descriptor.  Every
    # Insight's printed +1 ability is resolved before any increase, so an
    # increase is never offered a score a later Insight has already spent past
    # the cap.
    for milestone_id, row in sorted(_milestone_rows(request, envelope), key=lambda item: _milestone_order_key(request, envelope, item[0], item[1])):
        if any(
            isinstance(occurrence, Mapping) and occurrence.get("milestone_id") == milestone_id
            for occurrence in state.insight_occurrences
        ):
            continue
        if recorded_milestone_branch(state, milestone_id) == MILESTONE_BRANCH_INSIGHT:
            continue
        if build_asi_milestone_menu(request, envelope, state, milestone_id=milestone_id, ordinal=1) is not None:
            descriptors.append((f"asi_milestone:{milestone_id}", "asi_milestone", f"asi_milestone:{milestone_id}"))
    # Path progression is only a choice at ambiguous CLs.  Keep exact
    # contract keys and deterministic order; the builder filters singleton
    # and already committed maps.
    progression = _progression_map(request, envelope)
    # Numeric CL order: the forced-progression rule in the menu builder
    # counts the CLs still ahead of the current one.  Descriptors are listed
    # without building their menus: each progression menu runs a completion
    # search, and ``next_step`` builds the one it reaches (a ``None`` menu at
    # an unambiguous CL is skipped there).
    for raw_cl in sorted(progression, key=lambda value: (0, int(str(value))) if str(value).isdigit() else (1, 0)):
        cl = str(raw_cl)
        if progression_step_expected(request, envelope, state, cl):
            descriptors.append((f"path_progression:{cl}", "path_progression", f"path_progression:{cl}"))
    # Once every progression CL is fixed, a Path that reaches its Subpath
    # selection level must hold a Subpath (the Stage 2 Path milestone).  The
    # early optional Subpath step may have been declined; this required step
    # has its own ID and offers no none option.
    for path_id in subpath_required_path_ids(request, envelope, state):
        step_id = f"subpath_choice:{path_id}:required"
        descriptors.append((step_id, "subpath_choice", step_id))
    # Starting proficiency maps are keyed by the exact selected owner ID.
    # Each required value is a distinct 1/1 step, with a stable numeric
    # suffix after the first pick.
    for field in _PROFICIENCY_FIELDS:
        slot = _PROFICIENCY_SLOTS[field]
        kind = _PROFICIENCY_KINDS[field]
        owners = sorted(set(state.by_slot.get(slot, [])))
        entries = _proficiency_entries(request, envelope, field)
        bounded_values = _map(bounded.get(field))
        for owner_id in owners:
            entry = entries.get(owner_id) if isinstance(entries, Mapping) else None
            if not isinstance(entry, Mapping):
                continue
            _allowed_values, required = _proficiency_values(entry, field)
            chosen = bounded_values.get(owner_id) if isinstance(bounded_values.get(owner_id), (list, tuple)) else []
            for index in range(len(chosen) + 1, required + 1):
                step_id = f"{kind}:{owner_id}" + (f":{index}" if index > 1 else "")
                descriptors.append((step_id, kind, f"{kind}:{owner_id}"))
    # Starting kit (5.5e style): the Path kit option, then each closed choice of
    # the printed Background kit and the Path kit, one menu at a time.
    kit_context = starting_kit_context(state)
    if kit_context is not None:
        kit_background_id, kit_path_id, kit = kit_context
        if not kit.get("path_option"):
            descriptors.append(("starting_kit_option", "starting_kit_option", "starting_kit_option"))
        else:
            from factory_authoring.starting_kits import choice_menus
            kit_picks = _map(kit.get("picks"))
            for kit_menu in choice_menus(kit_background_id, kit_path_id, kit["path_option"]):
                if kit_menu["choice_id"] not in kit_picks:
                    kit_step_id = f"starting_kit_choice:{kit_menu['choice_id']}"
                    descriptors.append((kit_step_id, "starting_kit_choice", kit_step_id))
                    break
    # Treasures (Item Book Chapters 2-5): weapon, armour, Wondrous Treasures
    # and consumables, one closed menu at a time.
    treasure_step = treasure_next_step(request, envelope, state)
    if treasure_step is not None:
        descriptors.append((treasure_step, treasure_step.split(":", 1)[0], treasure_step))
    item_limits = _map(limits.get("item_priorities"))
    item_max = item_limits.get("final_max", item_limits.get("max_choices", 1))
    item_max = item_max if type(item_max) is int and item_max > 0 else 1
    if len(state.by_slot.get("item_priorities", [])) < item_max:
        descriptors.append((f"item_priorities:{len(state.by_slot.get('item_priorities', [])) + 1}", "item_priorities", "item_priorities"))
    from character_creation.constructed_arts.explicit_forging import has_explicit_forging_contract, validate_required_design_selection
    validate_required_design_selection(envelope, state.bounded.get("forged_design_ids") or [], complete=state.bounded.get("forged_design_done") is True, request=request)
    if has_explicit_forging_contract(envelope) and state.bounded.get("forged_design_done") is not True:
        index = len(state.bounded.get("forged_design_ids") or []) + 1
        descriptors.append((f"forged_design:{index}", "forged_design", "forged_design"))
    return descriptors


@dataclass(frozen=True)
class WalkStep:
    """The engine's next deterministic action."""

    step_id: str
    step_kind: str
    ordinal: int
    action: str
    menu: StepMenu | None
    committed: CommittedState
    reason: str = ""
    event: Mapping[str, Any] | None = None

    @property
    def options(self) -> tuple[StepOption, ...]:
        return self.menu.options if self.menu is not None else ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_kind": self.step_kind,
            "ordinal": self.ordinal,
            "action": self.action,
            "menu": self.menu.to_dict() if self.menu is not None else None,
            "committed": self.committed.to_dict(),
            "reason": self.reason,
            "event": deepcopy(dict(self.event)) if isinstance(self.event, Mapping) else None,
        }


def next_step(
    request: Mapping[str, Any] | None,
    envelope: Mapping[str, Any] | None,
    committed: CommittedState | Mapping[str, Any] | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
    *,
    page: int = 1,
) -> WalkStep:
    """Return the next menu/autocommit/completion action."""

    request = request if isinstance(request, Mapping) else {}
    envelope = envelope if isinstance(envelope, Mapping) else {}
    event_rows = _events(events)
    state = _apply_owner_locks(request, envelope, _state(committed))
    done = _done_steps(event_rows)
    ordinal = len(event_rows) + 1
    if ordinal > MAX_WALK_STEPS:
        _error("DCC_LINEAR_STEP_LIMIT", "The linear walk exceeds its step ceiling.")
    descriptors = _step_descriptors(request, envelope, state)
    for step_id, step_kind, slot_id in descriptors:
        if step_id in done:
            continue
        if is_owner_locked(request, envelope, step_id) or is_owner_locked(request, envelope, slot_id):
            continue
        selection_index = _selected_count(state, slot_id) + 1
        menu = build_step_menu(
            request,
            envelope,
            state,
            step_id=step_id,
            step_kind=step_kind,
            ordinal=ordinal,
            page=page,
            selection_index=selection_index,
        )
        if menu is None:
            # A ``None`` menu usually means "not applicable here".  For a
            # constructed-training slot that a rival/boss contract requires,
            # it means the frozen request cannot legally complete the
            # character.  Fail closed with the actionable detail instead of
            # walking past the mandatory slot to a response the validator
            # rejects with a bare count mismatch.
            if step_kind == "creation_training":
                gap = creation_training_required_gap(request, envelope, state, step_id)
                if gap is not None:
                    _error(
                        "DCC_LINEAR_REQUIRED_STEP_UNSATISFIABLE",
                        "A required constructed-training slot has no legal option in the frozen request; the character cannot be completed from this request.",
                        details=gap,
                    )
            if step_kind == "method_choice":
                gap = method_required_gap(request, envelope, state)
                if gap is not None:
                    _error(
                        "DCC_LINEAR_REQUIRED_STEP_UNSATISFIABLE",
                        "A character with attainment needs a Method and the frozen request offers no legal one for the selected Paths.",
                        details=gap,
                    )
            continue
        selectable = [option for option in menu.options if not option.is_continuation]
        if len(selectable) == 1 and step_kind != "identity":
            committed_state = commit_option(menu, selectable[0].option_id, state)
            event = {
                "event_type": EVENT_STEP_AUTOCOMMITTED,
                "step_id": step_id,
                "choice_ids": list(selectable[0].choice_ids),
                "reason": "single_option",
                "committed_sha256": committed_state.committed_sha256,
            }
            return WalkStep(step_id, step_kind, ordinal, ACTION_AUTOCOMMITTED, menu, committed_state, "single_option", event)
        return WalkStep(step_id, step_kind, ordinal, ACTION_MENU, menu, state)
    # Descriptors yielding nothing is not proof of completion.  Mandatory
    # acquisition counts are proven here, before the response is assembled,
    # so a missing step is reported as the exact next step rather than as a
    # validator rejection of an incomplete character.
    gaps = mandatory_completion_gaps(request, envelope, state)
    if gaps is not None:
        _error(
            "DCC_LINEAR_MANDATORY_STEPS_INCOMPLETE",
            "The walk ran out of steps with mandatory acquisitions still missing; completion is refused.",
            details=gaps,
        )
    return WalkStep("", "", ordinal, ACTION_COMPLETE, None, state, "walk_complete")


def commit_option(menu: StepMenu, option_id: str, committed: CommittedState | Mapping[str, Any] | None = None) -> CommittedState:
    """Validate an option against this exact menu, then apply its typed IDs."""

    menu = validate_step_menu(menu)
    state = _state(committed)
    try:
        parsed_id = parse_step_response({"option_id": option_id}, menu)
    except LinearMenuError:
        # Preserve the public fail-closed error type while retaining the
        # before-commit guarantee.
        raise
    option = next(option for option in menu.options if option.option_id == parsed_id)
    if option.is_continuation:
        _error("DCC_LINEAR_CONTINUATION", "A continuation option must be requested as the next page, not committed.")
    slot_id = menu.step_id.split(":", 1)[0]
    current = list(state.by_slot.get(slot_id, []))
    if menu.step_kind == "forged_design":
        return _with_forged_design_decision(state, menu.step_id, option.choice_ids)
    if menu.step_kind in {"starting_kit_option", "starting_kit_choice"}:
        return _with_starting_kit_decision(state, menu.step_id, option.choice_ids)
    if menu.step_kind.startswith("treasure_"):
        return _with_treasure_decision(state, menu.step_id, option.choice_ids)
    if option.kind == "none":
        # The builder adds a none option only after the frozen slot minimum
        # is satisfied.  Split-step menus intentionally expose 1/1 cardinality,
        # so menu membership is the authority for this slot-wide rule.
        if menu.step_kind == "creation_training":
            parts = menu.step_id.split(":")
            if len(parts) != 3:
                _error("DCC_LINEAR_TRAINED_CHOICE", "A constructed-training skip requires CL and slot components.")
            try:
                cl = int(parts[1])
            except (TypeError, ValueError) as exc:
                raise LinearWalkError("DCC_LINEAR_TRAINED_CHOICE", "A constructed-training skip requires a numeric CL.") from exc
            return state.with_trained_choice_skip(cl)
        return state
    if menu.step_kind == "sphere_free_talent_pair":
        if len(option.choice_ids) != 2:
            _error("DCC_LINEAR_PAIR_ID", "A free-Talent pair option must carry exactly two typed IDs.")
        return state.with_pair(option.choice_ids[0], option.choice_ids[1])
    if menu.step_kind == "sphere_route":
        if len(option.choice_ids) != 1:
            _error("DCC_LINEAR_ROUTE_ID", "A route option must carry exactly one route ID.")
        if state.route_id is not None:
            code = "DCC_LINEAR_ROUTE_DUPLICATE" if state.route_id == option.choice_ids[0] else "DCC_LINEAR_ROUTE_CONFLICT"
            _error(code, "A committed route cannot be selected again.")
        return state.with_route(option.choice_ids[0])
    if menu.step_kind == "ordinary_talent":
        if len(option.choice_ids) != 1:
            _error("DCC_LINEAR_ORDINARY_ID", "An ordinary Talent step commits exactly one Talent ID.")
        try:
            cl = int(menu.step_id.split(":", 1)[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise LinearWalkError("DCC_LINEAR_STEP_ID", "An ordinary Talent step requires a numeric CL.") from exc
        prior = state.ordinary_by_cl.get(str(cl))
        if prior is not None:
            code = "DCC_LINEAR_ORDINARY_DUPLICATE" if prior == option.choice_ids[0] else "DCC_LINEAR_ORDINARY_CONFLICT"
            _error(code, "An ordinary Talent CL cannot be selected again.")
        return state.with_ordinary(cl, option.choice_ids[0])
    if menu.step_kind == "creation_training":
        if option.kind == "none":
            try:
                cl = int(menu.step_id.split(":")[1])
            except (TypeError, ValueError, IndexError) as exc:
                raise LinearWalkError("DCC_LINEAR_TRAINED_CHOICE", "A constructed-training skip requires a numeric CL.") from exc
            return state.with_trained_choice_skip(cl)
        parts = menu.step_id.split(":")
        if len(parts) != 3:
            _error("DCC_LINEAR_TRAINED_CHOICE", "A constructed training step requires CL and slot components.")
        try:
            cl = int(parts[1])
            slot = int(parts[2])
        except (TypeError, ValueError) as exc:
            raise LinearWalkError("DCC_LINEAR_TRAINED_CHOICE", "A constructed training step requires numeric CL and slot values.") from exc
        if len(option.choice_ids) == 2:
            choice_type = "new_sphere"
            record_id, bonus_id = option.choice_ids
        elif len(option.choice_ids) == 1:
            choice_type = "known_sphere_talent"
            record_id = option.choice_ids[0]
            bonus_id = None
        else:
            _error("DCC_LINEAR_TRAINED_CHOICE", "A constructed training option must select a Talent or a Sphere/bonus pair.")
        choice: dict[str, Any] = {"cl": cl, "slot": slot, "choice_type": choice_type, "record_id": record_id}
        if bonus_id is not None:
            choice["bonus_talent_id"] = bonus_id
        return state.with_trained_choice(choice)
    if menu.step_kind == "insight_occurrence":
        suffix = menu.step_id.split(":", 1)[1] if ":" in menu.step_id else ""
        if suffix.endswith(":ability"):
            if len(option.choice_ids) != 1:
                _error("DCC_LINEAR_INSIGHT_ABILITY", "An Insight ability follow-up commits exactly one typed ability.")
            milestone_id = suffix[:-len(":ability")]
            return state.with_insight_ability(milestone_id, option.choice_ids[0])
        if len(option.choice_ids) != 1:
            _error("DCC_LINEAR_INSIGHT_OCCURRENCE", "An Insight occurrence choice commits exactly one typed Insight ID.")
        occurrence: dict[str, Any] = {"insight_id": option.choice_ids[0], "milestone_id": suffix}
        return state.with_insight_occurrence(occurrence)
    if menu.step_kind == "point_buy_preset":
        parsed: dict[str, int] | None = None
        mode: str | None = None
        for candidate_mode in ("permutable", "fixed"):
            parsed = _decode_score_bundle(option.choice_ids, "point_buy_preset", mode=candidate_mode)
            if parsed is not None:
                mode = candidate_mode
                break
        if parsed is None or mode is None or len(parsed) != 6:
            _error("DCC_LINEAR_POINT_BUY_PRESET", "The point-buy preset is not a complete typed six-ability selection.")
        abilities = list(parsed)
        preset = {
            "abilities": abilities,
            "scores": [parsed[ability] for ability in abilities],
            "permutable_across_abilities": mode == "permutable",
        }
        result = state.with_point_buy_preset(preset)
        return result if mode == "permutable" else result.with_ability_scores(parsed)
    if menu.step_kind == "point_buy_assignment":
        parsed = _decode_score_bundle(option.choice_ids, "point_buy_assignment")
        preset = _map(state.bounded.get("point_buy_preset"))
        advertised_abilities = preset.get("abilities")
        if parsed is None or not isinstance(advertised_abilities, (list, tuple)) or set(parsed) != set(advertised_abilities) or len(parsed) != 6 or preset.get("permutable_across_abilities") is not True:
            _error("DCC_LINEAR_POINT_BUY_ASSIGNMENT", "The point-buy assignment does not match the frozen preset.")
        preset_scores = preset.get("scores")
        if not isinstance(preset_scores, (list, tuple)) or sorted(parsed.values(), reverse=True) != sorted((value for value in preset_scores if type(value) is int), reverse=True):
            _error("DCC_LINEAR_POINT_BUY_ASSIGNMENT", "The point-buy assignment does not preserve the frozen preset scores.")
        return state.with_ability_scores(parsed)
    if menu.step_kind == "asi_or_insight":
        # The printed level milestone "Ability Score Improvement or Cultivation
        # Insight" resolves as one of its two printed branches; this commit
        # records which one, and the branch's own menu asks its detail question.
        if len(option.choice_ids) != 1 or option.choice_ids[0] not in MILESTONE_BRANCHES:
            _error("DCC_LINEAR_MILESTONE_BRANCH", "A level milestone branch option must name exactly one printed resolution.")
        milestone_id = menu.step_id.split(":", 1)[1] if ":" in menu.step_id else ""
        return state.with_milestone_branch(milestone_id, option.choice_ids[0])
    if menu.step_kind == "asi_milestone":
        deltas: dict[str, int] = {}
        for token in option.choice_ids:
            parts = token.split(":") if isinstance(token, str) else []
            if len(parts) != 3 or parts[0] != "asi" or parts[1] in deltas:
                _error("DCC_LINEAR_ASI", "An ASI option must carry typed ability/delta pairs.")
            try:
                delta = int(parts[2])
            except (TypeError, ValueError) as exc:
                raise LinearWalkError("DCC_LINEAR_ASI", "An ASI option must carry integer deltas.") from exc
            deltas[parts[1]] = delta
        milestone_id = menu.step_id.split(":", 1)[1] if ":" in menu.step_id else ""
        return state.with_ability_score_changes(milestone_id, deltas)
    if menu.step_kind == "path_progression":
        if len(option.choice_ids) != 1:
            _error("DCC_LINEAR_PROGRESSION", "A Path progression step commits one Path ID.")
        cl = menu.step_id.split(":", 1)[1] if ":" in menu.step_id else ""
        return state.with_path_progression(cl, option.choice_ids[0])
    if menu.step_kind in {"path_skill", "origin_skill", "background_language"}:
        if len(option.choice_ids) != 1:
            _error("DCC_LINEAR_PROFICIENCY", "A starting proficiency step commits one value.")
        suffix = menu.step_id.split(":", 1)[1] if ":" in menu.step_id else ""
        owner_id = suffix.rsplit(":", 1)[0] if ":" in suffix and suffix.rsplit(":", 1)[1].isdigit() else suffix
        field = {
            "path_skill": "path_skill_choices_by_path_id",
            "origin_skill": "origin_skill_choices_by_origin_id",
            "background_language": "background_language_choices_by_background_id",
        }[menu.step_kind]
        prior_map = _map(state.bounded.get(field))
        prior = prior_map.get(owner_id) if isinstance(prior_map.get(owner_id), (list, tuple)) else []
        return state.with_proficiency(field, owner_id, [*prior, option.choice_ids[0]])
    if set(option.choice_ids) & set(current):
        _error("DCC_LINEAR_COMMIT_DUPLICATE", "The option repeats a choice already committed in this slot.")
    if menu.step_kind == "foundation_initial_stage":
        if len(option.choice_ids) != 1:
            _error("DCC_LINEAR_FOUNDATION_STAGE", "An initial Foundation stage commits one published value.")
        return state.with_bounded("foundation_initial_stage", option.choice_ids[0])
    if menu.step_kind == "background_ability":
        ability, amount = _background_ability_parts(option.choice_ids)
        result = state.with_bounded("background_ability", ability)
        if amount is not None:
            result = result.with_bounded("background_ability_amount", amount)
        return result
    if menu.step_kind == "identity":
        _error("DCC_LINEAR_RESPONSE_KIND", "Identity must be committed with commit_identity.")
    return state.with_choice(slot_id, option.choice_ids)


def commit_identity(menu: StepMenu, response: Mapping[str, Any] | str, committed: CommittedState | Mapping[str, Any] | None = None) -> CommittedState:
    menu = validate_step_menu(menu)
    if menu.step_kind != "identity":
        _error("DCC_LINEAR_RESPONSE_KIND", "The supplied menu is not the identity step.")
    identity = parse_identity_response(response)
    return _state(committed).with_identity(identity["name"], identity["title"], identity.get("concept"))


def continue_page(menu: StepMenu) -> str:
    menu = validate_step_menu(menu)
    if menu.next_page_id is None:
        _error("DCC_LINEAR_PAGE_END", "The current menu has no continuation page.")
    return menu.next_page_id


def walk_next_step(*args: Any, **kwargs: Any) -> WalkStep:
    return next_step(*args, **kwargs)


def next_linear_step(*args: Any, **kwargs: Any) -> WalkStep:
    return next_step(*args, **kwargs)


def apply_option(*args: Any, **kwargs: Any) -> CommittedState:
    return commit_option(*args, **kwargs)


def commit_selection(*args: Any, **kwargs: Any) -> CommittedState:
    return commit_option(*args, **kwargs)


__all__ = [
    "ACTION_MENU",
    "ACTION_AUTOCOMMITTED",
    "ACTION_COMPLETE",
    "ACTION_SKIPPED",
    "ACTION_FAILED",
    "EVENT_STEP_COMMITTED",
    "EVENT_STEP_AUTOCOMMITTED",
    "LinearWalkError",
    "WalkStep",
    "next_step",
    "walk_next_step",
    "next_linear_step",
    "commit_option",
    "apply_option",
    "commit_selection",
    "commit_identity",
    "continue_page",
    "replay_committed_state",
]
