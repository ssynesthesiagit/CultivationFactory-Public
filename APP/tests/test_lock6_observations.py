"""Knowledge boundaries beyond the imported real table hide/move/reload cases."""
import pytest

from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind, Position
from combat.gate4_context import build_decision_context
from combat.target_knowledge import knowledge, recent_events
from tests.test_lock2_persistence import table_match
from tests.test_lock_choices import install


def case(tmp_path):
    service, _, mid = table_match(tmp_path)
    engine = service._load_session(mid).engine
    viewer = engine.state.actors[engine.state.current_actor_id]
    target = next(a for a in engine.state.actors.values() if a.team_id != viewer.team_id)
    action = ActionDefinition(source_definition_id='test:observed-attack', owner_id=viewer.entity_id,
        display_name='Practice shot', economy=EconomyKind.ACTION, target_kind='HOSTILE_ENTITY',
        resolution_kind='ATTACK', range_ft=60, attack_bonus=100)
    engine.action_catalog[action.source_definition_id] = action
    return service, engine, viewer, target, action


def hide(engine, target):
    engine._apply_condition(target, 'condition:typed.hidden', 'test:hide', target.entity_id, expires_on='UNTIL_REMOVED')


def test_unknown_old_state_has_no_target_or_controller_position_and_queries_are_pure(tmp_path):
    service, engine, viewer, target, action = case(tmp_path)
    hide(engine, target)
    engine.state.observations = {}  # old snapshot's missing field defaults to this
    before = engine.state.model_dump(mode='json'), len(engine.events), engine.roller.counter
    assert engine._action_candidates(viewer, action) == []
    policy, _ = service.policies.for_actor(viewer.entity_id)
    context = build_decision_context(engine, policy, for_ai=True)
    assert target.entity_id not in {actor.entity_id for actor in context.actors}
    assert (engine.state.model_dump(mode='json'), len(engine.events), engine.roller.counter) == before


def test_opposing_sides_keep_independent_last_observations(tmp_path):
    _, engine, viewer, target, action = case(tmp_path)
    old = target.position.model_copy()
    hide(engine, target)
    target.position = Position(x=9, y=4)
    third = viewer.model_copy(update={'entity_id': 'third-observer', 'team_id': 'third-side'})
    assert knowledge(engine, viewer, target, action).position == old
    assert knowledge(engine, third, target, action) is None
    engine.state.observations[third.team_id] = {target.entity_id: Position(x=8, y=4)}
    assert knowledge(engine, third, target, action).position == Position(x=8, y=4)
    assert knowledge(engine, viewer, target, action).position == old


def test_native_guessed_attack_has_no_creature_damage_score(tmp_path):
    service, engine, viewer, target, action = case(tmp_path)
    hide(engine, target)
    target.position = Position(x=9, y=4)
    candidate = engine._action_candidates(viewer, action)[0]
    policy, _ = service.policies.for_actor(viewer.entity_id)
    context = build_decision_context(engine, policy, for_ai=True)
    scored = service.controller._score_candidate(context, candidate, ())
    assert candidate.metadata['expected_damage'] == 0
    assert next(c.value for c in scored.components if c.component == 'immediate_effect') == 0
    assert next(a.position for a in context.actors if a.entity_id == target.entity_id) == candidate.destination


def test_seen_requirement_rechecked_after_defender_checkpoint(monkeypatch, tmp_path):
    _, engine, viewer, target, action = case(tmp_path)
    action.parameters['requires_seen_target'] = True
    candidate = engine._action_candidates(viewer, action)[0]
    engine._active_candidate = candidate
    intent = ActionIntent(intent_id='test:lose-sight', decision_id=candidate.decision_id,
        state_version=candidate.state_version, actor_id=viewer.entity_id, candidate_id=candidate.candidate_id,
        target_ids=candidate.target_ids)
    install(monkeypatch, 'before_attack', lambda *args: hide(engine, target))
    start = engine.state.event_sequence
    with engine._transaction(action.source_definition_id, intent.intent_id, viewer.entity_id):
        assert not engine._resolve_attack_spec(viewer, target, {'range_ft': 60, 'attack_bonus': 100}, intent,
                                               source_definition_id=action.source_definition_id)
    events = [e for e in engine.events if e.sequence > start]
    assert any(e.event_type == 'ATTACK_LOCATION_MISSED' and e.payload['reason'] == 'LOST_SIGHT' for e in events)
    assert not any(e.event_type in ('ATTACK_ROLLED', 'DAMAGE_COMMITTED') for e in events)


def test_hidden_move_stays_private_even_after_later_reveal(tmp_path):
    _, engine, viewer, target, _ = case(tmp_path)
    hide(engine, target)
    target.position = Position(x=9, y=4)
    event = engine._append_event('MOVEMENT_COMMITTED', 'system:combat.move', actor_id=target.entity_id,
        payload={'destination': {'x': 9, 'y': 4}, 'path': [{'x': 8, 'y': 4}, {'x': 9, 'y': 4}]})
    target.conditions.clear()
    assert recent_events(engine, viewer, [event]) == ()


def test_unseen_occupancy_is_learned_only_on_contact_without_a_zero_move_loop(tmp_path):
    _, engine, viewer, target, _ = case(tmp_path)
    old = target.position.model_copy()
    hide(engine, target)
    target.reaction_available = False
    secret = Position(x=viewer.position.x, y=viewer.position.y + 1)
    target.position = secret
    moves = engine._movement_candidates(viewer)
    assert any(c.destination == old for c in moves)  # last seen does not mean occupied
    candidate = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination == secret)
    origin, allowance = viewer.position, viewer.movement_remaining_ft
    engine.execute_intent(ActionIntent(intent_id='test:unseen-contact', actor_id=viewer.entity_id,
        candidate_id=candidate.candidate_id, decision_id=candidate.decision_id, state_version=candidate.state_version,
        destination=candidate.destination))
    assert viewer.position == origin and viewer.movement_remaining_ft == allowance
    assert engine.state.observations[viewer.team_id][target.entity_id] == secret
    assert not any(c.destination == secret for c in engine._movement_candidates(viewer))


def test_unobserved_defeat_does_not_remove_a_remembered_square(tmp_path):
    _, engine, viewer, target, action = case(tmp_path)
    hide(engine, target)
    target.active = False
    candidate = engine._action_candidates(viewer, action)[0]
    assert candidate.metadata['target_knowledge'] == 'LAST_OBSERVED'


def test_blind_attacker_cannot_use_a_seen_target_clause(tmp_path):
    _, engine, viewer, target, action = case(tmp_path)
    action.parameters['requires_seen_target'] = True
    engine._apply_condition(viewer, 'condition:typed.blinded', 'test:blind', target.entity_id, expires_on='UNTIL_REMOVED')
    assert engine._action_candidates(viewer, action) == []
