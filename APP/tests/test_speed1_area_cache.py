"""SPEED1: derived sight answers must not invalidate semantic area geometry."""
from copy import copy

from combat import area_projection, typed_executor, zones
from combat.gate2_runtime_models import Position
from tests.h1_support import duel, ME


def test_sight_cache_population_and_eviction_keep_the_area_index():
    engine = duel([])
    origin = engine.state.actors[ME].position
    aim = Position(x=5, y=5)
    spec = {'shape': 'sphere', 'size_ft': 15}
    first = area_projection.cells(engine, origin, aim, spec)
    index = engine._area_projection_index
    for ray in range(20):
        engine.grid._centerline_sight_cache[(ray, 0, 0, 5, 5, 0)] = True
        assert area_projection.cells(copy(engine), origin, aim, spec) is first
        assert engine._area_projection_index is index
    engine.grid._centerline_sight_cache.clear()
    assert area_projection.cells(engine, origin, aim, spec) is first
    # Real geometry still invalidates at the same unrecorded epoch.
    engine.grid.blocked.add((4, 5))
    changed = area_projection.cells(engine, origin, aim, spec)
    assert engine._area_projection_index is not index
    assert changed == typed_executor.area_cells(engine, origin, aim, spec) != first


def test_real_service_menu_does_not_rebuild_rasters_for_each_sight_query(tmp_path, monkeypatch):
    from tests.worker2_support import fixture, OWNER
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT

    combat, table, mid = fixture(tmp_path, ['DARK_BASE_DARKNESS'])
    session = combat._load_session(mid)
    # Bind a real centerline region on a disposable service-loaded grid. Sight
    # populates the same cache that grew per placement in the live 3v3 profile.
    session.engine.grid.centerline_cells.add((0, 0))
    session.engine.grid.occluder_spans[(0, 0)] = [('centerline', 0, None)]
    origin = session.engine.state.actors[OWNER].position
    area_projection.cells(session.engine, origin, Position(x=5, y=5),
                          {'shape': 'sphere', 'size_ft': 15})
    initial = session.engine._area_projection_index
    session.engine.grid.line_of_sight(origin, Position(x=6, y=5))
    assert session.engine.grid._centerline_sight_cache
    count = []
    init = area_projection._Index.__init__
    def counted(index, *args):
        count.append(1)
        init(index, *args)
    monkeypatch.setattr(area_projection._Index, '__init__', counted)
    candidates = CombatService(ROOT, tmp_path)._legal_candidates(session)
    assert any(c.destination is not None and c.kind.value != 'MOVE' for c in candidates)
    assert session.engine.grid._centerline_sight_cache
    assert len(count) == 0, f'{len(count)} full terrain snapshots for one menu'
    assert session.engine._area_projection_index is initial
    # The optimization also serves player menus; commit an unchanged legal
    # action through the table, reload it, and check journal/replay integrity.
    state = table.state(mid)
    assert state['menu']['actor_id'] == OWNER
    from tests.worker2_support import settle
    hold = next(c.candidate_id for c in candidates if c.source_definition_id == 'system:combat.hold_position')
    settle(table, mid, hold)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'
    assert TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid)['menu']
