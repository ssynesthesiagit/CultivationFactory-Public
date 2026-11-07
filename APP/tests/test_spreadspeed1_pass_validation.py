"""SPREADSPEED1: grid-index snapshots are validated once per candidate pass, exactly.

spread_areas.reaches and area_projection.cells used to deep-compare the whole
grid snapshot (roof surfaces included) on every call; a slow owner fight spent
most of a 147 s menu there. Inside one read_queries.candidate_pass the check now
runs once per identical set of grid input objects. Answers must not change:
temporary in-pass projections, recorded changes, other engines and the next
pass after an unrecorded edit all still get the full check.
"""
import json
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


ME = 'actor:factory.spreadspeed1'


def _darkness_fight():
    """A real fight with a cast spreading Darkness on a height-aware map.

    The engine-level setup of test_darkness_and_stealth: it also runs on the
    public test mirror, where the worker-2 table fixture finds no Darkness.
    """
    from combat.factory_compiler import compile_character
    from combat.gate2_runtime_content import AN
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import ROOT
    from tests.test_zones import SHEET

    sheet = {**SHEET, 'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.dark'],
                                              'learned_talent_record_ids': ['DARK_BASE_DARKNESS']}}
    battlefield = json.loads((ROOT / 'combat_gate1/generated/Battlefield.json').read_text(encoding='utf-8'))
    # One finite-height wall makes every spreading query take the 3D volume path.
    battlefield['terrain_regions'].append({'region_id': 'test:finite-wall', 'terrain_type': 'BLOCKED',
                                           'cells': [{'x': 0, 'y': 0}], 'height_ft': 10, 'movement_cost': 1})
    engine = Gate4ControllerEngine(
        ROOT, match_seed='SPREADSPEED1', typed_bundles=(compile_character(sheet, actor_id=ME),),
        battlefield=battlefield,
        roster_setup={'primary_actor_ids': [ME, AN], 'team_by_actor': {ME: 'team:a', AN: 'team:b'},
                      'starting_positions': {ME: {'x': 4, 'y': 6}, AN: {'x': 8, 'y': 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()

    def do(name, at=None):
        candidate = next(c for c in engine.legal_candidates() if c.display_name.split(' at ')[0] == name
                         and (at is None or (c.destination is not None and (c.destination.x, c.destination.y) == at)))
        engine.execute_intent(ActionIntent(
            intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
            destination=candidate.destination))
    shape = [c.display_name for c in engine.legal_candidates() if c.display_name.startswith('Shape Darkness')]
    if shape:
        do(min(shape, key=lambda name: (not name.endswith('plain Darkness'), name)))
    do('Darkness', at=(6, 6))
    engine._system_start_turn()
    assert engine.grid.finite_heights
    zone = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get('spreads'))
    return engine, zone


def test_spreading_darkness_fight_is_identical_with_and_without_the_pass_cache(monkeypatch):
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    from tests.h1_support import ROOT

    engine, _ = _darkness_fight()
    policy, _ = PolicyLibrary(ROOT).for_actor(ME)
    calls = []
    native = spread_areas.reaches
    def counted(*args, **kwargs):
        calls.append(1)
        return native(*args, **kwargs)
    monkeypatch.setattr(spread_areas, 'reaches', counted)
    checks = _count(monkeypatch, spread_areas)

    def read(fight):
        before = fight.state.model_dump(mode='json')
        candidates = [c.model_dump(mode='json') for c in fight.legal_candidates()]
        context = build_decision_context(fight, policy, include_item_actions=True).model_dump(mode='json')
        state = fight.state.model_dump(mode='json')
        assert state == before
        return candidates, json.dumps(context, sort_keys=True, default=str), json.dumps(state, sort_keys=True)

    cached = read(deepcopy(engine))
    cached_calls, cached_checks = len(calls), len(checks)
    with monkeypatch.context() as patch:
        _bypass(patch)
        plain = read(deepcopy(engine))
    plain_calls, plain_checks = len(calls) - cached_calls, len(checks) - cached_checks
    assert cached[0] and cached[0] == plain[0]
    assert cached[1] == plain[1]
    assert cached[2] == plain[2]
    # The spreading path really ran, and the pass cache really skipped checks.
    assert cached_calls == plain_calls > 0
    assert 0 < plain_checks <= plain_calls
    assert cached_checks < plain_checks


def test_fight_unrecorded_grid_edit_between_passes_is_seen(monkeypatch):
    engine, zone = _darkness_fight()

    def membership(fight):
        with read_queries.candidate_pass(fight):
            return {aid: spatial_areas.zone_contains(fight, actor, fight.state.zones[zone.zone_id])
                    for aid, actor in sorted(fight.state.actors.items())}

    before = membership(engine)
    # An unrecorded full-height wall between the caster and the darkness centre.
    engine.grid.blocked.update((5, y) for y in range(engine.grid.height))
    after = membership(engine)
    reference = deepcopy(engine)
    with monkeypatch.context() as patch:
        _bypass(patch)
        patch.setattr(spatial_areas, 'reaches', lambda fight, vertex, aim, destination, area: _reference(
            fight, vertex, aim, destination, area))
        expected = membership(reference)
    assert after == expected
    assert before[ME] and not after[ME], 'the edit must change who is inside the darkness'
