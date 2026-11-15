"""Placement misses retain exhaustive authority without per-cell setup work."""
import pytest
from combat import placement_menu
from tests.test_menuspeed3_placement import setup, root_for
from tests.test_menuspeed3_review import offline_menu_embeddings


def test_complete_picker_uses_one_native_action_query(tmp_path, monkeypatch):
    combat, _, mid = setup(tmp_path)
    engine = combat._load_session(mid).engine
    root = root_for(combat, mid)
    from combat.gate2_runtime_models import Position
    from combat.target_knowledge import actors_for
    actor = engine.state.actors[root.actor_id]
    levels = sorted({0, actor.position.z} | {a.position.z for a in actors_for(engine, actor)})
    expected = [row for y in range(engine.grid.height) for x in range(engine.grid.width)
                for z in levels
                if (row := placement_menu.exact(engine, root, Position(x=x, y=y, z=z))) is not None]
    assert len(expected) > 1
    calls = []
    native = engine._action_candidates
    def generate(*args, **kwargs):
        calls.append(kwargs.get('intent'))
        return native(*args, **kwargs)
    monkeypatch.setattr(engine, '_action_candidates', generate)
    # Even an enclosing lazy-menu query must expose the full picker on demand.
    with placement_menu.query():
        actual = list(placement_menu.cells(engine, root))
    assert actual == expected
    assert calls == [None], 'full authority should reuse native geometry setup once'


def test_table_auto_step_miss_reuses_native_setup(tmp_path, monkeypatch):
    from combat.gate2_engine import Gate2Engine
    from tests.worker2_support import OWNER, reload
    combat, table, mid = setup(tmp_path)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    native = Gate2Engine._action_candidates
    complete = placement_menu.cells
    rank = placement_menu.search
    exact = placement_menu.exact
    counts = []
    active = None
    sampling = False
    def generate(*args, **kwargs):
        if active is not None:
            counts[active] += 1
        return native(*args, **kwargs)
    def picker(*args):
        nonlocal active, sampling
        previous = active
        was_sampling = sampling
        sampling = False
        counts.append(0)
        active = len(counts) - 1
        try:
            yield from complete(*args)
        finally:
            active = previous
            sampling = was_sampling
    def search(*args):
        nonlocal sampling
        previous = sampling
        sampling = True
        try:
            return rank(*args)
        finally:
            sampling = previous
    monkeypatch.setattr(Gate2Engine, '_action_candidates', generate)
    monkeypatch.setattr(placement_menu, 'cells', picker)
    # Force a heuristic miss, while native exhaustive geometry remains legal.
    monkeypatch.setattr(placement_menu, 'search', search)
    monkeypatch.setattr(placement_menu, 'exact', lambda *args: None if sampling else exact(*args))
    result = table.auto_step(mid, 0, [])
    assert result['status'] == 'COMMITTED'
    assert counts and set(counts) == {1}, 'table fallback must share native setup'
    assert reload(tmp_path, mid).state.state_version > 0


def test_bulk_picker_shares_read_only_geometry_queries(tmp_path, monkeypatch):
    from combat.read_queries import enumeration_cache
    combat, _, mid = setup(tmp_path)
    engine = combat._load_session(mid).engine
    root = root_for(combat, mid)
    native = engine._action_candidates
    def generate(*args, **kwargs):
        assert enumeration_cache(engine) is not None, 'bulk placement needs a pure candidate pass'
        return native(*args, **kwargs)
    monkeypatch.setattr(engine, '_action_candidates', generate)
    assert list(placement_menu.cells(engine, root))
    assert enumeration_cache(engine) is None, 'picker must not retain a cache for execution'


def test_bulk_picker_skips_only_out_of_range_coordinates(tmp_path, monkeypatch):
    combat, _, mid = setup(tmp_path)
    engine = combat._load_session(mid).engine
    root = root_for(combat, mid)
    expected = list(placement_menu.cells(engine, root))
    visited = set()
    native = engine._effect_distance_to_cell
    def distance(actor, cell):
        visited.add((cell.x, cell.y))
        return native(actor, cell)
    monkeypatch.setattr(engine, '_effect_distance_to_cell', distance)
    assert list(placement_menu.cells(engine, root)) == expected
    assert visited and len(visited) < engine.grid.width * engine.grid.height, 'bulk picker must bound native range'
    assert placement_menu._RANGE.get() is None


@pytest.mark.parametrize('remote', [False, True])
def test_range_bound_preserves_large_body_origin_and_altitudes(tmp_path, monkeypatch, remote):
    from combat.gate2_runtime_models import Position
    from tests.worker2_support import OWNER
    from tests.test_lock_choices import install
    combat, _, mid = setup(tmp_path)
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    actor.position = actor.position.model_copy(update={'z': 2})
    engine.actor_footprints[OWNER] = engine._footprint(actor).model_copy(
        update={'width_cells': 3, 'height_cells': 3})
    if remote:
        install(monkeypatch, 'effect_origins', lambda e, a, action:
            [{'id': 'test:far-origin', 'label': 'Distant current',
              'position': {'x': e.grid.width - 2, 'y': 6, 'z': 2}}]
            if a.entity_id == OWNER and action.target_kind == 'CELL' else [])
    with placement_menu.query():
        root = next(c for c in engine.legal_candidates()
                    if c.metadata.get('placement_picker') and 'Gather Current: Press' in c.display_name
                    and bool(c.metadata.get('effect_origin')) == remote)
    expected = [row for y in range(engine.grid.height) for x in range(engine.grid.width)
                for z in (0, 2)
                if (row := placement_menu.exact(engine, root, Position(x=x, y=y, z=z))) is not None]
    assert expected and any(row.destination.z == 2 for row in expected)
    assert list(placement_menu.cells(engine, root)) == expected


def test_range_scope_is_inert_for_other_action_frames(tmp_path):
    from combat.shot_geometry import scope
    combat, _, mid = setup(tmp_path)
    engine = combat._load_session(mid).engine
    root = root_for(combat, mid)
    actor = engine.state.actors[root.actor_id]
    action = engine.action_catalog[root.source_definition_id]
    sibling = next(a for a in engine.action_catalog.values()
                   if a.owner_id == actor.entity_id and a is not action)
    token = placement_menu._RANGE.set((engine, actor, action))
    try:
        for framed in (False, True):
            from contextlib import nullcontext
            with scope(engine, actor, sibling) if framed else nullcontext():
                xs, ys, zs = placement_menu.axes(engine.grid, None, (0, 2))
                assert list(xs) == list(range(engine.grid.width))
                assert list(ys) == list(range(engine.grid.height))
                assert zs == (0, 2)
    finally:
        placement_menu._RANGE.reset(token)
