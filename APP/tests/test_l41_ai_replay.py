"""Seeded AI fight events, rolls, genesis and full-state replay controls.

For intentional fight changes, re-record in the same commit from APP with:
python tools/record_l41_controls.py tests/l41_replay_controls.py
"""
import json
from itertools import zip_longest

import pytest

from combat.area_knowledge import bind_origin_permissions
from combat.canonical import canonical_text
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.l41_replay_controls import CONTROL_STREAMS
from tests.legacy_fight_support import legacy_zero_hp
from tests.r1i_service_support import ROOT, fixture
from tests.replay_assertions import assert_replay_equal
from tools.record_l41_controls import control_stream, write_controls

SEEDS = tuple(f"SOL41-REPLAY-{i}" for i in range(3))


def capture_l41_control(tmp_path, seed):
    """Replay the shared fixture and return canonical events and directly checked records."""
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
    assert all(isinstance(key, str) and type(value) is int and value == 0
               for key, value in permissions.items())

    lines = []
    for event in payload["events"]:
        # Compare the genesis payload separately, just like the roll records.
        details = {} if event["sequence"] == 1 else event["payload"]
        row = {
            "step": event["sequence"], "actor": event["actor_id"],
            "kind": event["event_type"], "action": event["source_definition_id"],
            "targets": event["target_ids"], "outcome": details,
            "state_version": event["state_version"],
            "intent": event["trigger_or_intent_id"], "transaction": event["transaction_id"],
        }
        lines.append(canonical_text(row))
    return lines, {
        "state": payload["state"],
        "genesis": canonical_text(payload["events"][0]["payload"]),
        "rolls": [canonical_text(roll) for roll in payload["rolls"]],
    }


def assert_lines_match(expected, actual, kind):
    for index, (want, got) in enumerate(zip_longest(expected, actual)):
        assert want == got, f"first differing {kind} {index}: expected {want!r}; got {got!r}"


@pytest.mark.parametrize("kind", ("event", "roll", "genesis"))
def test_control_mutation_reports_first_differing_event(kind):
    expected = ["unchanged", "original record", "last record"]
    actual = expected.copy()
    actual[1] = "altered record"
    with pytest.raises(AssertionError, match=f"first differing {kind} 1:") as exc:
        assert_lines_match(expected, actual, kind)
    assert expected[1] in str(exc.value)
    assert "altered record" in str(exc.value)


@pytest.mark.parametrize("seed", SEEDS)
def test_ai_fight_matches_cycle_control_bytes(tmp_path, seed, legacy_zero_hp):
    expected = CONTROL_STREAMS[seed].splitlines()
    assert expected, f"empty control for {seed}"
    final = json.loads(expected[-1])
    actual, records = capture_l41_control(tmp_path, seed)
    # Failed CI jobs return captured stdout, but may discard their temporary files.
    output = tmp_path / "actual_controls.py"
    write_controls(output, {seed: control_stream(actual, records)})
    print(f"L41_CONTROL_BEGIN {seed}")
    print(output.read_text(encoding="utf-8"), end="")
    print(f"L41_CONTROL_END {seed}")
    assert_lines_match(expected[:-1], actual, "event")
    assert_lines_match([final["genesis"]], [records["genesis"]], "genesis")
    assert_lines_match(final["rolls"], records["rolls"], "roll")
    assert records["state"] == final["state"]
