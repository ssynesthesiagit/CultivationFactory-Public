"""SPREADSPEED1: grid-index snapshots are validated once per candidate pass, exactly.

spread_areas.reaches and area_projection.cells used to deep-compare the whole
grid snapshot (roof surfaces included) on every call; a slow owner fight spent
most of a 147 s menu there. Inside one read_queries.candidate_pass the check now
runs once per identical set of grid input objects. Answers must not change:
temporary in-pass projections, recorded changes, other engines and the next
pass after an unrecorded edit all still get the full check.
"""
import json
import shutil
from copy import copy, deepcopy
from types import SimpleNamespace

from combat import area_projection, read_queries, spatial_areas, spread_areas, typed_executor
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position

ORIGIN = Position(x=3, y=3, z=1)
TARGET = Position(x=6, y=3, z=1)
AREA = {'shape': 'sphere', 'size_ft': 15, 'spreads': True}
FLAT = Position(x=3, y=3)


def _engine(finite=True, roofs=()):
    grid = SquareGrid({'width_squares': 8, 'height_squares': 8, 'square_size_ft': 5,
                      'starting_positions': {}, 'terrain_regions': [], 'roof_surfaces': list(roofs)})
    grid.finite_heights = finite
    return SimpleNamespace(grid=grid, action_catalog={},
                           state=SimpleNamespace(state_version=1, event_sequence=1))


def _wall(grid):
    return {(5, y) for y in range(grid.height)}


def _reference(engine, vertex, aim, destination, area):
    return typed_executor.in_area(engine, vertex, aim, destination, area) and spatial_areas._spread_reaches(
        engine, vertex, aim, destination, area)


def _count(monkeypatch, module):
    calls = []
    native = module.geometry_data
    def counted(grid):
        calls.append(grid)
        return native(grid)
    monkeypatch.setattr(module, 'geometry_data', counted)
    return calls


def _bypass(patch):
    """Today's behaviour: the full snapshot check on every call, pass or not."""
    plain = lambda engine, grid, name, epoch, resolve: resolve()
    patch.setattr(area_projection, 'validated_index', plain)
    patch.setattr(spread_areas, 'validated_index', plain)


def test_full_check_every_call_outside_a_pass_and_once_inside(monkeypatch):
    engine = _engine()
    checks = _count(monkeypatch, spread_areas)
    for _ in range(5):
        assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, TARGET, AREA)
    assert len(checks) == 5
    index = engine._spread_area_index
    del checks[:]
    with read_queries.candidate_pass(engine):
        for _ in range(5):
            assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, TARGET, AREA)
        # Preview views are other engines: they keep today's per-call check.
        view = copy(engine)
        assert spatial_areas.reaches(view, ORIGIN, ORIGIN, TARGET, AREA)
        assert spatial_areas.reaches(view, ORIGIN, ORIGIN, TARGET, AREA)
    assert len(checks) == 3
    assert engine._spread_area_index is index
    # The pass cache did not survive the pass.
    assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, TARGET, AREA)
    assert len(checks) == 4

    flat = _engine(finite=False)
    raster_checks = _count(monkeypatch, area_projection)
    first = area_projection.cells(flat, FLAT, FLAT, AREA)
    assert area_projection.cells(flat, FLAT, FLAT, AREA) is first
    assert len(raster_checks) == 4  # signature + index check, per call
    del raster_checks[:]
    with read_queries.candidate_pass(flat):
        for _ in range(5):
            assert area_projection.cells(flat, FLAT, FLAT, AREA) is first
    assert len(raster_checks) == 2


def test_in_pass_projections_and_recorded_changes_never_reuse_other_geometry(monkeypatch):
    engine = _engine()
    grid = engine.grid
    checks = _count(monkeypatch, spread_areas)
    with read_queries.candidate_pass(engine):
        assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, TARGET, AREA)
        assert len(checks) == 1
        # A temporary projection reassigns a grid field, like motion.terrain_for
        # and zones.sync_walls do: it must take the full check again.
        held_blocked, held_heights = grid.blocked, grid.terrain_heights
        grid.blocked = held_blocked | _wall(grid)
        assert not spatial_areas.reaches(engine, ORIGIN, ORIGIN, TARGET, AREA)
        assert len(checks) == 2
        grid.terrain_heights = {**held_heights, 'BLOCKED': {cell: 5 for cell in _wall(grid)}}
        assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, TARGET, AREA) == _reference(
            engine, ORIGIN, ORIGIN, TARGET, AREA)
        assert len(checks) == 3
        # Even a field that does not change the answer is checked, not trusted.
        held_costs = grid.base_movement_cost
        grid.base_movement_cost = {**held_costs, (0, 0): 2}
        assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, TARGET, AREA) == _reference(
            engine, ORIGIN, ORIGIN, TARGET, AREA)
        assert len(checks) == 4
        grid.blocked, grid.terrain_heights, grid.base_movement_cost = held_blocked, held_heights, held_costs
        # Restoring the very same objects is the geometry first validated.
        assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, TARGET, AREA)
        assert len(checks) == 4
        # A recorded change inside the pass is a new epoch.
        engine.state.event_sequence += 1
        assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, TARGET, AREA)
        assert len(checks) == 5

    flat = _engine(finite=False)
    with read_queries.candidate_pass(flat):
        open_cells = area_projection.cells(flat, FLAT, FLAT, AREA)
        held = flat.grid.blocked
        flat.grid.blocked = held | _wall(flat.grid)
        walled = area_projection.cells(flat, FLAT, FLAT, AREA)
        assert walled == typed_executor.area_cells(flat, FLAT, FLAT, AREA)
        assert walled != open_cells
        flat.grid.blocked = held
        assert area_projection.cells(flat, FLAT, FLAT, AREA) == open_cells


def test_unrecorded_edit_between_passes_is_seen_by_the_next_pass():
    engine = _engine()
    with read_queries.candidate_pass(engine):
        assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, TARGET, AREA)
    engine.grid.blocked.update(_wall(engine.grid))  # in place, no revision
    with read_queries.candidate_pass(engine):
        assert not spatial_areas.reaches(engine, ORIGIN, ORIGIN, TARGET, AREA)
    engine.grid.terrain_heights['BLOCKED'] = {cell: 5 for cell in _wall(engine.grid)}
    with read_queries.candidate_pass(engine):
        assert spatial_areas.reaches(engine, ORIGIN, ORIGIN, TARGET, AREA) == _reference(
            engine, ORIGIN, ORIGIN, TARGET, AREA)

    # Native roof inputs are part of the checked snapshot too.
    roofed = _engine(roofs=[{'id': 'roof', 'height_ft': 10, 'cells': [{'x': 4, 'y': 3}]}])
    with read_queries.candidate_pass(roofed):
        before = spatial_areas.reaches(roofed, ORIGIN, ORIGIN, TARGET, AREA)
        index = roofed._spread_area_index
    roof = roofed.grid.roof_geometry
    roof.by_cell[(4, 3)] = roof.by_cell[(4, 3)]  # same content: index kept
    with read_queries.candidate_pass(roofed):
        assert spatial_areas.reaches(roofed, ORIGIN, ORIGIN, TARGET, AREA) == before
        assert roofed._spread_area_index is index
    from dataclasses import replace
    roof.by_cell[(4, 3)] = (replace(roof.surfaces[0], walk_ft=5),)
    with read_queries.candidate_pass(roofed):
        assert spatial_areas.reaches(roofed, ORIGIN, ORIGIN, TARGET, AREA) == _reference(
            roofed, ORIGIN, ORIGIN, TARGET, AREA)
        assert roofed._spread_area_index is not index

    flat = _engine(finite=False)
    with read_queries.candidate_pass(flat):
        open_cells = area_projection.cells(flat, FLAT, FLAT, AREA)
    flat.grid.blocked.update(_wall(flat.grid))
    with read_queries.candidate_pass(flat):
        walled = area_projection.cells(flat, FLAT, FLAT, AREA)
    assert walled == typed_executor.area_cells(flat, FLAT, FLAT, AREA) and walled != open_cells


def _darkness_fight(tmp_path, monkeypatch):
    """A real table fight with a committed spreading Darkness on a height-aware map."""
    from combat.gate5_service import CombatService
    from tests.worker2_support import fixture, settle

    arenas = CombatService.factory_arenas
    def height_arenas(self, *args, **kwargs):
        result = deepcopy(arenas(self, *args, **kwargs))
        result['battlefield:factory_pillar_arena']['terrain_regions'].append({
            'region_id': 'test:finite-wall', 'terrain_type': 'BLOCKED',
            'cells': [{'x': 0, 'y': 0}], 'height_ft': 10, 'movement_cost': 1})
        return result
    monkeypatch.setattr(CombatService, 'factory_arenas', height_arenas)
    base = tmp_path / 'base'
    base.mkdir()
    combat, table, mid = fixture(base, ['DARK_BASE_DARKNESS'])
    candidates = combat._legal_candidates(combat._load_session(mid))
    darkness = next(c for c in candidates if c.display_name.startswith('Darkness') and c.destination
                    and (c.destination.x, c.destination.y) == (5, 6))
    settle(table, mid, darkness.candidate_id)
    return base, mid


def test_spreading_darkness_fight_is_identical_with_and_without_the_pass_cache(tmp_path, monkeypatch):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT

    base, mid = _darkness_fight(tmp_path, monkeypatch)
    calls = []
    native = spread_areas.reaches
    def counted(*args, **kwargs):
        calls.append(1)
        return native(*args, **kwargs)
    monkeypatch.setattr(spread_areas, 'reaches', counted)
    checks = _count(monkeypatch, spread_areas)

    def read(name):
        root = tmp_path / name
        shutil.copytree(base, root)
        service = CombatService(ROOT, root)
        state = TabletopService(service, root).state(mid, compact_moves=True)
        session = service._load_session(mid)
        assert session.engine.grid.finite_heights
        assert any(z.active and z.trigger_profile.get('spreads') for z in session.engine.state.zones.values())
        candidates = [c.model_dump(mode='json') for c in service._legal_candidates(session)]
        text = json.dumps(state, sort_keys=True, default=str).replace(str(root), '<root>')
        return text, candidates

    cached = read('cached')
    cached_calls, cached_checks = len(calls), len(checks)
    with monkeypatch.context() as patch:
        _bypass(patch)
        plain = read('plain')
    plain_calls, plain_checks = len(calls) - cached_calls, len(checks) - cached_checks
    assert cached[1] and cached[1] == plain[1]
    assert cached[0] == plain[0]
    # The spreading path really ran, and the pass cache really skipped checks.
    assert cached_calls == plain_calls > 0
    assert 0 < plain_checks <= plain_calls
    assert cached_checks < plain_checks


def test_fight_unrecorded_grid_edit_between_passes_is_seen(tmp_path, monkeypatch):
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT

    base, mid = _darkness_fight(tmp_path, monkeypatch)

    def membership(engine):
        zone = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get('spreads'))
        with read_queries.candidate_pass(engine):
            return {aid: spatial_areas.zone_contains(engine, actor, zone)
                    for aid, actor in sorted(engine.state.actors.items())}

    def edit(engine):
        # An unrecorded full-height wall through the darkness, next to its centre.
        engine.grid.blocked.update((4, y) for y in range(engine.grid.height))

    engine = CombatService(ROOT, base)._load_session(mid).engine
    before = membership(engine)
    edit(engine)
    after = membership(engine)
    reference_engine = CombatService(ROOT, base)._load_session(mid).engine
    edit(reference_engine)
    with monkeypatch.context() as patch:
        _bypass(patch)
        patch.setattr(spatial_areas, 'reaches', lambda engine, vertex, aim, destination, area: _reference(
            engine, vertex, aim, destination, area))
        expected = membership(reference_engine)
    assert after == expected
    assert after != before, 'the edit must change who is inside the darkness'
