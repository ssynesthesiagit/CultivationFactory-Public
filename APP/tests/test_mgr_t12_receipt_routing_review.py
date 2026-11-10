"""Four receipt-routing review findings; no model or browser transport."""
import pytest

from combat import flight, movement_routes
from combat.ext import athletics, retribution_second_pass as retribution
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
from tests.h1_support import ME, ALLY, FOE as STOCK_FOE, duel
from tests.auto8f1_table_support import OWNER, FOE, SECOND, fixture, candidate_id
from tests.test_mgr_t12_tumble_pursuit import held_passages, chosen_path, finish


def p(x, y, z=0):
    return Position(x=x, y=y, z=z)


def held_engine():
    engine = duel([athletics.PURSUIT], ally_mids=[])
    actor = engine.state.actors[ME]
    engine.typed_control_modes = {ME: 'MANUAL'}
    engine.state.actors[ALLY].position = p(8, 8)
    engine.state.actors[STOCK_FOE].position = p(9, 4)
    engine._apply_condition(actor, athletics.PURSUIT_PASSAGE, athletics.PURSUIT,
        actor.entity_id, expires_on='END_OF_CURRENT_TURN', data={'ally_id': ''})
    return engine, actor


def test_held_receipt_keeps_straight_running_jump_with_tight_budget():
    engine, actor = held_engine()
    actor.strength_score = 14
    actor.movement_remaining_ft = 15
    before = engine.state.model_dump(mode='json')
    from combat.passage_routes import reachable
    walking = reachable(engine, actor, 15)
    straight = (p(3, 6), p(4, 6), p(5, 6))
    assert any(path == straight and cost == 10 for path, cost, _ in walking.runups)
    jump = next(c for c in engine._movement_candidates(actor)
                if c.destination == p(5, 6, 1) and c.metadata.get('movement_mode') == 'jump')
    assert jump.movement_cost_ft == 15
    assert jump.canonical_path == (*straight, p(5, 6, 1))
    assert engine.state.model_dump(mode='json') == before


@pytest.mark.parametrize('danger', ['opportunity', 'hazard'])
def test_unused_receipt_retains_native_safe_equal_cost_route(danger):
    engine, actor = held_engine()
    actor.movement_remaining_ft = 10
    if danger == 'opportunity':
        engine.state.actors[STOCK_FOE].position = p(3, 4)
    else:
        engine.grid.qi_hazard.add((2, 5))
    before = engine.state.model_dump(mode='json')
    selector = movement_routes.native_selector(engine, actor)
    routes = flight.reachable(engine, actor, grant_ft=10, mode='walk', path_selector=selector)
    path, cost, _ = routes[p(1, 5)]
    assert cost == 10
    assert p(2, 5) not in path
    if danger == 'opportunity':
        assert movement_routes.expected_attacks(engine, actor, path) == []
    else:
        assert not engine._path_intersects_cells(actor, path, engine.grid.qi_hazard)
    for control in ('MANUAL', 'LOCAL_AUTO'):
        engine.typed_control_modes[ME] = control
        native = next(c for c in engine._movement_candidates(actor)
                      if c.destination == p(1, 5) and c.metadata.get('movement_mode', 'walk') == 'walk')
        assert native.movement_cost_ft == cost
        assert p(2, 5) not in native.canonical_path
    # Flight-capable actors use the spatial adapter's same selector.
    actor.fly_speed_ft = 30
    assert p(2, 5) not in flight.reachable(engine, actor, grant_ft=10,
        mode='walk', path_selector=selector)[p(1, 5)][0]
    actor.fly_speed_ft = 0
    assert engine.state.model_dump(mode='json') == before


def test_unequal_ally_crossings_quote_actual_first_entry_spend_and_reload(tmp_path, monkeypatch):
    from tests.test_lock_choices import install
    from combat.relations import relation, ALLY as ALLIED
    install(monkeypatch, 'pass_through', lambda e, a, b: 'difficult' if relation(e, a, b) == ALLIED else None)

    def transform(bundles):
        held_passages(1)(bundles)
        for bundle in bundles:
            bundle['actor_template']['speed_ft'] = 35
            if bundle['actor_id'] == SECOND:
                row = ActionDefinition(source_definition_id='action:test.t12.large_ally',
                    display_name='Test larger ally', owner_id=SECOND, economy=EconomyKind.NONE,
                    resolution_kind='TYPED', target_kind='SELF',
                    parameters={'free_primary': True, 'typed': {'effects': [
                        {'type': 'size_change', 'size': 'Large', 'expires_on': 'UNTIL_REMOVED'}],
                        'numbers': {}, 'riders': [], 'duration': {'kind': 'instant'}}})
                bundle['action_catalog'].append(row.model_dump(mode='json'))
                bundle['actor_template']['action_ids'].append(row.source_definition_id)

    game = fixture(tmp_path, [athletics.PURSUIT], seed='T12-unequal-receipt',
        bundle_transform=transform, allies=(FOE, SECOND),
        places={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, SECOND: {'x': 6, 'y': 6}})
    game['turn_of'](SECOND)
    game['commit'](candidate_id(game['menu'](), 'Test larger ally'))
    finish(game)
    game['to_owner']()
    game['commit'](candidate_id(game['menu'](), 'Test held receipts'))
    finish(game)
    engine = game['stored_engine']()
    assert len(engine._actor_cells(engine.state.actors[SECOND])) == 4
    path = [{'x': x, 'y': 6} for x in range(3, 9)]
    menu = game['menu']()
    quote = game['table'].preview_move_path(game['match_id'], menu['decision_id'], menu['state_version'], OWNER, path)
    assert quote['candidate']['movement_cost_ft'] == 35
    chosen_path(game, path, lambda c: pytest.fail('Both allies are too close for a new Pursuit threshold'))
    finish(game)
    actor = game['reload_owner']()
    assert actor.position == p(8, 6)
    assert actor.movement_remaining_ft == 0
    assert not any(c.condition_id == athletics.PURSUIT_PASSAGE for c in actor.conditions.values())


def test_ground_flyer_walking_grant_accounts_receipt_and_set_up_exception():
    engine, actor = held_engine()
    from combat.gate2_grid import SquareGrid
    engine.grid = SquareGrid({'width_squares': 8, 'height_squares': 1,
        'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []})
    actor.position = p(1, 0)
    actor.fly_speed_ft = 30
    for aid, x in ((ALLY, 2), (STOCK_FOE, 3)):
        other = engine.state.actors[aid]
        other.position = p(x, 0)
        other.team_id = actor.team_id
    anchor = engine.state.actors[STOCK_FOE].model_copy(deep=True)
    anchor.entity_id = 'test:set-up-anchor'
    anchor.position = p(5, 0)
    anchor.team_id = 'test:enemy'
    engine.state.actors[anchor.entity_id] = anchor
    from combat.target_knowledge import observe
    observe(engine)
    engine._apply_condition(actor, retribution.SET_UP_CONDITION, retribution.SET_UP,
        anchor.entity_id, expires_on='START_OF_SOURCE_NEXT_TURN', data={'anchor_id': anchor.entity_id})
    before = engine.state.model_dump(mode='json')
    from combat.granted_movement import routes
    walking = routes(engine, actor, 15, mode='walk')
    assert p(4, 0) not in walking
    assert p(0, 0) in walking
    assert not retribution._can_end_adjacent(engine, actor, anchor, 15, granted=True, mode='walk')
    # Set Up's printed exception admits this legal retreat: no adjacent walking
    # endpoint is feasible with the held receipt, even though flying could work.
    from combat.gate2_runtime_models import LegalCandidate
    path, cost, mode = walking[p(0, 0)]
    retreat = LegalCandidate(candidate_id='test:walking-retreat', decision_id='test:grant',
        state_version=engine.state.state_version, kind='MOVE', actor_id=ME,
        source_definition_id='test:grant', display_name='Step', destination=p(0, 0),
        canonical_path=path, movement_cost_ft=cost,
        metadata={'movement_allowance_ft': 15, 'movement_mode': mode})
    assert retribution.set_up_route_endpoint(engine, actor, retreat, None) is not False
    assert engine.state.model_dump(mode='json') == before
