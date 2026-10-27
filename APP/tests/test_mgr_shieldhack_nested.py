"""Shield-Hacking's first attack can be a nested Remote Trigger dart."""

from combat import ext
from combat.gate2_runtime_models import ActionIntent, Position
from tests.test_auto_lane1 import AN, ME, _engine
from tests.test_sys_placed_effects import _pick, _trapper, _walk


def test_remote_trigger_dart_consumes_denial_before_later_attack():
    engine = _engine(_trapper("TAL_TRAP_REMOTE_TRIGGER"))
    if engine.state.setup_tasks:
        candidate = engine.legal_candidates()[0]
        engine.execute_intent(ActionIntent(intent_id="test:setup", decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=candidate.actor_id))
    owner_id, foe_id = ME, AN
    engine.state.actors[owner_id].resources["resource:core.martial_focus"] = 1
    _pick(engine, "Trap aim: north")
    _pick(engine, "Set Trap", at=(3, 5))
    foe = engine.state.actors[foe_id]
    engine._add_modifier(foe, "test:guard", "armor_class", "ADD", 2, "SELF", expires_on="START_OF_SELF_NEXT_TURN")
    denial = "condition:typed.shield_hacking_rhythm"
    engine._apply_condition(foe, denial, "test:rhythm", owner_id, expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "Shield-Hacking Rhythm"})
    assert sum(v for v in ext.run("ac", engine, foe) if isinstance(v, int)) == -2
    foe.position = Position(x=12, y=5)
    events = _walk(engine, foe_id, [(8, 3), (3, 1)])
    assert any(e.event_type == "ATTACK_ROLLED" and foe_id in e.target_ids for e in events)
    assert not any(c.condition_id == denial for c in foe.conditions.values())
    assert sum(v for v in ext.run("ac", engine, foe) if isinstance(v, int)) == 0
