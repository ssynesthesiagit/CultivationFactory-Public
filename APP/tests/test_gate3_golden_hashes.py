"""Exact golden hashes for the retained Gate 3 fight replay.

The pins are environment-independent. Everything the engine derives from printed
prose is left out of them: the public mirror scrambles printed rules text, so a
value computed from that text moves even though the fight is identical. The only
such value here is the Creation-time ``area_origin_permissions`` stamp, bound by
matching ``rules_text.json`` for the Darkness "anywhere within range" wording
(combat/area_knowledge.py): present on the private tree, absent where the text is
scrambled. That permission keeps its own behavioural tests
(tests/test_a2r13_observer_awareness.py) and a private-tree pin below; the replay
golden must not pin it, or public CI fails for a reason unrelated to the code.
The structural checks live in tests/test_combat_gate3_persistence.py.

Hashes move only when the replayed fight changes on purpose. Lead 2026-10-21:
the ending turn now records its closing TURN_ENDED after MATCH_ENDED (195 -> 196
events). That extra event is the only mechanical change: the state document,
with the event counter removed, hashes the same on main and on this branch
(MECHANICAL_STATE_WITHOUT_EVENT_SEQUENCE_SHA256). The full state pin moves
because ``state.event_sequence`` counts the extra event (195 -> 196), which the
test below asserts equals the number of recorded events.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.gate3_scripted import execute_persistent_script
from tests.test_combat_gate3_persistence import SCRIPT_PATH, ROOT, strip_gate3_fields

MECHANICAL_STATE_SHA256 = "58b9f9cff042c5cff43e08ae1faddc90a1b54a9777039c05a839d2ae1ec7b660"
# Same state with the event counter removed: identical on main a27e4bf9's replay
# (195 events) and this branch (196), which is what proves the only mechanical
# delta is the closing TURN_ENDED. Evidence: fix/MUTUALKO1F11-evidence/.
MECHANICAL_STATE_WITHOUT_EVENT_SEQUENCE_SHA256 = "a0264ec6d0093ffacf37b8bdec6c78eb4d61b67a5dfed70a99d31ac1cc7da3ed"
HISTORICAL_EVENTS_SHA256 = "84f58f1cf7ba3f5634ecb29c289029d1b94159c86f1c6da2dea4fd0c5e268716"
HISTORICAL_EVENTS_WITHOUT_TARGETING_SHA256 = "a3b6d054348080a8ff1ef96549985b54134f1f6aaa64e5342945f8007575aac5"
PRINTED_AREA_PERMISSION = {"DARK_BASE_DARKNESS": 0}


def _historical_events(events):
    """The historical event shape, minus values that depend on the machine's prose."""
    out = copy.deepcopy(events)
    for event in out:
        payload = event["payload"]
        payload.pop("observations_after", None)
        payload.pop("observed_by", None)
        # Printed-rule-derived (see the module docstring): the scrambled public
        # copy binds no exception, the private copy does. Same fight either way.
        payload.pop("area_origin_permissions", None)
        if event["event_type"] == "REACTION_RESOLVED" and event["source_definition_id"] == "reaction:ling_qi.qi_armor":
            payload.update(ac_bonus=3, new_ac=16)
    return out


def test_retained_fight_golden_hashes(tmp_path: Path) -> None:
    session, _decisions = execute_persistent_script(ROOT, tmp_path / "UserData", SCRIPT_PATH)
    replay = session.replay()
    actual_events = [strip_gate3_fields(event) for event in replay["events"]]

    mechanical_state = copy.deepcopy(replay["state"])
    assert mechanical_state.pop("observations")
    assert canonical_sha256(mechanical_state) == MECHANICAL_STATE_SHA256
    # The closing TURN_ENDED is the only mechanical delta: the event counter
    # moved with it, and the rest of the state is byte-identical to main's.
    without_counter = copy.deepcopy(mechanical_state)
    counter = without_counter.pop("event_sequence")
    assert counter == len(actual_events)
    assert canonical_sha256(without_counter) == MECHANICAL_STATE_WITHOUT_EVENT_SEQUENCE_SHA256

    historical = _historical_events(actual_events)
    assert canonical_sha256(historical) == HISTORICAL_EVENTS_SHA256
    assert historical[0]["payload"].pop("targeting_policy") == {
        "concealment_miss_percent": 0, "total_concealment_miss_percent": 0,
    }
    assert canonical_sha256(historical) == HISTORICAL_EVENTS_WITHOUT_TARGETING_SHA256


def test_private_tree_pins_the_printed_area_permission(tmp_path: Path) -> None:
    """Private-tree pin for the prose-bound Creation stamp the stable hash leaves out.

    Review RB1 finding 1: the public golden drops ``area_origin_permissions``
    because the scrambled mirror cannot bind it. This keeps coverage of the
    private value without moving the environment-independent pins; on a
    scrambled/public tree there is nothing to pin, so the test skips (see the
    report's 'Stays private' section).
    """
    session, _decisions = execute_persistent_script(ROOT, tmp_path / "UserData", SCRIPT_PATH)
    events = [strip_gate3_fields(event) for event in session.replay()["events"]]
    created = next(event for event in events if event["event_type"] == "MATCH_CREATED")
    permission = created["payload"]["area_origin_permissions"]
    if not permission:
        pytest.skip("scrambled public mirror binds no printed permission")
    assert permission == PRINTED_AREA_PERMISSION


def test_replay_golden_ignores_printed_prose_bound_at_creation(tmp_path: Path) -> None:
    """Regression (review F9R finding 1): the golden must not move with printed prose.

    Public CI runs the same fight over scrambled rules text, so the Creation stamp
    holds no printed exception there. Before this normalization the two shapes
    hashed differently and test_retained_fight_golden_hashes failed publicly
    (b77bad5c... instead of 84f58f1c...) although the fight was identical.
    """
    session, _decisions = execute_persistent_script(ROOT, tmp_path / "UserData", SCRIPT_PATH)
    replay = session.replay()
    events = [strip_gate3_fields(event) for event in replay["events"]]
    published = copy.deepcopy(events)
    for event in published:
        if event["event_type"] == "MATCH_CREATED":
            assert isinstance(event["payload"]["area_origin_permissions"], dict)
            event["payload"]["area_origin_permissions"] = {}

    assert canonical_sha256(_historical_events(published)) == HISTORICAL_EVENTS_SHA256
    assert canonical_sha256(_historical_events(published)) == canonical_sha256(_historical_events(events))
