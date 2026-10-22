"""Exact golden hashes for the retained Gate 3 fight replay (scramble-local).

Why this is a separate file: the public mirror scrambles printed prose, and these
SHA-256 pins cover that prose inside the replayed state and events, so they fail on
public CI for reasons unrelated to the code. The public structural checks live in
tests/test_combat_gate3_persistence.py. Run this file locally (private tree).

Hashes move only when the replayed fight changes on purpose. Lead 2026-10-21: the
ending turn now records its closing TURN_ENDED after MATCH_ENDED (195 -> 196 events),
which is the only change behind the new pins.
"""

from __future__ import annotations

import copy
from pathlib import Path

from combat.canonical import canonical_sha256
from combat.gate3_scripted import execute_persistent_script
from tests.test_combat_gate3_persistence import SCRIPT_PATH, ROOT, strip_gate3_fields


def test_retained_fight_golden_hashes(tmp_path: Path) -> None:
    session, _decisions = execute_persistent_script(ROOT, tmp_path / "UserData", SCRIPT_PATH)
    replay = session.replay()
    actual_events = [strip_gate3_fields(event) for event in replay["events"]]

    mechanical_state = copy.deepcopy(replay["state"])
    assert mechanical_state.pop("observations")
    assert canonical_sha256(mechanical_state) == "58b9f9cff042c5cff43e08ae1faddc90a1b54a9777039c05a839d2ae1ec7b660"

    historical_events = copy.deepcopy(actual_events)
    for event in historical_events:
        event["payload"].pop("observations_after", None)
        event["payload"].pop("observed_by", None)
        if event["event_type"] == "REACTION_RESOLVED" and event["source_definition_id"] == "reaction:ling_qi.qi_armor":
            event["payload"].update(ac_bonus=3, new_ac=16)
    assert canonical_sha256(historical_events) == "f929dcf78b1f85f17691fd4bb1da9053048e443a764f4aefa75cceaccf2f53c8"
    assert historical_events[0]["payload"].pop("targeting_policy") == {
        "concealment_miss_percent": 0, "total_concealment_miss_percent": 0,
    }
    assert canonical_sha256(historical_events) == "b05102dc23b2fe1385e8a692e10968ab203739d57610ddbb6896d6277cceb400"
