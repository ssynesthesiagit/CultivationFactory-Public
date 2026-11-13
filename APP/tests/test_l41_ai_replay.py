"""Seeded AI fight event streams and full-state replay controls."""
import json
from itertools import zip_longest
from pathlib import Path

import pytest

from combat.area_knowledge import bind_origin_permissions
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.legacy_fight_support import legacy_zero_hp
from tests.r1i_service_support import ROOT, fixture
from tests.replay_assertions import assert_replay_equal

SEEDS = tuple(f"SOL41-REPLAY-{i}" for i in range(3))
CONTROL_DIR = Path(__file__).parent / "data" / "l41_ai_replay"


def capture_l41_control(tmp_path, seed):
    """Replay the shared fixture and return diagnostic event lines and a digest."""
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
    return lines, canonical_sha256(payload)


@pytest.mark.parametrize("seed", SEEDS)
def test_ai_fight_matches_cycle_control_bytes(tmp_path, seed, legacy_zero_hp):
    expected = (CONTROL_DIR / f"{seed}.jsonl").read_text(encoding="utf-8").splitlines()
    assert expected, f"empty control for {seed}"
    expected_digest = json.loads(expected[-1])["digest"]
    actual, digest = capture_l41_control(tmp_path, seed)
    for index, (want, got) in enumerate(zip_longest(expected[:-1], actual)):
        assert want == got, f"first differing event {index}: expected {want!r}; got {got!r}"
    assert digest == expected_digest
