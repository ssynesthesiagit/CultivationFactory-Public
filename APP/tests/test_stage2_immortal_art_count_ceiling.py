"""Stage 2 enforces the Immortal Art lane rules on the final state.

Core Rules Reference v0.2C §17.6 / opening rules Step 7 (owner ruling
2026-09-11): a Nascent Soul character (CL 15-19) may hold at most 3 refined
Immortal Arts and an Immortal-tier character (CL 20) at most 6.  The lane is
resolved by an Art or a causal typed-none, never filled to a fixed count.
"""
from __future__ import annotations

import json

from stage2.service import RulesCausalStage2Service, _state


def _probe_state(cl: int, art_count: int, *, typed_none: bool = False) -> dict:
    state = _state("ceiling-probe")
    state.update({
        "current_cl": cl,
        "completed_levels": list(range(1, cl + 1)),
        "ability_scores": {"STR": 8},
        "background": "background",
        "background_sphere": "background-sphere",
        "background_talent": "background-talent",
        "origin_insight": "origin",
        "paths": ["tianxia.path.body_refining"],
        "method": {"state": "acquired", "record_id": "method"},
        "foundation": {"state": "acquired", "record_id": "foundation"},
        "recorded_arts": [{"record_id": "manual"}],
        "equipment": ["equipment"],
        "level_talents": {str(level): [{"record_id": f"talent-{level}"}] for level in range(1, cl + 1)},
        "event_occurrences": {"starting_state": [{"event_id": "starting"}]},
        "typed_none_states": {"forged_techniques": {"state": "none", "source_backed": True}},
        "forged_techniques": {"state": "none"},
        "immortal_arts": [{"art_id": f"art-{index}"} for index in range(art_count)],
    })
    if typed_none:
        state["typed_none_states"]["immortal_arts"] = {"state": "none", "source_backed": True}
    return state


def _immortal_rows(service, state, cl):
    return [row for row in service._completion_blockers(state, cl, [], {}) if str(row.get("code", "")).startswith("IMMORTAL_ARTS_")]


def test_an_immortal_tier_character_may_hold_at_most_six_arts(catalog_environment):
    service = RulesCausalStage2Service(catalog_environment["db"])
    assert _immortal_rows(service, _probe_state(20, 6), 20) == []
    rows = _immortal_rows(service, _probe_state(20, 7), 20)
    assert [row["code"] for row in rows] == ["IMMORTAL_ARTS_COUNT_EXCEEDS_TIER_CEILING"]
    payload = json.dumps(rows[0])
    assert '"tier": "Immortal"' in payload and '"ceiling": 6' in payload and '"actual": 7' in payload
    assert "17.6" in payload


def test_a_nascent_soul_character_may_hold_at_most_three_arts(catalog_environment):
    service = RulesCausalStage2Service(catalog_environment["db"])
    assert _immortal_rows(service, _probe_state(17, 3), 17) == []
    rows = _immortal_rows(service, _probe_state(17, 4), 17)
    assert [row["code"] for row in rows] == ["IMMORTAL_ARTS_COUNT_EXCEEDS_TIER_CEILING"]
    assert '"ceiling": 3' in json.dumps(rows[0])


def test_the_lane_is_resolved_by_one_art_or_a_causal_typed_none(catalog_environment):
    service = RulesCausalStage2Service(catalog_environment["db"])
    assert _immortal_rows(service, _probe_state(20, 1), 20) == []
    assert _immortal_rows(service, _probe_state(20, 0, typed_none=True), 20) == []
    rows = _immortal_rows(service, _probe_state(20, 0), 20)
    assert [row["code"] for row in rows] == ["IMMORTAL_ARTS_RESOLUTION_REQUIRED"]
    assert _immortal_rows(service, _probe_state(14, 0), 14) == []
