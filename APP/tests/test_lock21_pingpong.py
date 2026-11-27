"""Repeated table decisions must not walk a movement segment in circles."""
import json

from combat.gate5_service import CombatService
from combat.gate4_context import build_decision_context
from combat.gate4_models import DecisionContext
from tests.test_tabletop_hunt6 import table_fight, LEFT, ROOT
from combat.gate4_controller import LocalDeterministicController
from combat.gate2_runtime_models import Position
import pytest


def test_two_cell_range_plateau_through_table_commits(tmp_path):
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    # Isolate Hunt77's two equally desirable range-band cells. Candidates are
    # real legal engine moves, committed through the Table, with real turn and
    # movement budgets. Keep End Turn as the non-movement alternative.
    cells = (Position(x=1, y=4), Position(x=2, y=4))
    engine = combat._load_session(mid).engine
    first = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination == cells[0])
    assert table.act(mid, first.candidate_id, first.decision_id, first.state_version, 0, [])['status'] == 'COMMITTED'
    visited = [cells[0]]
    for _ in range(8):
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        engine = loaded.engine
        if engine.state.current_actor_id != LEFT:
            break
        policy, _ = combat.policies.for_actor(LEFT)
        ctx = build_decision_context(engine, policy, for_ai=True)
        ctx = ctx.model_copy(update={'legal_candidates': tuple(c for c in ctx.legal_candidates
            if c.kind == 'END_TURN' or c.kind == 'MOVE' and c.destination in cells)})
        choice = LocalDeterministicController().choose_primary_action(ctx)
        candidate = next(c for c in ctx.legal_candidates if c.candidate_id == choice.intent.candidate_id)
        if candidate.kind == 'MOVE':
            assert candidate.destination not in visited
            visited.append(candidate.destination)
        assert table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version, 0, [])['status'] == 'COMMITTED'
    else:
        raise AssertionError('The movement segment did not finish')
    assert visited == list(cells)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('boundary', ['TURN_STARTED', 'TURN_ENDED', 'REACTION_RESOLVED',
    'DAMAGE_COMMITTED', 'HEALING_APPLIED', 'CONDITION_APPLIED', 'CONDITION_REMOVED', 'ACTION', 'OTHER_MOVE'])
def test_meaningful_intervention_resets_segment_without_mutation(boundary):
    from types import SimpleNamespace
    from combat.movement_history import endpoints
    move = SimpleNamespace(event_type='MOVEMENT_COMMITTED', actor_id=LEFT,
        source_definition_id='system:combat.movement', payload={
            'path': [{'x': 1, 'y': 4}, {'x': 2, 'y': 4, 'z': 1}],
            'destination': {'x': 2, 'y': 4, 'z': 1}})
    engine = SimpleNamespace(events=[move])
    assert endpoints(engine, LEFT) == (Position(x=1, y=4), Position(x=2, y=4, z=1))
    stop = SimpleNamespace(event_type=boundary, actor_id=LEFT, payload={})
    if boundary == 'ACTION':
        stop.event_type = 'INTENT_ACCEPTED'
        stop.payload = {'kind': 'ACTION'}
    if boundary == 'OTHER_MOVE':
        stop.event_type, stop.actor_id = 'MOVEMENT_COMMITTED', 'other'
    engine.events.append(stop)
    assert endpoints(engine, LEFT) == ()
    assert engine.events == [move, stop]


def test_old_context_and_movement_only_domain_remain_usable():
    from tests.test_combat_gate4_controller import engine, choose, AN
    _, ctx = choose(engine('L21-OLD-CONTEXT'), AN)
    payload = ctx.model_dump(mode='json')
    payload.pop('movement_endpoints', None)
    legacy = DecisionContext.model_validate(payload)
    assert 'movement_endpoints' not in legacy.model_dump(mode='json')
    move = next(c for c in ctx.legal_candidates if c.kind == 'MOVE')
    only_move = ctx.model_copy(update={'legal_candidates': (move,), 'movement_endpoints': (move.destination,)})
    assert LocalDeterministicController().choose_primary_action(only_move).intent.candidate_id == move.candidate_id


def test_table_ai_plateau_does_not_revisit_endpoints_and_reload_keeps_history(tmp_path):
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    positions = []
    previous_sequence = len(combat._load_session(mid).engine.events)
    moves = 0
    for step in range(32):
        engine = combat._load_session(mid).engine
        if engine.state.current_actor_id != LEFT:
            break
        result = table.auto_step(mid, 0, [])
        assert result['status'] == 'COMMITTED', result
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        assert session.engine.state == combat._load_session(mid).engine.state
        for event in session.engine.events[previous_sequence:]:
            if event.event_type == 'INTENT_ACCEPTED' and event.payload.get('kind') != 'MOVE':
                positions.clear()  # attacking/guarding can make a return trip useful
            if event.event_type == 'MOVEMENT_COMMITTED' and event.actor_id == LEFT:
                path = event.payload['path']
                if not positions:
                    positions.append(path[0])
                assert event.payload['destination'] not in positions
                positions.append(event.payload['destination'])
                moves += 1
        previous_sequence = len(session.engine.events)
        policy, _ = combat.policies.for_actor(session.engine.state.current_actor_id)
        context = build_decision_context(session.engine, policy, for_ai=True)
        assert DecisionContext.model_validate_json(context.model_dump_json()) == context
    else:
        raise AssertionError('The turn did not finish')
    assert moves > 0
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def corridor_table(tmp_path, *, hazard=False):
    """Seal a narrow native arena so real paths and hazard rolls replay from disk."""
    from combat.gate2_runtime_content import AN, LING
    from combat.tabletop_service import TabletopService
    from tests.test_hidden_targeting import turn

    arena = json.loads((ROOT / 'combat/rules/arenas/Pillar_Arena.json').read_text())
    arena.pop('retired', None)  # preserve the historical sealed geometry
    arena['width_squares'], arena['height_squares'] = 12, 8
    arena['terrain_regions'] = [{'terrain_type': 'BLOCKED', 'movement_cost': 1,
        'cells': [{'x': x, 'y': y} for x in range(12) for y in range(8) if y != 4]}]
    if hazard:
        arena['terrain_regions'].append({'terrain_type': 'QI_HAZARD', 'movement_cost': 1,
            'cells': [{'x': 3, 'y': 4}]})
    combat = CombatService(ROOT, tmp_path)
    # After the two initiative rolls this seed gives a failed hazard save.
    session = combat.persistence.create_match(match_seed='LOCK21-DAMAGE-2', battlefield=arena,
        roster_setup={'primary_actor_ids': [AN, LING], 'team_by_actor': {AN: 'a', LING: 'b'},
            'starting_positions': {AN: {'x': 1, 'y': 4}, LING: {'x': 10, 'y': 4}}})
    for actor_id in (AN, LING):
        combat.set_controller_mode(session.match_id, actor_id=actor_id, controller_mode='MANUAL')
    table = TabletopService(combat, tmp_path)
    turn(table, session.match_id, AN)
    return combat, table, session.match_id, AN


def move_candidate(engine, x):
    return next(c for c in engine.legal_candidates()
                if c.kind == 'MOVE' and c.destination == Position(x=x, y=4))


def commit_move(table, mid, candidate):
    result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version, 0, [])
    assert result['status'] == 'COMMITTED', result


def choice_with_retreat(context, destination):
    # Keep End Turn: a movement-only menu intentionally bypasses suppression.
    context = context.model_copy(update={'legal_candidates': tuple(c for c in context.legal_candidates
        if c.kind == 'END_TURN' or c.kind == 'MOVE' and c.destination == destination)})
    return LocalDeterministicController().choose_primary_action(context)


def test_hazard_damage_resets_earlier_endpoints_through_table_reload(tmp_path):
    combat, table, mid, actor_id = corridor_table(tmp_path, hazard=True)
    engine = combat._load_session(mid).engine
    commit_move(table, mid, move_candidate(engine, 2))
    before = CombatService(ROOT, tmp_path)._load_session(mid).engine
    policy, _ = combat.policies.for_actor(actor_id)
    previous = build_decision_context(before, policy, for_ai=True)
    assert previous.movement_endpoints == (Position(x=1, y=4), Position(x=2, y=4))
    hp_before, sequence = before.state.actors[actor_id].current_hp, len(before.events)
    commit_move(table, mid, move_candidate(before, 3))

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    events = engine.events[sequence:]
    # This is real map damage during MOVE, with no other reset to mask the bug.
    assert [e.payload['kind'] for e in events if e.event_type == 'INTENT_ACCEPTED'] == ['MOVE']
    assert not any(e.event_type in {'TURN_STARTED', 'TURN_ENDED', 'REACTION_RESOLVED',
        'HEALING_APPLIED', 'CONDITION_APPLIED', 'CONDITION_REMOVED'} for e in events)
    damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED']
    assert len(damage) == 1 and damage[0].source_definition_id == 'system:battlefield.qi_hazard'
    assert damage[0].target_ids == (actor_id,) and damage[0].payload['hp_damage'] > 0
    assert engine.state.actors[actor_id].current_hp == hp_before - damage[0].payload['hp_damage']
    receipts = [e for e in events if e.event_type == 'MOVEMENT_COMMITTED']
    assert len(receipts) == 1 and receipts[0].actor_id == actor_id
    assert receipts[0].source_definition_id == 'system:combat.movement'
    assert events.index(damage[0]) < events.index(receipts[0])
    assert receipts[0].payload['path'] == [{'x': 2, 'y': 4}, {'x': 3, 'y': 4}]

    context = build_decision_context(engine, policy, for_ai=True)
    # The receipt follows damage, but its starting square predates damage.
    assert context.movement_endpoints == (Position(x=3, y=4),)
    assert context.movement_endpoints == build_decision_context(
        combat._load_session(mid).engine, policy, for_ai=True).movement_endpoints
    for destination in previous.movement_endpoints:
        candidate = move_candidate(engine, destination.x)
        assert candidate.candidate_id in choice_with_retreat(context, destination).record.legal_alternatives
        stale = context.model_copy(update={'movement_endpoints': previous.movement_endpoints})
        assert candidate.candidate_id not in choice_with_retreat(stale, destination).record.legal_alternatives
    commit_move(table, mid, move_candidate(engine, 1))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[actor_id].position == Position(x=1, y=4)
    assert build_decision_context(loaded.engine, policy, for_ai=True).movement_endpoints == (
        Position(x=1, y=4), Position(x=3, y=4))
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('destination', [0, 2])
def test_old_ground_crossing_and_intermediate_destination_stay_eligible(tmp_path, destination):
    combat, table, mid, actor_id = corridor_table(tmp_path)
    commit_move(table, mid, move_candidate(combat._load_session(mid).engine, 3))
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    policy, _ = combat.policies.for_actor(actor_id)
    context = build_decision_context(engine, policy, for_ai=True)
    assert context.movement_endpoints == (Position(x=1, y=4), Position(x=3, y=4))
    candidate = move_candidate(engine, destination)
    assert Position(x=2, y=4) in candidate.canonical_path
    if destination == 0:
        assert Position(x=1, y=4) in candidate.canonical_path[1:-1]
    assert candidate.candidate_id in choice_with_retreat(context, candidate.destination).record.legal_alternatives
    commit_move(table, mid, candidate)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[actor_id].position == candidate.destination
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
