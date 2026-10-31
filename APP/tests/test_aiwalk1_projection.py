"""Query bounds, native gates and knowledge isolation for walking forecasts."""
from copy import deepcopy

import pytest

from combat import ext, flight_decision, ground_decision
from combat.gate2_runtime_models import ActionDefinition, DiceSpec, Position
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary
from combat.target_knowledge import actors_for
from tests.h1_support import ROOT, ME, FOE, duel
from tests.test_aiwalk1 import walking_duel


def inputs(engine):
    actor = engine.state.actors[ME]
    return actor, tuple(engine.legal_candidates()), actors_for(engine, actor)


def multiattack_duel():
    """An Eui's stock shape: a 7-damage blast usable from 10 feet and a
    two-strike 1d4+4 assault (13 together) that only reaches 5 feet."""
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

    def attack(kind, damage):
        return {'type': 'attack', 'attack_kind': kind, 'attack_bonus': 100,
                'on_hit': [{'type': 'damage', 'flat': damage, 'damage_type': 'force'}]}
    blast = ActionDefinition(source_definition_id='test:aiwalk1.blast', display_name='Blast',
        owner_id=ME, economy='ACTION', resolution_kind='TYPED', target_kind='HOSTILE_ENTITY',
        range_ft=60, parameters={'expected_damage': 7, 'typed': {'effects': [attack('ranged', 7)]}})
    assault = ActionDefinition(source_definition_id='test:aiwalk1.paired_assault',
        display_name='Paired Assault', owner_id=ME, economy='ACTION', resolution_kind='MULTI_ATTACK',
        target_kind='HOSTILE_ENTITY', reach_ft=5, attack_count=2,
        damage=DiceSpec(count=1, sides=4, modifier=4),
        parameters={'typed': {'effects': [attack('melee', 5)]}})
    for action in (blast, assault):
        engine.action_catalog[action.source_definition_id] = action
    actor.action_ids = (blast.source_definition_id, assault.source_definition_id)
    policy = PolicyLibrary(ROOT).fallback().model_copy(update={
        'weights': {'immediate_effect': 1, 'position': 1}, 'action_priorities': {},
        'target_priorities': {}, 'position_relative': True})
    return engine, policy


def test_fixture_baseline_takes_native_enabling_move_without_projection(monkeypatch):
    """Baseline without walk forecasts (AIWALK1F2 finding 2).

    Intent: with no projection annotations, the AI's own planner still uses its
    native rule (own owned strike, own reach) and steps to the square where the
    4 ft ranged shot is joined by the 40 ft blade. The weak shot must stay a legal
    option, and the pick is the enabling step within 5 ft of the foe, not a
    forecast credit.
    """
    engine, policy = walking_duel()
    ext._load()
    monkeypatch.setitem(ext._HOOKS, 'ai_decision_annotations', [])
    context = build_decision_context(engine, policy, for_ai=True)
    assert any(c.source_definition_id.endswith('weak_shot') for c in context.legal_candidates)
    pick = LocalDeterministicController().choose_primary_action(context)
    selected = next(c for c in context.legal_candidates if c.candidate_id == pick.intent.candidate_id)
    assert selected.kind == 'MOVE', selected.source_definition_id
    assert engine._distance_actor_to_actor(engine.state.actors[ME], engine.state.actors[FOE],
                                          actor_position=selected.destination) <= 5


def test_projection_is_read_only_and_cached_per_endpoint(monkeypatch):
    engine, _ = walking_duel()
    # An unavailable higher-valued strike prevents the upper-bound early exit,
    # so duplicate destination routes really exercise the per-decision cache.
    source = 'test:aiwalk1.unavailable'
    old = engine.action_catalog['test:aiwalk1.strong_blade']
    engine.action_catalog[source] = old.model_copy(update={'source_definition_id': source,
        'parameters': {**old.parameters, 'expected_damage': 100, 'requires_condition': 'test:missing'}})
    engine.state.actors[ME].action_ids += (source,)
    actor, candidates, known = inputs(engine)
    moves = [c for c in candidates if c.kind == 'MOVE']
    candidates += tuple(c.model_copy(update={'candidate_id': c.candidate_id + ':same'}) for c in moves)
    before = deepcopy(engine.state.model_dump(mode='json'))
    events = deepcopy(engine.events)
    rolls = deepcopy(engine.rolls)
    native, calls = flight_decision.native_attack_candidates, []
    def counted(view, mover, foes, attacks):
        calls.append((mover.position.x, mover.position.y, mover.movement_remaining_ft))
        return native(view, mover, foes, attacks)
    monkeypatch.setattr(flight_decision, 'native_attack_candidates', counted)
    values = ground_decision.attack_values(engine, actor, candidates, known)
    assert values and all(v['walk_attack']['gain'] == 36 for v in values.values())
    assert len(calls) == len(set(calls)) <= 8
    assert all(remaining == 0 for _, _, remaining in calls)
    assert engine.state.model_dump(mode='json') == before
    assert engine.events == events and engine.rolls == rolls
    actor.action_available = False
    calls.clear()
    assert ground_decision.attack_values(engine, actor, candidates, known) == {}
    assert calls == []  # no stale query survives a new decision/economy


def test_at_most_eight_prospective_endpoints(monkeypatch):
    engine, _ = walking_duel()
    engine.state.actors[ME].movement_remaining_ft = 30
    engine.state.actors[FOE].position = Position(x=7, y=6)
    source = 'test:aiwalk1.strong_blade'
    engine.action_catalog[source] = engine.action_catalog[source].model_copy(update={'reach_ft': 15})
    actor, candidates, known = inputs(engine)
    assert sum(c.kind == 'MOVE' for c in candidates) > 8
    native, calls = flight_decision.native_attack_candidates, []
    def counted(*args):
        calls.append(args[1].position)
        native(*args)
        return ()  # no endpoint reaches the bound: exercise the full budget
    monkeypatch.setattr(flight_decision, 'native_attack_candidates', counted)
    values = ground_decision.attack_values(engine, actor, candidates, known)
    assert values == {} and len(calls) == 8


def test_no_projection_when_strongest_attack_already_available(monkeypatch):
    engine, _ = walking_duel()
    engine.state.actors[FOE].position = Position(x=4, y=6)
    actor, candidates, known = inputs(engine)
    monkeypatch.setattr(flight_decision, 'query_copy', lambda *a: pytest.fail('unnecessary engine copy'))
    assert ground_decision.attack_values(engine, actor, candidates, known) == {}


@pytest.mark.parametrize('gate', ['candidate_allowed', 'ai_candidate_allowed'])
def test_native_plugin_veto_gets_no_attack_credit(monkeypatch, gate):
    engine, _ = walking_duel()
    actor, candidates, known = inputs(engine)
    ext._load()
    def veto(view, mover, candidate, action):
        return False if action and action.source_definition_id.endswith('strong_blade') else None
    monkeypatch.setitem(ext._HOOKS, gate, [*ext._HOOKS.get(gate, []), veto])
    assert ground_decision.attack_values(engine, actor, candidates, known) == {}


def test_unknown_foe_cannot_grant_attack_credit(monkeypatch):
    from combat import target_knowledge
    engine, _ = walking_duel()
    actor, candidates, known = inputs(engine)
    native = target_knowledge.knowledge
    def unknown(view, viewer, target, *args, **kwargs):
        return None if target.entity_id == FOE else native(view, viewer, target, *args, **kwargs)
    monkeypatch.setattr(target_knowledge, 'knowledge', unknown)
    monkeypatch.setattr(flight_decision, 'query_copy', lambda *a: pytest.fail('hidden foe projection'))
    assert ground_decision.attack_values(engine, actor, candidates, known) == {}


def test_prohibited_attack_cannot_grant_move_credit():
    engine, policy = walking_duel()
    actor, candidates, known = inputs(engine)
    policy = policy.model_copy(update={'prohibited_choices': ('test:aiwalk1.strong_blade',)})
    assert ground_decision.attack_values(engine, actor, candidates, known, policy=policy) == {}


@pytest.mark.parametrize('mode', ['fly', 'climb', 'jump', 'jump_down'])
def test_only_ordinary_walks_are_queried(mode):
    engine, _ = walking_duel()
    actor, candidates, known = inputs(engine)
    candidates = tuple(c.model_copy(update={'metadata': {**c.metadata, 'movement_mode': mode}})
                       if c.kind == 'MOVE' else c for c in candidates)
    assert ground_decision.attack_values(engine, actor, candidates, known) == {}


def test_player_menu_unchanged_and_all_ai_destinations_retained():
    engine, policy = walking_duel()
    player = build_decision_context(engine, policy, for_ai=False)
    context = build_decision_context(engine, policy, for_ai=True)
    assert not any('walk_attack' in c.metadata for c in player.legal_candidates)
    assert {c.candidate_id for c in player.legal_candidates} == {c.candidate_id for c in context.legal_candidates}
    rows = tuple(c for c in context.legal_candidates if c.kind == 'MOVE')
    order = ext.run_strict('ai_movement_order', context, rows)[0]
    assert len(order) == len(rows) and set(order) == {c.candidate_id for c in rows}


def test_multiattack_walk_credit_counts_every_strike():
    """AIWALK1F4 finding 1: a two-strike 1d4+4 assault is worth 13, not one strike's 6.

    With a per-strike estimate the assault (6) lost to the 7-damage blast usable
    from here and was dropped before its prospective legality was ever queried,
    so stepping into its 5-foot reach earned no credit (stock: An Eui's Paired
    Bi Shou Assault against Scouring Destructive Blast).
    """
    engine, _ = multiattack_duel()
    actor, candidates, known = inputs(engine)
    assault = engine.action_catalog['test:aiwalk1.paired_assault']
    assert ground_decision.attack_value(assault) == 13
    # Half points are kept to the whole-action total: one strike alone is 6.
    assert ground_decision.attack_value(assault.model_copy(update={'attack_count': 1})) == 6
    foe = engine.state.actors[FOE]
    enabling = {c.candidate_id for c in candidates if c.kind == 'MOVE'
                and c.destination is not None
                and engine._distance_actor_to_actor(actor, foe, actor_position=c.destination) <= 5}
    assert enabling
    # The assault is not offered at the current distance; only the blast is.
    assert not any(c.source_definition_id.endswith('paired_assault') for c in candidates)
    values = ground_decision.attack_values(engine, actor, candidates, known)
    # The upper-bound early exit may stop after the first credited endpoint,
    # but no destination outside the assault's reach may earn credit.
    assert values and set(values) <= enabling
    assert all(row['walk_attack'] == {'here': 7, 'best': 13, 'gain': 6} for row in values.values())
