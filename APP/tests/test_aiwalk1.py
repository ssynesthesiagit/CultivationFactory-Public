"""Ordinary walking must consider legal attacks unlocked this turn."""
from combat.gate2_runtime_models import ActionDefinition, Position
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from tests.h1_support import ROOT, ME, FOE, duel


def walking_duel():
    engine = duel([])
    actor, foe = engine.state.actors[ME], engine.state.actors[FOE]
    actor.position = Position(x=3, y=6)
    foe.position = Position(x=5, y=6)
    actor.movement_remaining_ft = 5
    foe.reaction_available = False
    engine.grid.blocked.clear()
    engine.grid.opaque.clear()
    engine.grid.qi_hazard.clear()
    engine.grid.base_movement_cost.clear()
    actions = []
    for name, damage, ranged in [('weak_shot', 4, True), ('strong_blade', 40, False)]:
        action = ActionDefinition(source_definition_id='test:aiwalk1.' + name,
            display_name=name.replace('_', ' ').title(), owner_id=ME, economy='ACTION',
            resolution_kind='TYPED', target_kind='HOSTILE_ENTITY',
            range_ft=60 if ranged else None, reach_ft=None if ranged else 5,
            parameters={'expected_damage': damage, 'typed': {'effects': [{
                'type': 'attack', 'attack_kind': 'ranged' if ranged else 'melee',
                'attack_bonus': 100, 'on_hit': [
                    {'type': 'damage', 'flat': damage, 'damage_type': 'force'}]}]}})
        engine.action_catalog[action.source_definition_id] = action
        actions.append(action.source_definition_id)
    actor.action_ids = tuple(actions)
    policy = PolicyLibrary(ROOT).fallback().model_copy(update={
        'weights': {'immediate_effect': 1, 'position': 1}, 'action_priorities': {},
        'target_priorities': {}, 'position_relative': True})
    return engine, policy


def test_walk_then_native_strong_attack():
    engine, policy = walking_duel()
    controller = LocalDeterministicController()
    context = build_decision_context(engine, policy, for_ai=True)
    attacks = [c for c in context.legal_candidates if c.kind == 'ACTION']
    assert any(c.source_definition_id.endswith('weak_shot') for c in attacks)
    assert not any(c.source_definition_id.endswith('strong_blade') for c in attacks)
    choice = controller.choose_primary_action(context)
    assert choice.intent.destination is not None, choice.intent
    assert engine._distance_actor_to_actor(engine.state.actors[ME], engine.state.actors[FOE],
                                          actor_position=choice.intent.destination) <= 5
    engine.execute_intent(choice.intent)
    assert engine.state.actors[ME].action_available
    context = build_decision_context(engine, policy, for_ai=True)
    choice = controller.choose_primary_action(context)
    selected = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
    assert selected.source_definition_id.endswith('strong_blade')
    hp = engine.state.actors[FOE].current_hp
    engine.execute_intent(choice.intent)
    assert engine.state.actors[FOE].current_hp < hp
