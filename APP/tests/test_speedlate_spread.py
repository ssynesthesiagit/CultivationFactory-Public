"""SPEEDLATE: repeated 3D spreading queries resume one exact search."""
from copy import copy, deepcopy
from itertools import product
from types import SimpleNamespace

import pytest

from combat import spatial_areas, spread_areas
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position


def _engine():
    grid = SquareGrid({'width_squares': 8, 'height_squares': 8, 'square_size_ft': 5,
                      'starting_positions': {}, 'terrain_regions': []})
    grid.finite_heights = True
    return SimpleNamespace(grid=grid, state=SimpleNamespace(state_version=1, event_sequence=1))


ORIGIN = Position(x=3, y=3, z=1)
AREA = {'shape': 'sphere', 'size_ft': 15, 'spreads': True}


def _reference(engine, vertex, aim, destination, area):
    from combat.typed_executor import in_area
    return in_area(engine, vertex, aim, destination, area) and spatial_areas._spread_reaches(
        engine, vertex, aim, destination, area)


@pytest.mark.parametrize('shape', ['sphere', 'cube', 'cylinder', 'cone', 'line'])
@pytest.mark.parametrize('reverse', [False, True])
def test_incremental_membership_is_exact_in_either_target_order(shape, reverse):
    engine = _engine()
    engine.grid.blocked.update({(4, 3), (4, 4), (3, 4), (5, 2)})
    engine.grid.terrain_heights['BLOCKED'] = {(4, 3): 10, (3, 4): 5, (5, 2): 15}
    engine.grid.terrain_spans['BLOCKED'] = {(4, 4): [(5, 15)]}
    area = {**AREA, 'shape': shape, 'width_ft': 10, 'height_ft': 15}
    vertex = Position(x=1, y=3, z=1)
    targets = [Position(x=x, y=y, z=z) for x,y,z in product(range(1, 7), range(1, 7), range(4))]
    if reverse:
        targets.reverse()
    for target in targets:
        assert spatial_areas.reaches(engine, vertex, ORIGIN, target, area) == _reference(
            engine, vertex, ORIGIN, target, area)


def test_repeated_target_and_geometry_equivalent_area_do_not_walk_again(monkeypatch):
    engine = _engine()
    calls = []
    native = SquareGrid.volume_step_legal
    def counted(self, *args, **kwargs):
        calls.append(1)
        return native(self, *args, **kwargs)
    monkeypatch.setattr(SquareGrid, 'volume_step_legal', counted)
    target = Position(x=6, y=3, z=1)
    assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, target, AREA)
    count = len(calls)
    assert count > 0
    for _ in range(10):
        assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, target, {**AREA, 'name': 'unrelated presentation'})
    assert len(calls) == count, 'the same spreading volume was searched again for each creature'


def test_grid_edits_revisions_projections_and_deepcopy_are_observed():
    engine = _engine()
    target = Position(x=6, y=3, z=1)
    assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, target, AREA)
    index = engine._spread_area_index
    projected = copy(engine)
    assert spatial_areas.reaches(projected, ORIGIN, ORIGIN, target, AREA)
    assert projected._spread_area_index is index
    engine.grid._centerline_sight_cache['derived'] = True
    assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, target, AREA)
    assert engine._spread_area_index is index
    # A real wall edit, even without a recorded revision, rebuilds the search.
    engine.grid.blocked.update((5, y) for y in range(engine.grid.height))
    assert not spatial_areas.reaches(engine, ORIGIN, ORIGIN, target, AREA)
    assert engine._spread_area_index is not index
    index = engine._spread_area_index
    engine.grid.terrain_heights['BLOCKED'] = {(5, y): 5 for y in range(engine.grid.height)}
    assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, target, AREA)
    assert engine._spread_area_index is not index
    index = engine._spread_area_index
    engine.state.event_sequence += 1
    assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, target, AREA)
    assert engine._spread_area_index is not index
    cloned = deepcopy(engine)
    assert cloned._spread_area_index is None
    assert spatial_areas.reaches(cloned, ORIGIN, ORIGIN, target, AREA)
    assert cloned._spread_area_index is not engine._spread_area_index
    # Different explicit origin/spec inputs never borrow another area's search.
    for aim, area in [(Position(x=4, y=4, z=2), AREA), (ORIGIN, {**AREA, 'size_ft': 5})]:
        assert spatial_areas.reaches(engine, ORIGIN, aim, target, area) == _reference(
            engine, ORIGIN, aim, target, area)


def test_unknown_grid_and_nondata_inputs_keep_the_reference_path():
    engine = _engine()
    target = Position(x=6, y=3, z=1)
    engine.grid.extra_provider = object()
    assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, target, AREA) == _reference(
        engine, ORIGIN, ORIGIN, target, AREA)
    assert not hasattr(engine, '_spread_area_index')
    class OtherGrid(SquareGrid):
        pass
    engine = _engine()
    engine.grid = OtherGrid({'width_squares': 8, 'height_squares': 8, 'square_size_ft': 5,
                             'starting_positions': {}, 'terrain_regions': []})
    engine.grid.finite_heights = True
    assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, target, AREA) == _reference(
        engine, ORIGIN, ORIGIN, target, AREA)
    assert not hasattr(engine, '_spread_area_index')


def test_failed_search_is_evicted_and_bounds_include_rejected_cells(monkeypatch):
    engine = _engine()
    target = Position(x=6, y=3, z=1)
    native = spread_areas._Search.reaches
    def broken(self, *args):
        self.seen.add(('partial',))
        raise RuntimeError('interrupted query')
    monkeypatch.setattr(spread_areas._Search, 'reaches', broken)
    with pytest.raises(RuntimeError, match='interrupted'):
        spatial_areas.reaches(engine, ORIGIN, ORIGIN, target, AREA)
    assert not engine._spread_area_index.entries
    monkeypatch.setattr(spread_areas._Search, 'reaches', native)
    monkeypatch.setattr(spread_areas, 'MAX_ENTRIES', 1)
    assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, target, AREA)
    assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, Position(x=4, y=3, z=1), {**AREA, 'size_ft': 10})
    assert len(engine._spread_area_index.entries) == 1
    monkeypatch.setattr(spread_areas, 'MAX_CELLS', 1)
    assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, target, AREA)
    assert not engine._spread_area_index.entries


def test_table_menu_reuses_spread_search_and_commit_reload_remains_exact(tmp_path, monkeypatch):
    from combat.gate5_service import CombatService
    from tests.worker2_support import fixture, settle
    from tests.h1_support import ROOT

    # Height-aware geometry must be part of the match's persisted battlefield,
    # not an edit to a disposable engine that the table never commits.
    arenas = CombatService.factory_arenas
    def height_arenas(self, *args, **kwargs):
        result = deepcopy(arenas(self, *args, **kwargs))
        result['battlefield:factory_pillar_arena']['terrain_regions'].append({
            'region_id': 'test:finite-wall', 'terrain_type': 'BLOCKED',
            'cells': [{'x': 0, 'y': 0}], 'height_ft': 10, 'movement_cost': 1})
        return result
    monkeypatch.setattr(CombatService, 'factory_arenas', height_arenas)
    combat, table, mid = fixture(tmp_path, ['DARK_BASE_DARKNESS'])
    session = combat._load_session(mid)
    # The fixture's real compiled Darkness, paid for and committed by the table.
    candidates = combat._legal_candidates(session)
    darkness = next(c for c in candidates if c.display_name.startswith('Darkness') and c.destination
                    and (c.destination.x, c.destination.y) == (5, 6))
    settle(table, mid, darkness.candidate_id)
    calls = []
    native = spread_areas._Search.__init__
    def counted(self, *args):
        calls.append(1)
        native(self, *args)
    monkeypatch.setattr(spread_areas._Search, '__init__', counted)
    def check_cold_boundary():
        service = CombatService(ROOT, tmp_path)
        loaded = service._load_session(mid)
        engine = loaded.engine
        assert engine.grid.finite_heights
        assert engine.grid.terrain_heights['BLOCKED'][(0, 0)] == 10
        before = deepcopy(engine.state.model_dump(mode='json'))
        zone = next(z for z in engine.state.zones.values()
                    if z.active and z.trigger_profile.get('spreads'))
        calls_before = len(calls)
        actual = {aid: spatial_areas.zone_contains(engine, actor, zone)
                  for aid, actor in engine.state.actors.items()}
        candidates = service._legal_candidates(loaded)
        index = engine._spread_area_index
        assert index.entries and len(calls) > calls_before
        walks = sum(len(search.seen) for search in index.entries.values())
        for _ in range(10):
            assert {aid: spatial_areas.zone_contains(engine, actor, zone)
                    for aid, actor in engine.state.actors.items()} == actual
        assert sum(len(search.seen) for search in index.entries.values()) == walks
        assert engine.state.model_dump(mode='json') == before
        # Fresh engine/read frames keep candidate memoization from hiding the
        # independent, original ordered flood-search oracle.
        reference_service = CombatService(ROOT, tmp_path)
        reference = reference_service._load_session(mid)
        reference_zone = reference.engine.state.zones[zone.zone_id]
        with monkeypatch.context() as oracle:
            oracle.setattr(spatial_areas, 'reaches', _reference)
            expected = {aid: spatial_areas.zone_contains(reference.engine, actor, reference_zone)
                        for aid, actor in reference.engine.state.actors.items()}
            expected_candidates = reference_service._legal_candidates(reference)
        assert actual == expected
        assert [c.model_dump(mode='json') for c in candidates] == [
            c.model_dump(mode='json') for c in expected_candidates]
        assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
        return candidates, actual

    candidates, before_membership = check_cold_boundary()
    hold = next(c.candidate_id for c in candidates if c.source_definition_id == 'system:combat.hold_position')
    settle(table, mid, hold)
    _, after_membership = check_cold_boundary()
    assert after_membership == before_membership
    assert table.state(mid)['menu']
