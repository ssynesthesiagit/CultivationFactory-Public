"""Seeded AI fight fingerprints, including the approved movement cycle control.

This deliberately covers unaffected fights (no Blood Pump or Golden Bell).
Each fingerprint includes every field of events, rolls and persisted state;
timestamps from the nonmechanical controller journal are not combat bytes.
Lock round 24 intentionally changes these seeds: at event 16 the owner Dodges
instead of moving to a repeated endpoint. The old complete fingerprints and
every changed field are retained in astra/lock24-run/l41-comparison.json.
Exact complete and projected fingerprints retain the prior checks for integer
Strength and the natural Unarmed Strike action from the admitted lock lanes.
"""
import pytest
from tests.legacy_fight_support import legacy_zero_hp

from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.r1i_service_support import ROOT, fixture

WITHOUT_STRENGTH_FINGERPRINTS = {
    'SOL41-REPLAY-0': '671b47e3b4311a5ede071e395e19336de3bb0c207c21eafa22736abd4d8a3eb3',
    'SOL41-REPLAY-1': '8fe24e82240ee12e0699e26244cc852e6e127a1b83eb85e4fcbf4a549d296567',
    'SOL41-REPLAY-2': '98a949e7479e81087c46b5fcd876de7c1ef36c38cb69ecee94b6e541d6bf030c',
}

WITHOUT_STRENGTH_OR_UNARMED_FINGERPRINTS = {
    'SOL41-REPLAY-0': 'd0ce838152765155824c5839704ae949faf6f44745a6e4f680f7ffae7d0cb28c',
    'SOL41-REPLAY-1': '5618e2ffc3e57c9672c1b46c9a7ca3d99062d1c48d27d4f3687fcdaa4e93a275',
    'SOL41-REPLAY-2': '4d90e8d1cb5d5ca3b5c0aefe329996721db6c742094a65f50b65887046c84b0f',
}


@pytest.mark.parametrize("seed,expected", [
    ("SOL41-REPLAY-0", "a1e78d667584b7c991a369e8eb4b0966a767b685a0e383cafc721be292444d7b"),
    ("SOL41-REPLAY-1", "7a8659481289d675a22baf8e6d9091a2306dceda7c507335187327c569f668cf"),
    ("SOL41-REPLAY-2", "84973f130eb71bc661420c8e1b9f0558ae933b298e74f84b813a794e0bd5184f"),
])
def test_ai_fight_matches_cycle_control_bytes(tmp_path, seed, expected, legacy_zero_hp):
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
        assert loaded.engine.state.model_dump(mode="json") == current.engine.state.model_dump(mode="json")
        if loaded.engine.state.terminal_result is not None:
            break
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    payload = {"state": loaded.engine.state.model_dump(mode="json"),
        "events": [e.model_dump(mode="json") for e in loaded.engine.events],
        "rolls": [r.model_dump(mode="json") for r in loaded.engine.rolls]}
    # Check every combat byte, then check each admitted state addition before
    # comparing its exact projection. No event or roll is normalized away.
    assert canonical_sha256(payload) == expected
    for actor in payload['state']['actors'].values():
        assert actor.pop('strength_score') == 14
    assert canonical_sha256(payload) == WITHOUT_STRENGTH_FINGERPRINTS[seed]
    for actor in payload['state']['actors'].values():
        added = [source for source in actor['action_ids'] if source.endswith('.natural.unarmed_strike')]
        assert len(added) == 1
        actor['action_ids'] = [source for source in actor['action_ids'] if source not in added]
    assert canonical_sha256(payload) == WITHOUT_STRENGTH_OR_UNARMED_FINGERPRINTS[seed]
