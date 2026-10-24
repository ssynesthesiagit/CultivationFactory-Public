"""The portable attack resolver shares SOL132's pre-d20 concealment policy."""
from combat import target_knowledge, targeting
from tests.h1_support import script
from tests.test_c3ar_runtime_executability import (
    runtime_package, adapter, bundle, runtime_engine, req, SOURCE_ACTOR_ID,
)


def test_portable_unseen_attack_rolls_concealment_before_its_d20(bundle, monkeypatch):
    monkeypatch.setattr(targeting, 'rules', lambda: dict(targeting.LEGACY_POLICY))
    engine = runtime_engine(bundle)
    actor, target = engine.state.actors[SOURCE_ACTOR_ID], engine.state.actors['dummy:target']
    target_knowledge.observe(engine)
    engine._apply_condition(target, 'condition:typed.invisible', 'test:invisible', target.entity_id,
                            expires_on='UNTIL_REMOVED')
    before = target.current_hp
    script(engine, [1])
    engine.execute_action(req('action:fire.flame_lash', target_id=target.entity_id))
    assert target.current_hp == before and not actor.action_available
    assert any(e.payload.get('miss_chance_percent') == 50 and e.payload['missed'] for e in engine.events)
    assert not any(e.event_type == 'ATTACK_ROLLED' for e in engine.events)


def test_portable_unseen_attack_has_no_default_concealment_roll(bundle):
    engine = runtime_engine(bundle)
    target = engine.state.actors['dummy:target']
    target_knowledge.observe(engine)
    engine._apply_condition(target, 'condition:typed.invisible', 'test:invisible', target.entity_id,
                            expires_on='UNTIL_REMOVED')
    script(engine, [1, 1])
    engine.execute_action(req('action:fire.flame_lash', target_id=target.entity_id))
    assert any(e.event_type == 'ATTACK_ROLLED' for e in engine.events)
    assert not any('miss_chance_percent' in e.payload for e in engine.events)
    assert not any(r.reason == 'CONCEALMENT_MISS_CHANCE' for r in engine.rolls)


def test_portable_attack_does_not_follow_unseen_movement(bundle):
    from combat.gate2_runtime_models import Position
    engine = runtime_engine(bundle)
    target = engine.state.actors['dummy:target']
    target_knowledge.observe(engine)
    engine._apply_condition(target, 'condition:typed.invisible', 'test:invisible', target.entity_id,
                            expires_on='UNTIL_REMOVED')
    target.position = Position(x=4, y=2)
    hp = target.current_hp
    engine.execute_action(req('action:fire.flame_lash', target_id=target.entity_id))
    assert target.current_hp == hp
    assert any(e.event_type == 'ATTACK_LOCATION_MISSED' for e in engine.events)
    assert not any(e.event_type == 'ATTACK_ROLLED' for e in engine.events)
