"""Seeded AI fight event streams and full-state replay controls.

For intentional fight changes, re-record in the same commit from APP with:
python tools/record_l41_controls.py tests/l41_replay_controls.py
"""
import json
from itertools import zip_longest

import pytest

from combat.area_knowledge import bind_origin_permissions
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.l41_replay_controls import CONTROL_STREAMS
from tests.legacy_fight_support import legacy_zero_hp
from tests.r1i_service_support import ROOT, fixture
from tests.replay_assertions import assert_replay_equal

SEEDS = tuple(f"SOL41-REPLAY-{i}" for i in range(3))


def capture_l41_control(tmp_path, seed):
    """Replay the shared fixture and return diagnostic event lines, final state and a digest."""
    combat, table, mid, _, _ = fixture(tmp_path, [], seed=seed)
    for actor_id in combat._load_session(mid).engine.state.actors:
        combat.set_controller_mode(mid, actor_id=actor_id, controller_mode="LOCAL_AUTO")
    for _ in range(24):
        result = table.auto_step(mid, 0)
        assert result["status"] == "COMMITTED", result
        current = combat._load_session(mid)
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
        loaded = combat._load_session(mid)
        assert_replay_equal(loaded.engine.state.model_dump(mode="json"), current.engine.state.model_dump(mode="json"))
        if loaded.engine.state.terminal_result is not None:
            break
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    payload = {
        "state": loaded.engine.state.model_dump(mode="json"),
        "events": [e.model_dump(mode="json") for e in loaded.engine.events],
        "rolls": [r.model_dump(mode="json") for r in loaded.engine.rolls],
    }
    # The public test export scrambles the rules prose that determines this map.
    permissions = payload["events"][0]["payload"].pop("area_origin_permissions")
    assert permissions == bind_origin_permissions(ROOT)
    assert set(permissions) <= {"DARK_BASE_DARKNESS"}
    assert all(value == 0 for value in permissions.values())

    lines = []
    for event in payload["events"]:
        # Genesis contains the complete initial state; the final digest covers it.
        details = {} if event["sequence"] == 1 else event["payload"]
        row = {
            "step": event["sequence"], "actor": event["actor_id"],
            "kind": event["event_type"], "action": event["source_definition_id"],
            "targets": event["target_ids"], "outcome": details,
        }
        lines.append(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return lines, payload["state"], canonical_sha256(payload)


def assert_events_match(expected, actual):
    for index, (want, got) in enumerate(zip_longest(expected, actual)):
        assert want == got, f"first differing event {index}: expected {want!r}; got {got!r}"


def test_control_mutation_reports_first_differing_event():
    expected = CONTROL_STREAMS[SEEDS[0]].splitlines()[:-1]
    actual = expected.copy()
    actual[1] = "altered event"
    with pytest.raises(AssertionError, match="first differing event 1:") as exc:
        assert_events_match(expected, actual)
    assert expected[1] in str(exc.value)
    assert "altered event" in str(exc.value)


@pytest.mark.parametrize("seed", SEEDS)
def test_ai_fight_matches_cycle_control_bytes(tmp_path, seed, legacy_zero_hp):
    expected = CONTROL_STREAMS[seed].splitlines()
    assert expected, f"empty control for {seed}"
    final = json.loads(expected[-1])
    actual, state, digest = capture_l41_control(tmp_path, seed)
    assert_events_match(expected[:-1], actual)
    assert state == final["state"]
    assert digest == final["digest"]
