"""Shared, source-backed owner decision projections.

The owner review API and the response resolver both consume the same frozen
envelope.  This module only derives displayable alternatives; acceptance is
still performed by the delegated validator and the compilation path.
"""

from __future__ import annotations

import itertools
from copy import deepcopy
from typing import Any

from app.core import sha256_json

_ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")


def _choice_authority(envelope: dict[str, Any], slot_id: str, choice_id: str) -> dict[str, Any]:
    typed = envelope.get("typed_choice_authority_by_slot") or {}
    authority = (
        (typed.get(slot_id) or {}).get("stage2_authority_by_choice", {}).get(choice_id)
        if isinstance(typed, dict)
        else None
    )
    if not isinstance(authority, dict):
        choice = ((envelope.get("choices_by_slot") or {}).get(slot_id) or {}).get(choice_id) or {}
        authority = choice.get("stage2_authority")
        if not isinstance(authority, dict):
            authority = (choice.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
    return authority if isinstance(authority, dict) else {}


def _choice_metadata(envelope: dict[str, Any], slot_id: str, choice_id: str) -> dict[str, Any]:
    choices_by_slot = envelope.get("choices_by_slot") if isinstance(envelope.get("choices_by_slot"), dict) else {}
    slot_choices = choices_by_slot.get(slot_id) if isinstance(choices_by_slot.get(slot_id), dict) else {}
    choice = slot_choices.get(choice_id) if isinstance(slot_choices, dict) else {}
    return choice if isinstance(choice, dict) else {}


def _selected_values(selected_by_slot: dict[str, Any] | None, slot_id: str) -> list[Any]:
    if not isinstance(selected_by_slot, dict):
        return []
    values = selected_by_slot.get(slot_id)
    return list(values) if isinstance(values, list) else []


def _selected_path_ids(
    envelope: dict[str, Any],
    selected_by_slot: dict[str, Any] | None,
) -> set[str]:
    values = [value for value in _selected_values(selected_by_slot, "path_choice") if isinstance(value, str)]
    if not values:
        locks = envelope.get("owner_locks") if isinstance(envelope.get("owner_locks"), dict) else {}
        by_slot = locks.get("by_slot") if isinstance(locks.get("by_slot"), dict) else {}
        values = [value for value in by_slot.get("path_choice") or [] if isinstance(value, str)]
    return set(values)


def _milestone_row(details: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    nested = details.get("milestone") if isinstance(details.get("milestone"), dict) else {}
    milestone_id = details.get("milestone_id") or nested.get("milestone_id")
    rows = {
        row.get("milestone_id"): row
        for row in envelope.get("advancement_choice_milestones") or []
        if isinstance(row, dict) and isinstance(row.get("milestone_id"), str)
    }
    source = rows.get(milestone_id) or {}
    return {**source, **nested, **details, "milestone_id": milestone_id}


def _milestone_is_selected(
    milestone: dict[str, Any],
    *,
    envelope: dict[str, Any],
    proposal_bounded: dict[str, Any],
    proposal_selected_by_slot: dict[str, Any] | None,
) -> bool:
    path_id = milestone.get("path_id")
    selected_paths = _selected_path_ids(envelope, proposal_selected_by_slot)
    if isinstance(path_id, str) and selected_paths and path_id not in selected_paths:
        return False
    progression = proposal_bounded.get("path_progression_by_cl")
    cl = milestone.get("cl", milestone.get("effective_cl"))
    if isinstance(progression, dict) and isinstance(cl, int):
        selected_at_cl = progression.get(str(cl), progression.get(cl))
        if isinstance(selected_at_cl, str):
            return selected_at_cl == path_id
        if isinstance(selected_at_cl, list) and isinstance(path_id, str):
            return path_id in selected_at_cl
    return True


def _milestone_rows(envelope: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row.get("milestone_id"): row
        for row in envelope.get("advancement_choice_milestones") or []
        if isinstance(row, dict) and isinstance(row.get("milestone_id"), str)
    }


def _current_scores(
    *,
    milestone: dict[str, Any],
    envelope: dict[str, Any],
    proposal_bounded: dict[str, Any],
    proposal_acquisition: dict[str, Any],
    proposal_selected_by_slot: dict[str, Any] | None,
) -> dict[str, int]:
    base = proposal_bounded.get("ability_scores")
    scores = {
        ability: value
        for ability, value in (base.items() if isinstance(base, dict) else [])
        if ability in _ABILITIES and type(value) is int
    }
    rows = _milestone_rows(envelope)
    current_id = milestone.get("milestone_id")
    current_cl = milestone.get("cl", milestone.get("effective_cl"))

    def before_current(row: dict[str, Any]) -> bool:
        row_id = row.get("milestone_id")
        row_cl = row.get("cl", row.get("effective_cl"))
        if row_id == current_id:
            return False
        if type(current_cl) is int and type(row_cl) is int:
            return row_cl < current_cl
        return True

    changes = proposal_bounded.get("ability_score_changes_by_milestone_id")
    if isinstance(changes, dict):
        for milestone_id, delta_map in sorted(changes.items()):
            row = rows.get(milestone_id)
            if not isinstance(row, dict) or not before_current(row) or not _milestone_is_selected(
                row,
                envelope=envelope,
                proposal_bounded=proposal_bounded,
                proposal_selected_by_slot=proposal_selected_by_slot,
            ):
                continue
            if not isinstance(delta_map, dict):
                continue
            for ability, delta in delta_map.items():
                if ability in _ABILITIES and type(delta) is int and ability in scores:
                    scores[ability] += delta

    occurrences = proposal_acquisition.get("insight_occurrences") if isinstance(proposal_acquisition, dict) else []
    for occurrence in occurrences or []:
        if not isinstance(occurrence, dict):
            continue
        row = rows.get(occurrence.get("milestone_id"))
        if not isinstance(row, dict) or not before_current(row) or not _milestone_is_selected(
            row,
            envelope=envelope,
            proposal_bounded=proposal_bounded,
            proposal_selected_by_slot=proposal_selected_by_slot,
        ):
            continue
        insight_id = occurrence.get("insight_id")
        if not isinstance(insight_id, str):
            continue
        authority = _choice_authority(envelope, "insight_priorities", insight_id)
        rule = authority.get("ability_change") or authority.get("insight_ability_change")
        parameters = occurrence.get("parameters") if isinstance(occurrence.get("parameters"), dict) else {}
        ability = parameters.get("ability")
        amount = rule.get("amount") if isinstance(rule, dict) else None
        if ability in scores and type(amount) is int:
            scores[ability] += amount
    return scores


def _asi_choices(
    milestone_id: str,
    rule: dict[str, Any],
    current_scores: dict[str, Any],
) -> list[dict[str, Any]]:
    allowed_deltas = [value for value in rule.get("allowed_deltas") or [] if type(value) is int]
    budget = rule.get("budget")
    abilities = tuple(value for value in rule.get("allowed_abilities") or _ABILITIES if value in _ABILITIES)
    cap = rule.get("cap")
    if not allowed_deltas or type(budget) is not int or not abilities:
        return []
    choices: list[dict[str, Any]] = []
    for count in range(1, len(abilities) + 1):
        for selected in itertools.combinations(abilities, count):
            for deltas in itertools.product(allowed_deltas, repeat=count):
                if sum(deltas) != budget:
                    continue
                if type(cap) is int and any(
                    type(current_scores.get(ability)) is int
                    and current_scores[ability] + delta > cap
                    for ability, delta in zip(selected, deltas)
                ):
                    continue
                value = {
                    "kind": "ability_score_change",
                    "milestone_id": milestone_id,
                    "deltas": dict(zip(selected, deltas)),
                }
                choices.append({
                    "choice_id": f"{milestone_id}.asi.{sha256_json(value)[:16]}",
                    "value": value,
                    "name": "Ability-score improvement: " + ", ".join(
                        f"{ability} {delta:+d}" for ability, delta in value["deltas"].items()
                    ),
                    "operation": "set_milestone_choice",
                })
    return choices


def _acquired_ids(
    proposal_acquisition: dict[str, Any],
    proposal_selected_by_slot: dict[str, Any] | None,
    *,
    exclude_milestone_id: str | None = None,
) -> dict[str, set[str]]:
    acquired: dict[str, set[str]] = {
        "path": set(value for value in _selected_values(proposal_selected_by_slot, "path_choice") if isinstance(value, str)),
        "subpath": set(value for value in _selected_values(proposal_selected_by_slot, "subpath_choice") if isinstance(value, str)),
        "sphere": set(),
        "insight": set(),
    }
    for key in ("acquired_sphere_ids", "sphere_ids", "acquired_canonical_sphere_ids"):
        values = proposal_acquisition.get(key)
        if isinstance(values, list):
            acquired["sphere"].update(value for value in values if isinstance(value, str))
    for row in proposal_acquisition.get("sphere_free_talent_pairs") or []:
        if isinstance(row, dict) and isinstance(row.get("sphere_id"), str):
            acquired["sphere"].add(row["sphere_id"])
    for row in proposal_acquisition.get("insight_occurrences") or []:
        if (
            isinstance(row, dict)
            and row.get("milestone_id") != exclude_milestone_id
            and isinstance(row.get("insight_id"), str)
        ):
            acquired["insight"].add(row["insight_id"])
    return acquired


def _relation_targets(relation: dict[str, Any]) -> list[str]:
    values = relation.get("target_ids") or relation.get("targets")
    if isinstance(values, str):
        return [values]
    if isinstance(values, list):
        return [value for value in values if isinstance(value, str)]
    value = relation.get("target_id") or relation.get("record_id")
    return [value] if isinstance(value, str) else []


def _relation_bucket(acquired: dict[str, set[str]], kind: Any) -> set[str]:
    normalized = str(kind or "").casefold()
    bucket = acquired.get(normalized)
    if bucket is None and normalized.endswith("s"):
        bucket = acquired.get(normalized[:-1])
    return bucket or set().union(*acquired.values())


def _prerequisites_allow(
    *,
    envelope: dict[str, Any],
    insight_id: str,
    acquired: dict[str, set[str]],
) -> bool:
    availability = envelope.get("prerequisites_and_availability")
    availability = availability if isinstance(availability, dict) else {}
    frozen = availability.get("insight_priorities") if isinstance(availability.get("insight_priorities"), dict) else {}
    frozen_row = frozen.get(insight_id) if isinstance(frozen, dict) else {}
    metadata = _choice_metadata(envelope, "insight_priorities", insight_id)
    prerequisites = frozen_row.get("prerequisites") if isinstance(frozen_row, dict) else None
    if not isinstance(prerequisites, list):
        prerequisites = metadata.get("prerequisites") if isinstance(metadata.get("prerequisites"), list) else []
    for prerequisite in prerequisites:
        if not isinstance(prerequisite, dict):
            return False
        targets = _relation_targets(prerequisite)
        if not targets:
            return False
        bucket = _relation_bucket(acquired, prerequisite.get("kind"))
        operator = str(prerequisite.get("operator") or "requires").casefold()
        if operator in {"requires", "required", "require", "all_of"} and not all(
            target in bucket for target in targets
        ):
            return False
        if operator == "one_of" and not any(target in bucket for target in targets):
            return False
        if operator in {"excludes", "incompatible", "forbids", "forbidden", "not"} and any(
            target in bucket for target in targets
        ):
            return False
        if operator not in {
            "requires", "required", "require", "all_of", "one_of",
            "excludes", "incompatible", "forbids", "forbidden", "not",
        }:
            return False
    incompatibilities = metadata.get("incompatibilities") if isinstance(metadata.get("incompatibilities"), list) else []
    for incompatibility in incompatibilities:
        if isinstance(incompatibility, str):
            if any(incompatibility in bucket for bucket in acquired.values()):
                return False
            continue
        if not isinstance(incompatibility, dict):
            return False
        bucket = _relation_bucket(acquired, incompatibility.get("kind"))
        targets = _relation_targets(incompatibility)
        if not targets or any(target in bucket for target in targets):
            return False
    return True


def _insight_choices(
    milestone: dict[str, Any],
    envelope: dict[str, Any],
    proposal_acquisition: dict[str, Any],
    proposal_bounded: dict[str, Any],
    proposal_selected_by_slot: dict[str, Any] | None,
    current_scores: dict[str, int],
) -> list[dict[str, Any]]:
    milestone_id = milestone.get("milestone_id")
    effective_cl = milestone.get("cl", milestone.get("effective_cl"))
    selected_occurrences = [
        row for row in proposal_acquisition.get("insight_occurrences") or []
        if isinstance(row, dict) and row.get("milestone_id") != milestone_id
    ]
    occurrence_counts: dict[str, int] = {}
    for row in selected_occurrences:
        insight_id = row.get("insight_id")
        if isinstance(insight_id, str):
            occurrence_counts[insight_id] = occurrence_counts.get(insight_id, 0) + 1
    acquired = _acquired_ids(
        proposal_acquisition,
        proposal_selected_by_slot,
        exclude_milestone_id=milestone_id if isinstance(milestone_id, str) else None,
    )
    allowed_ids = (envelope.get("allowed_choice_ids_by_slot") or {}).get("insight_priorities") or []
    choices: list[dict[str, Any]] = []
    for insight_id in allowed_ids:
        if not isinstance(insight_id, str):
            continue
        authority = _choice_authority(envelope, "insight_priorities", insight_id)
        metadata = _choice_metadata(envelope, "insight_priorities", insight_id)
        if insight_id in set(
            value for value in (envelope.get("unavailable_or_rejected_choice_ids_by_slot") or {}).get("insight_priorities") or []
            if isinstance(value, str)
        ):
            continue
        if not _prerequisites_allow(envelope=envelope, insight_id=insight_id, acquired=acquired):
            continue
        allowed_cls = authority.get("allowed_cls") or authority.get("allowed_effective_cls")
        if not isinstance(allowed_cls, list):
            frozen = (envelope.get("prerequisites_and_availability") or {}).get("insight_priorities") or {}
            frozen_row = frozen.get(insight_id) if isinstance(frozen, dict) else {}
            availability = frozen_row.get("availability") if isinstance(frozen_row, dict) else {}
            allowed_cls = [availability.get("minimum_cl")] if isinstance(availability, dict) and type(availability.get("minimum_cl")) is int else []
        if isinstance(allowed_cls, list) and effective_cl not in allowed_cls:
            continue
        repeatability = authority.get("repeatability") or {}
        count = occurrence_counts.get(insight_id, 0)
        mode = repeatability.get("mode") or "nonrepeatable"
        maximum = repeatability.get("maximum")
        if mode == "nonrepeatable" and count:
            continue
        if type(maximum) is int and count >= maximum:
            continue
        rule = authority.get("ability_change") or authority.get("insight_ability_change") or {}
        amount = rule.get("amount")
        cap = rule.get("cap")
        abilities = [value for value in rule.get("allowed_abilities") or [] if value in _ABILITIES]
        if not abilities or type(amount) is not int or amount <= 0:
            continue
        parameter_values = [
            {"ability": ability}
            for ability in abilities
            if type(current_scores.get(ability)) is not int
            or type(cap) is not int
            or current_scores[ability] + amount <= cap
        ]
        for parameters in parameter_values:
            ability = parameters["ability"]
            current_score = current_scores.get(ability)
            resulting_score = current_score + amount if type(current_score) is int else None
            value: dict[str, Any] = {
                "kind": "cultivation_insight_acquisition",
                "milestone_id": milestone_id,
                "insight_id": insight_id,
            }
            if parameters:
                value["parameters"] = parameters
            choice = {
                "choice_id": f"{milestone_id}.insight.{insight_id}.{sha256_json(value)[:12]}",
                "value": value,
                "name": metadata.get("name") or insight_id,
                "description": metadata.get("description"),
                "ability": ability,
                "amount": amount,
                "current_score": current_score,
                "resulting_score": resulting_score,
                "cap": cap,
                "operation": "set_milestone_choice",
            }
            choices.append(choice)
    return choices


def enrich_milestone_details(
    details: dict[str, Any],
    *,
    envelope: dict[str, Any],
    proposal_bounded: dict[str, Any] | None = None,
    proposal_acquisition: dict[str, Any] | None = None,
    proposal_selected_by_slot: dict[str, Any] | None = None,
    authority_by_milestone: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach legal, typed milestone alternatives to a server blocker."""
    result = deepcopy(details) if isinstance(details, dict) else {}
    milestone = _milestone_row(result, envelope)
    milestone_id = milestone.get("milestone_id")
    if not isinstance(milestone_id, str) or not milestone_id:
        return result
    result["milestone_id"] = milestone_id
    result.setdefault("operation", "set_milestone_choice")
    result.setdefault("allowed_kinds", deepcopy(milestone.get("allowed_kinds") or []))
    authority = (authority_by_milestone or {}).get(milestone_id) if isinstance(authority_by_milestone, dict) else {}
    authority = authority if isinstance(authority, dict) else {}
    rule = authority.get("ability_change") if isinstance(authority.get("ability_change"), dict) else {}
    if not rule:
        feature = milestone.get("feature") if isinstance(milestone.get("feature"), dict) else {}
        feature_authority = (feature.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
        rule = feature_authority.get("ability_change") if isinstance(feature_authority.get("ability_change"), dict) else {}
    bounded = proposal_bounded if isinstance(proposal_bounded, dict) else {}
    scores = bounded.get("ability_scores") if isinstance(bounded.get("ability_scores"), dict) else {}
    acquisition = proposal_acquisition if isinstance(proposal_acquisition, dict) else {}
    if not _milestone_is_selected(
        milestone,
        envelope=envelope,
        proposal_bounded=bounded,
        proposal_selected_by_slot=proposal_selected_by_slot,
    ):
        result["legal_choices"] = []
        result["allowed_milestone_choices"] = []
        result["allowed_choice_ids"] = []
        return result
    legal_choices: list[dict[str, Any]] = []
    scores = _current_scores(
        milestone=milestone,
        envelope=envelope,
        proposal_bounded=bounded,
        proposal_acquisition=acquisition,
        proposal_selected_by_slot=proposal_selected_by_slot,
    )
    allowed_kinds = result.get("allowed_kinds") or milestone.get("allowed_kinds") or []
    allowed_kinds = [kind for kind in allowed_kinds if isinstance(kind, str)]
    if "ability_score_change" in allowed_kinds:
        legal_choices.extend(_asi_choices(milestone_id, rule, scores))
    if "cultivation_insight_acquisition" in allowed_kinds:
        legal_choices.extend(_insight_choices(
            milestone,
            envelope,
            acquisition,
            bounded,
            proposal_selected_by_slot,
            scores,
        ))
    legal_choices.sort(key=lambda choice: str(choice.get("choice_id") or ""))
    result["legal_choices"] = legal_choices
    result["allowed_milestone_choices"] = deepcopy(legal_choices)
    result["allowed_choice_ids"] = [deepcopy(choice.get("value")) for choice in legal_choices]
    result["allowed_choice_values"] = [deepcopy(choice.get("value")) for choice in legal_choices]
    return result
