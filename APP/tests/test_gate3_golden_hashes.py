"""Exact golden hashes for the retained Gate 3 fight replay.

The pins are environment-independent. Everything the engine derives from printed
prose is left out of them: the public mirror scrambles printed rules text, so a
value computed from that text moves even though the fight is identical. The
prose-bound values here are ``area_origin_permissions``, ``damage_label``,
``mechanics_lock_sha256`` and ``universal_defaults_lock_sha256``.
The creation-time ``area_origin_permissions`` stamp is bound by matching
``rules_text.json`` for the Darkness "anywhere within range" wording
(combat/area_knowledge.py): present on the private tree, absent where the text is
scrambled. That permission keeps its own behavioural tests
(tests/test_a2r13_observer_awareness.py) and a private-tree pin below.
The ``damage_label`` is display text from ``packet_metadata`` / ``history_name``
(combat/damage_context.py); the persistence test still checks its type.
The last two values are fingerprints of generated lock files whose prose the
public mirror scrambles; we check them against those files instead of pinning them.
The pins and the structural checks on that same replay live here, together, so a
pin cannot be updated without the fight shape it is pinning being reviewed too.
tests/test_combat_gate3_persistence.py keeps the journal and persistence checks.

Hashes move only when the replayed fight changes on purpose. Lead F49 H2
(2026-11-19): the decisive Water Lash settles its Moon Sea Radiance aftermath
and closes the turn normally (including Bai Cui's default Dodge and the
Radiance expiry) before MATCH_ENDED. The replay now has 202 events and still
has 38 rolls. The 11-16 merge of main
added ``distance_ft`` to six MOVEMENT_COMMITTED payloads; removing it restores
the earlier event pins (lead proof: /var/tmp/auto-audit/ino-runs/mko21/proof.log).
Main f693518a78 added five damage receipt keys; removing all five restores the
previous event pins (lead proof: INO-MKO58PROOF4,
/var/tmp/auto-audit/fix/MUTUALKO1F58-leadproof/proof4.log).
Lead GOLDSTATE2 (2026-11-23) verified that removing the two lock fingerprints
makes both state pins identical in the private and scrambled public replays.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.gate3_scripted import execute_persistent_script
from tests.test_combat_gate3_persistence import SCRIPT_PATH, ROOT, strip_gate3_fields

# Lead F49 H2 (2026-11-19): state after Water Lash and the decisive turn fully settle.
# lock fingerprints left out (prose-bound, lead GOLDSTATE2 2026-11-23)
MECHANICAL_STATE_SHA256 = "93cebe6b1f788330e6671f309760b9a0acfd919ff93821e2c4e57c55f0744cbb"
# Same state with the event counter removed (the test asserts the counter equals the number of recorded events).
# Lead F50 H3 (2026-11-19): settled Water Lash state without the event counter.
# lock fingerprints left out (prose-bound, lead GOLDSTATE2 2026-11-23)
MECHANICAL_STATE_WITHOUT_EVENT_SEQUENCE_SHA256 = "88d5b1a8d7d0ca57a1c79de5d6376236d904c78dc614dba29a37c3153cecd343"
# main f693518a78: damage receipts add standing_before, bloodied_before, condition_ids_before, hit_roll_id
HISTORICAL_EVENTS_SHA256 = "b83d5f60dc68cd7e9a7483bb8a3507960c92f170ccd7d200d6b3ef4f96ec4cbc"
# main f693518a78: damage receipts add standing_before, bloodied_before, condition_ids_before, hit_roll_id
HISTORICAL_EVENTS_WITHOUT_TARGETING_SHA256 = "edfe625accba46ce6277b812cc35bc93dfbce57b2077c629cc1c7d9941f48c4c"
PRINTED_AREA_PERMISSION = {"DARK_BASE_DARKNESS": 0}


def _historical_events(events):
    """The historical event shape, minus values that depend on the machine's prose."""
    out = copy.deepcopy(events)
    for event in out:
        payload = event["payload"]
        payload.pop("observations_after", None)
        payload.pop("observed_by", None)
        # Printed-text-derived (see the module docstring): the Darkness exception
        # and the damage display label can differ in the scrambled public mirror.
        payload.pop("area_origin_permissions", None)
        payload.pop("damage_label", None)
        if event["event_type"] == "REACTION_RESOLVED" and event["source_definition_id"] == "reaction:ling_qi.qi_armor":
            payload.update(ac_bonus=3, new_ac=16)
    return out


def test_retained_fight_golden_hashes(tmp_path: Path) -> None:
    session, _decisions = execute_persistent_script(ROOT, tmp_path / "UserData", SCRIPT_PATH)
    replay = session.replay()
    actual_events = [strip_gate3_fields(event) for event in replay["events"]]

    mechanical_state = copy.deepcopy(replay["state"])
    assert mechanical_state.pop("observations")
    for key, filename in (
        ("mechanics_lock_sha256", "Gate2_Executable_Mechanics_Lock.json"),
        ("universal_defaults_lock_sha256", "Gate2_Universal_Combat_Defaults_Lock.json"),
    ):
        lock_path = ROOT / "combat_gate2/generated" / filename
        assert mechanical_state.pop(key) == canonical_sha256(json.loads(lock_path.read_text(encoding="utf-8"))), key
    assert canonical_sha256(mechanical_state) == MECHANICAL_STATE_SHA256
    # The event counter counts every recorded event; the rest of the state is pinned without it.
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

    # Structural checks for the same replay (also kept in
    # test_combat_gate3_persistence.py): the pinned bytes are this fight, not a
    # different one that happens to hash the same shape.
    retained_events = json.loads((ROOT / "combat_gate2/final/Gate2_Final_Event_Log.json").read_text())["events"]
    retained_rolls = json.loads((ROOT / "combat_gate2/final/Gate2_Final_Roll_Log.json").read_text())["rolls"]
    assert replay["rolls"] == retained_rolls
    assert [e["payload"] for e in actual_events if e["event_type"] == "REACTION_RESOLVED"
            and e["source_definition_id"] == "reaction:ling_qi.qi_armor"] == [
        {"ac_bonus": 5, "hit_after_recheck": True, "new_ac": 18}] * 2
    actual_moves = [e for e in actual_events if e["event_type"] == "MOVEMENT_COMMITTED" and "path" in e["payload"]]
    retained_moves = [e for e in retained_events if e["event_type"] == "MOVEMENT_COMMITTED" and "path" in e["payload"]]
    for actual, retained in zip(actual_moves, retained_moves, strict=True):
        assert actual["payload"]["path"][0] == retained["payload"]["path"][0]
        assert actual["payload"]["path"][-1] == retained["payload"]["path"][-1]
    assert [(event["event_type"], event["actor_id"]) for event in replay["events"][-2:]] == [
        ("TURN_ENDED", "bai_meizhen_early_outer_sect_cl5"), ("MATCH_ENDED", None),
    ]


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
