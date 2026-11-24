"""Public synthetic regressions for immutable map paint and one route read frame."""
from collections import Counter
from pathlib import Path

import pytest

from combat import ext, flight, motion, read_queries, roof_movement, spatial_areas, terrain_materials, zones
from combat.ext import states, wax_footing
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import ConditionInstance, Position, ZoneState
from combat.tabletop import normalize_map, to_battlefield

ROOT = Path(__file__).resolve().parents[1]


def yard(*, roof=False):
    document = {
        'display_name': 'Route read frame yard', 'width_squares': 12, 'height_squares': 10,
        'background': {'style': 'wood'},
    }
    if roof:
        document.update(
            walls=[{'shape': 'rect', 'points': [[4, 2], [8, 7]], 'filled': False}],
            roofs={'height_ft': 10, 'climb_check': 'none'})
    engine = Gate2Engine(ROOT, match_seed='route-read-frame', battlefield=to_battlefield(normalize_map(document)))
    actor = engine.state.actors[engine.state.current_actor_id]
    for index, other in enumerate(engine.state.actors.values()):
        other.position = Position(x=index, y=9)
    actor.position = Position(x=3, y=4)
    actor.speed_ft = actor.movement_remaining_ft = actor.climb_speed_ft = 20
    actor.fly_speed_ft = 0
    actor.turn_flags = {}
    return engine, actor


def zone(engine, owner, source, cells, **profile):
    row = ZoneState(
        zone_id='test:' + source, source_definition_id=source, owner_id=owner.entity_id,
        center=cells[0], radius_cells=3, affected_cells=tuple(cells),
        concentration_link=False, created_round=0,
        trigger_profile={'kind': zones.KIND, 'name': 'Test terrain', **profile})
    engine.state.zones[row.zone_id] = row
    return row


def exemption(monkeypatch, actor, cells):
    def published(engine, mover):
        return motion.TerrainExemption(frozenset(cells), nonmagical_only=True) if mover is actor else None
    monkeypatch.setitem(ext._HOOKS, 'difficult_exempt', [published, *ext._HOOKS['difficult_exempt']])


def test_wax_footing_reads_the_same_map_inside_another_movers_repriced_step(monkeypatch):
    engine, mover = yard()
    owner, ally = [a for a in engine.state.actors.values() if a is not mover][:2]
    owner.team_id = ally.team_id = 'test:allies'
    square = Position(x=2, y=2)
    ally.position = square
    owner.conditions['test:court'] = ConditionInstance(
        instance_id='test:court', condition_id=states.PREFIX + wax_footing.COURT_STATE,
        source_definition_id=wax_footing.COURT, source_actor_id=owner.entity_id,
        target_id=owner.entity_id, applied_sequence=0, expires_on='UNTIL_REMOVED')
    zone(engine, owner, wax_footing.COURT, [square], difficult='enemies')
    engine.grid.base_movement_cost[(2, 2)] = 3
    exemption(monkeypatch, mover, {(2, 2)})
    footing = wax_footing.court_footing(engine, ally) or set()
    exempt = motion.exempt_cells(engine, ally)
    assert (2, 2) not in footing and (2, 2) not in exempt
    # Guard A: restoring motion.repriced's map swap makes wax see unpainted ground.
    with motion.repriced(engine, mover):
        assert motion.terrain_cost(engine.grid, (2, 2)) == 1
        assert (wax_footing.court_footing(engine, ally) or set()) == footing
        assert motion.exempt_cells(engine, ally) == exempt


@pytest.mark.parametrize('whole_map', [False, True])
def test_map_costs_never_change_for_a_mover_even_across_mid_move_wall_sync(monkeypatch, whole_map):
    engine, actor = yard()
    covered, uncovered = (4, 4), (5, 4)
    engine.grid.base_movement_cost.update({covered: 4, uncovered: 3})
    engine.__dict__.pop('_wall_base', None)
    zones.sync_walls(engine)
    if whole_map:
        actor.turn_flags['echoing_step'] = 1
    else:
        exemption(monkeypatch, actor, {covered})
    original = dict(engine.grid.base_movement_cost)
    with motion.terrain_for(engine, actor):
        # Guard B: restoring terrain_for's swap fails before any step is priced.
        assert engine.grid.base_movement_cost == original
        with motion.repriced(engine, actor):
            assert engine.grid.base_movement_cost == original
            assert motion.terrain_cost(engine.grid, covered) == 1
            assert motion.terrain_cost(engine.grid, uncovered) == (1 if whole_map else 3)
        wall = zone(engine, actor, 'test:wall', [Position(x=4, y=4)], wall={'move_cost': 2})
        zones.sync_walls(engine)
        # Ground is x4, so the new x2 wall doesn't change the map's merged cost.
        assert engine.grid.base_movement_cost == original
        with motion.repriced(engine, actor):
            assert engine.grid.base_movement_cost == original
            assert motion.terrain_cost(engine.grid, covered) == (1 if whole_map else 2)
        wall.active = False
        zones.sync_walls(engine)
        with motion.repriced(engine, actor):
            assert engine.grid.base_movement_cost == original
            assert motion.terrain_cost(engine.grid, covered) == 1
    assert engine.grid.base_movement_cost == original
    assert motion.terrain_cost(engine.grid, covered) == 4


@pytest.mark.parametrize('revision_field', ['state_version', 'event_sequence'])
def test_candidate_climb_search_shares_each_reader_key_until_a_recorded_change(monkeypatch, revision_field):
    engine, actor = yard(roof=True)
    exemption(monkeypatch, actor, {(3, 4)})
    def material_row(engine, mover):
        return {'mode': 'swim', 'materials': ('water',)} if mover is actor else None
    monkeypatch.setitem(ext._HOOKS, 'material_traversal', [material_row, *ext._HOOKS['material_traversal']])
    computes, asks = Counter(), Counter()
    watched = {'movement_exempt', 'area_difficult', 'material_traversal', 'material_records'}
    real_memo = read_queries.memo
    def counted(engine, key, compute):
        if key[0] not in watched:
            return real_memo(engine, key, compute)
        counted_key = (engine.state.state_version, engine.state.event_sequence, key)
        asks[counted_key] += 1
        def calculate():
            computes[counted_key] += 1
            return compute()
        return real_memo(engine, key, calculate)
    monkeypatch.setattr(read_queries, 'memo', counted)
    real_routes = roof_movement.routes
    summaries = []
    def checked_routes(engine, mover, **kwargs):
        routes = real_routes(engine, mover, **kwargs)
        assert routes and max(len(row[0]) for row in routes.values()) >= 3
        destination = next(p for p in routes if p.z)
        def probe():
            motion.exempt_cells(engine, mover)
            motion.exempt_cells(engine, mover, 'magical')
            spatial_areas.difficult_at(engine, mover, destination)
            terrain_materials.profiles(engine, mover)
            terrain_materials.query(engine, destination)
        probe()
        probe()
        # Guard C: removing _movement_candidates' read_frame repeats per-edge computes.
        assert {key[2][0] for key in computes} == watched
        assert max(computes.values()) == 1
        assert any(count > 1 for count in asks.values())
        before = sum(computes.values())
        setattr(engine.state, revision_field, getattr(engine.state, revision_field) + 1)
        probe()
        probe()
        assert sum(computes.values()) == before + 5
        assert max(computes.values()) == 1
        summaries.append(routes)
        return routes
    monkeypatch.setattr(roof_movement, 'routes', checked_routes)
    with read_queries.candidate_pass(engine):
        candidates = engine._movement_candidates(actor)
    assert summaries and any(c.metadata.get('movement_mode') == 'climb' for c in candidates)
    computes.clear()
    asks.clear()
    # No route frame escapes into execution: each standalone ask computes again.
    destination = Position(x=3, y=4, z=1)
    for _ in range(2):
        motion.exempt_cells(engine, actor)
        spatial_areas.difficult_at(engine, actor, destination)
        terrain_materials.profiles(engine, actor)
        terrain_materials.query(engine, destination)
    assert len(computes) == 5 and set(computes.values()) == {2}
