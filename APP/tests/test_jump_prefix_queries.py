"""Run-up sharing preserves native routes, receipt histories and query scopes."""
from collections import Counter
from copy import deepcopy

import pytest

from combat import ext, flight, passage_routes, read_queries
from combat.ext import athletics, move_attack, rider_movement
from combat.gate2_runtime_models import Position
from combat.space import point
from tests.test_perfjump1_jump_quote import case, snapshot
from tests.test_roof_movement import condition, engine_at_wall


def append_provider(monkeypatch, name, provider):
    """Keep all native providers and add an active, unannotated pure reply."""
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, name, [*ext._HOOKS.get(name, ()), provider])


def live_record(engine):
    return (engine.state.model_dump(mode='json'),
            [row.model_dump(mode='json') for row in engine.events],
            [row.model_dump(mode='json') for row in engine.rolls])


@pytest.mark.parametrize('edge_providers', [False, True])
def test_full_jump_routes_preserved_with_less_prefix_work(monkeypatch, edge_providers):
    engine, actor, walking = case()
    if edge_providers:
        # These providers have neither presence filters nor query metadata.
        append_provider(monkeypatch, 'movement_segment_surcharge',
            lambda e, a, previous, destination, mode:
            2 if mode == 'walk' and destination.x > previous.x else None)
        append_provider(monkeypatch, 'movement_step_capability',
            lambda e, a, previous, destination, mode:
            False if mode == 'jump' and point(destination) == (3, 7, 2) else None)
    before = live_record(engine)
    calls = Counter()
    advance = passage_routes.Resources.advance

    def counted(resources, state, previous, destination):
        calls[(point(previous), point(destination))] += 1
        yield from advance(resources, state, previous, destination)

    monkeypatch.setattr(passage_routes.Resources, 'advance', counted)
    shared = flight.jumps(engine, actor, walking)
    shared_work = sum(calls.values())
    calls.clear()
    with read_queries.sharing_off():
        independent = flight.jumps(engine, actor, walking)
    assert snapshot(shared) == snapshot(independent)
    assert len(shared) >= 20
    assert shared_work < sum(calls.values())
    if edge_providers:
        assert Position(x=3, y=7, z=2) not in shared
        assert shared[Position(x=4, y=5, z=1)][1] == 12
    assert live_record(engine) == before


def test_complete_native_movement_candidates_match_without_sharing():
    engine, actor = engine_at_wall(wall_x=3, height_ft=10)
    # A bounded native menu still includes supported jumps and ordinary routes.
    actor.position = Position(x=0, y=5)
    actor.strength_score = 30
    actor.speed_ft = actor.movement_remaining_ft = 25
    before = live_record(engine)
    for control in ('MANUAL', 'LOCAL_AUTO', 'API_AUTO'):
        engine.typed_control_modes = {actor.entity_id: control}
        shared = [row.model_dump(mode='json') for row in engine._movement_candidates(actor)]
        with read_queries.sharing_off():
            independent = [row.model_dump(mode='json') for row in engine._movement_candidates(actor)]
        assert shared == independent
        assert any(row['metadata'].get('movement_mode') == 'jump' for row in shared), control
        assert any(row['metadata'].get('movement_mode', 'walk') == 'walk' for row in shared)
    assert live_record(engine) == before


def receipt_branches():
    engine, actor = engine_at_wall(wall_x=7, height_ft=10)
    actor.position = Position(x=1, y=5)
    actor.strength_score = 30
    actor.speed_ft = actor.movement_remaining_ft = 60
    others = [row for row in engine.state.actors.values() if row is not actor]
    for other in others:
        other.active = False
    for other, position in zip(others, (Position(x=3, y=5), Position(x=6, y=5, z=1))):
        other.active = True
        other.team_id = actor.team_id
        other.position = position
    condition(actor, athletics.PURSUIT_PASSAGE, data={'ally_id': ''})
    direct = tuple(Position(x=x, y=5) for x in range(1, 7))
    detour = (*direct[:2], Position(x=3, y=4), *direct[3:])
    return engine, actor, direct, detour


def runups(engine, actor, paths):
    walking = passage_routes.Reachability()
    walking.runups = tuple((path, passage_routes.path_cost(engine, actor, path, 'walk'), 'walk')
                          for path in paths)
    return walking


def test_converging_receipt_histories_and_shared_branch_maps_stay_independent(monkeypatch):
    engine, actor, direct, detour = receipt_branches()
    walking = runups(engine, actor, (direct, detour))
    landing = Position(x=7, y=5, z=2)
    before = live_record(engine)
    extend = flight.extend_cost
    retained = []
    branch_inputs = []

    def inspected(e, a, resources, states, steps, mode):
        steps = tuple(steps)
        if steps and point(steps[0][0]) == (2, 5, 0):
            branch_inputs.append(states)
        output = extend(e, a, resources, states, steps, mode)
        retained.append((states, deepcopy(states)))
        retained.append((output, deepcopy(output)))
        return output

    monkeypatch.setattr(flight, 'extend_cost', inspected)
    shared = flight.jumps(engine, actor, walking)
    # The same prefix feeds both branches; no later ascent/landing can spend or
    # overwrite the cached map. Complete inventories, not one minimum, survive.
    assert len(branch_inputs) == 2 and branch_inputs[0] is branch_inputs[1]
    assert all(current == saved for current, saved in retained)
    with read_queries.sharing_off():
        independent = flight.jumps(engine, actor, walking)
    assert snapshot(shared) == snapshot(independent)
    direct_result = flight.jumps(engine, actor, runups(engine, actor, (direct,)))
    detour_result = flight.jumps(engine, actor, runups(engine, actor, (detour,)))
    assert detour_result[landing][1] < direct_result[landing][1]
    assert shared[landing] == detour_result[landing]
    assert shared[landing][0][:len(detour)] == detour
    for path, cost, mode in shared.values():
        assert cost == passage_routes.path_cost(engine, actor, path, mode)
    assert all(current == saved for current, saved in retained)
    assert live_record(engine) == before


def test_invalid_prefix_is_rejected_each_time_without_caching_failure(monkeypatch):
    engine, actor, walking = case()
    bad_edge = ((3, 5, 0), (4, 5, 0))
    calls = []

    def invalid_price(e, a, previous, destination, mode):
        if mode == 'walk' and (point(previous), point(destination)) == bad_edge:
            calls.append(bad_edge)
            return -1

    append_provider(monkeypatch, 'movement_segment_surcharge', invalid_price)
    before = live_record(engine)
    shared = flight.jumps(engine, actor, walking)
    assert len(calls) >= 2, 'each failed prefix must still validate the provider'
    calls.clear()
    with read_queries.sharing_off():
        independent = flight.jumps(engine, actor, walking)
    assert len(calls) >= 2
    assert snapshot(shared) == snapshot(independent)
    assert Position(x=4, y=5, z=1) not in shared
    assert Position(x=2, y=5, z=1) in shared
    assert live_record(engine) == before


def test_provider_exception_unwinds_frame_and_next_call_recomputes(monkeypatch):
    engine, actor, walking = case()
    expected = snapshot(flight.jumps(engine, actor, walking))
    before = live_record(engine)
    original_frame = read_queries._FRAME.get()

    def broken_price(e, a, previous, destination, mode):
        if mode == 'walk' and point(destination) == (5, 5, 0):
            raise RuntimeError('test prefix provider failure')

    with monkeypatch.context() as patch:
        append_provider(patch, 'movement_segment_surcharge', broken_price)
        with pytest.raises(RuntimeError, match='test prefix provider failure'):
            flight.jumps(engine, actor, walking)
    assert read_queries._FRAME.get() is original_frame
    assert snapshot(flight.jumps(engine, actor, walking)) == expected
    assert live_record(engine) == before


def test_new_search_does_not_reuse_receipts_across_nested_source_scopes():
    engine, actor = engine_at_wall(wall_x=12)
    actor.position = Position(x=1, y=5)
    actor.strength_score = 30
    actor.speed_ft = actor.movement_remaining_ft = 30
    others = [row for row in engine.state.actors.values() if row is not actor]
    for other in others:
        other.active = False
    foe = others[0]
    foe.active = True
    foe.team_id = 'test:hostile'
    foe.position = Position(x=2, y=5)
    ground = tuple(Position(x=x, y=5) for x in range(1, 5))
    walking = {ground[-1]: (ground, 15)}
    landing = Position(x=4, y=5, z=1)
    before = live_record(engine)

    def compared():
        shared = flight.jumps(engine, actor, walking)
        with read_queries.sharing_off():
            independent = flight.jumps(engine, actor, walking)
        assert snapshot(shared) == snapshot(independent)
        return shared

    # All calls share the outer read frame and state revision. Each jumps call
    # owns new Resources; the old maps live only until this outer frame exits.
    with read_queries.read_frame(engine):
        blocked = compared()
        assert landing not in blocked
        with move_attack.traits(engine, actor, {}, (foe.entity_id,)):
            difficult = compared()
            assert landing in difficult
            with rider_movement.crossing(engine, actor, foe.entity_id, 'free'):
                free = compared()
                assert free[landing][1] < difficult[landing][1]
            assert snapshot(compared()) == snapshot(difficult)
        assert snapshot(compared()) == snapshot(blocked)
    assert live_record(engine) == before
