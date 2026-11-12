"""Typed authority helpers for ordinary CAT3 Cultivation Insights.

The CAT3 compiler is the source of truth for Insight content.  This module
only translates fields that the compiler already typed into the bounded
Stage 2 acquisition contract; it never extracts mechanics from rules prose.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


ABILITY_NAME_TO_ID = {
    "strength": "STR",
    "dexterity": "DEX",
    "constitution": "CON",
    "intelligence": "INT",
    "wisdom": "WIS",
    "charisma": "CHA",
}


def _ability_ids(raw: dict[str, Any]) -> list[str]:
    values = raw.get("ability_options")
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        ability = ABILITY_NAME_TO_ID.get(value.strip().casefold(), value.strip().upper())
        if ability in {"STR", "DEX", "CON", "INT", "WIS", "CHA"} and ability not in result:
            result.append(ability)
    return result


def _repeatability(raw: dict[str, Any]) -> dict[str, Any]:
    """Compile repeatability from typed CAT3 fields, conservatively.

    Missing repeatability is closed as non-repeatable.  An authored maximum
    is finite; descriptive repeatability without a maximum remains open-ended
    and is represented with contiguous one-based occurrence indices.
    """
    value = raw.get("repeatable")
    maximum = raw.get("repeatable_maximum")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        maximum = None
    folded = value.strip().casefold() if isinstance(value, str) else ""
    if maximum is not None and maximum > 1:
        return {
            "mode": "finite",
            "maximum": maximum,
            "indexing": "one_based_contiguous",
            "source_field": "repeatable_maximum",
            "source_value": deepcopy(value),
        }
    if folded == "twice":
        return {
            "mode": "finite",
            "maximum": 2,
            "indexing": "one_based_contiguous",
            "source_field": "repeatable",
            "source_value": deepcopy(value),
        }
    if folded and folded != "no":
        return {
            "mode": "open_ended",
            "maximum": None,
            "indexing": "one_based_contiguous",
            "source_field": "repeatable",
            "source_value": deepcopy(value),
        }
    return {
        "mode": "nonrepeatable",
        "maximum": 1,
        "indexing": "one_based_contiguous",
        "source_field": "repeatable" if value is not None else "default",
        "source_value": deepcopy(value),
    }


def compile_insight_stage2_authority(raw: dict[str, Any], record_id: str) -> dict[str, Any]:
    """Return the complete typed acquisition authority for one selectable Insight."""
    raw_source_record = raw.get("raw_source_record")
    typed = {
        **(raw_source_record if isinstance(raw_source_record, dict) else {}),
        **raw,
    }
    minimum_cl = typed.get("minimum_cl")
    if not isinstance(minimum_cl, int) or not 1 <= minimum_cl <= 20:
        minimum_cl = 1
    abilities = _ability_ids(typed)
    repeatability = _repeatability(typed)
    ability_change = None
    if abilities:
        ability_change = {
            "selection_mode": "level_selection",
            "allowed_abilities": abilities,
            "amount": 1,
            "cap": 20,
            "allowed_cls": list(range(minimum_cl, 21)),
            "source_field": "ability_options",
            "source_value": deepcopy(typed.get("ability_options")),
        }
    source_authority = deepcopy(raw.get("source_authority") or typed.get("source_authority") or {})
    prerequisite_values = raw.get("prerequisites")
    if not isinstance(prerequisite_values, list):
        prerequisite_ledger = typed.get("compiled_prerequisite_ledger")
        prerequisite_values = ((prerequisite_ledger if isinstance(prerequisite_ledger, dict) else {}).get("resolved_relations") or [])
    prerequisites = [
        deepcopy(row)
        for row in prerequisite_values
        if isinstance(row, dict)
    ]
    source_record_commitment = (
        raw.get("source_record_commitment_sha256")
        or raw.get("record_commitment_sha256")
        or typed.get("source_record_commitment_sha256")
        or typed.get("record_commitment_sha256")
        or source_authority.get("source_record_sha256")
    )
    return {
        "authority_complete": True,
        "allowed_kinds": ["cultivation_insight_acquisition"],
        "allowed_channels": ["cultivation-insight-selection"],
        "minimum_cl": minimum_cl,
        "allowed_cls": list(range(minimum_cl, 21)),
        "insight_authority_type": typed.get("insight_authority_type"),
        "insight_group": deepcopy(typed.get("insight_group") or {}),
        "owning_canonical_sphere_ids": deepcopy(typed.get("owning_canonical_sphere_ids") or []),
        "typed_prerequisites": prerequisites,
        "ability_change": ability_change,
        # Kept as an explicit compatibility name for older read models.  The
        # Stage 2 runtime consumes ``ability_change`` above.
        "insight_ability_change": deepcopy(ability_change),
        "repeatability": repeatability,
        "execution_authority": {
            "execution_status": typed.get("execution_status"),
            "execution_profile": deepcopy(typed.get("execution_profile") or {}),
            "resources": deepcopy(typed.get("resources") or []),
            "rest_cadence": deepcopy(typed.get("rest_cadence") or []),
            "action_types": deepcopy(typed.get("action_types") or []),
            "manual_runtime_boundary": "Acquisition and the typed ability-selection packet are executable authority; remaining Insight rules stay source-backed display/manual authority until a later execution gate.",
        },
        "source_authority": source_authority,
        "source_record_commitment_sha256": source_record_commitment,
        "rule_id": f"cat3.{record_id}.cultivation-insight-acquisition.v1",
    }


def insight_occurrence_index(details: dict[str, Any], prior_occurrences: list[dict[str, Any]]) -> int:
    """Resolve the explicit one-based index used by repeatable Insights."""
    value = details.get("repeat_index")
    if isinstance(value, bool) or not isinstance(value, int):
        return len(prior_occurrences) + 1
    return value


__all__ = [
    "ABILITY_NAME_TO_ID",
    "compile_insight_stage2_authority",
    "insight_occurrence_index",
]
