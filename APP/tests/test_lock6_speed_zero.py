"""Speed0 plus granted movement must not trap a native or table AI turn."""
import pytest

from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from tests.test_lock2_persistence import ROOT, table_match, act
from tests.test_lock_choices import install


@pytest.mark.parametrize('cause', ['pinned_modifier', 'pinned_rule', 'grappled', 'restrained', 'life_state'])
def test_native_movement_candidates_respect_effective_speed(monkeypatch, tmp_path, cause):
    service, _, mid = table_match(tmp_path)
    engine = service._load_session(mid).engine
    actor = engine.state.actors[engine.state.current_actor_id]
    if cause == 'pinned_modifier':
        engine._add_modifier(actor, 'test:pinned', 'speed_ft', 'ADD', -999, 'SELF', expires_on='START_OF_SELF_NEXT_TURN')
    elif cause == 'life_state':
        actor.life_state = 'DYING'
    else:
        name = 'pinned' if cause == 'pinned_rule' else cause
        engine._apply_condition(actor, 'condition:typed.' + name, 'test:immobile', actor.entity_id,
                                expires_on='START_OF_SELF_NEXT_TURN',
                                data={'rule': {'speed_zero': True}} if cause == 'pinned_rule' else None)
    actor.movement_remaining_ft = 5
    assert engine._effective_speed(actor) == 0
    before = engine.state.model_dump(mode='json'), len(engine.events), engine.roller.counter
    assert engine._movement_candidates(actor) == []  # the core, without a Gate4 plug-in veto
    assert not any(c.kind.value == 'MOVE' for c in engine.legal_candidates())
    policy, _ = service.policies.for_actor(actor.entity_id)
    context = build_decision_context(engine, policy, for_ai=True)
    assert not any(c.kind.value == 'MOVE' for c in context.legal_candidates)
    assert (engine.state.model_dump(mode='json'), len(engine.events), engine.roller.counter) == before


def test_pinned_granted_movement_table_ai_leaves_turn_and_recovers(monkeypatch, tmp_path):
    source = 'test:pinned-setup:'
    def actions(info):
        return [ActionDefinition(source_definition_id=source + info['actor_id'], display_name='Practice being pinned',
            owner_id=info['actor_id'], economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
            parameters={'typed': {'numbers': info['numbers'], 'effects': [
                {'type': 'speed', 'becomes': 0, 'applies_to': 'self', 'duration': 'until_start_of_your_next_turn'},
                {'type': 'movement', 'distance_ft': 5, 'applies_to': 'self'}]}})]
    install(monkeypatch, 'compile_actions', actions)
    service, table, mid = table_match(tmp_path)
    actor_id = service._load_session(mid).engine.state.current_actor_id
    assert act(table, mid, source)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[actor_id]
    assert loaded.engine._effective_speed(actor) == 0 and actor.movement_remaining_ft > 0
    assert table.state(mid)['menu']['moves'] == []
    assert loaded.verify()['status'] == 'PASS'
    sequence = loaded.engine.state.event_sequence
    service.set_controller_mode(mid, actor_id=actor_id, controller_mode='LOCAL_AUTO')
    for _ in range(5):
        assert service.local_step(mid)['status'] == 'COMMITTED'
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        if loaded.engine.state.current_actor_id != actor_id:
            break
    assert loaded.engine.state.current_actor_id != actor_id
    assert not any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == actor_id
                   for e in loaded.engine.events if e.sequence > sequence)
    assert loaded.verify()['status'] == 'PASS'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    recovered = service._load_session(mid).engine
    assert recovered.state.current_actor_id == actor_id
    assert recovered._effective_speed(recovered.state.actors[actor_id]) > 0
    assert recovered._movement_candidates(recovered.state.actors[actor_id])


def test_positive_speed_keeps_granted_allowance_and_move_geometry(tmp_path):
    service, _, mid = table_match(tmp_path)
    engine = service._load_session(mid).engine
    actor = engine.state.actors[engine.state.current_actor_id]
    actor.movement_remaining_ft = 5
    before = engine._movement_candidates(actor)
    assert before and all(c.movement_cost_ft <= 5 for c in before)
    assert all(c.destination != actor.position for c in before)
    assert engine._movement_candidates(actor) == before


@pytest.mark.parametrize('expires', ['START_OF_SELF_NEXT_TURN', 'START_OF_SOURCE_NEXT_TURN'])
def test_expiring_speed_zero_refreshes_allowance_before_standing_up(tmp_path, expires):
    service, _, mid = table_match(tmp_path)
    engine = service._load_session(mid).engine
    actor = engine.state.actors[engine.state.current_actor_id]
    engine._add_modifier(actor, 'test:pinned', 'speed_ft', 'ADD', -999, 'SELF', expires_on=expires)
    engine._apply_condition(actor, 'condition:typed.prone', 'test:fall', actor.entity_id, expires_on='STAND_UP')
    actor.movement_remaining_ft = 0
    engine._system_start_turn()
    speed = engine._effective_speed(actor)
    assert speed > 0
    assert actor.movement_remaining_ft == speed - speed // 2
    assert not any(c.expires_on == 'STAND_UP' for c in actor.conditions.values())
    assert engine._movement_candidates(actor)
