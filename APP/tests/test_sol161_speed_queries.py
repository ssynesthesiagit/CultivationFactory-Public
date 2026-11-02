"""Exact query equivalence, invalidation and table persistence for speed pass 2."""
from combat import catalog_queries, flight, motion, read_queries, spatial_areas, zones
from combat.ext import hand_occupancy
from combat.canonical import canonical_bytes
from combat.gate2_runtime_models import Position
from tests.h1_support import ROOT, ME, duel
from tests.test_lock10_flight_movement import grant


def test_owner_index_reads_mutable_parameters_and_unversioned_catalog_edits():
    engine = duel([])
    actor = engine.state.actors[ME]
    action = next(iter(engine.action_catalog.values()))
    # Isolate the policy marker from the harness's already-managed loadout.
    for key, existing in list(engine.action_catalog.items()):
        if existing.owner_id == ME:
            params = dict(existing.parameters)
            params.pop('equipment_grip', None)
            params.pop('equipment_hands_model', None)
            engine.action_catalog[key] = existing.model_copy(update={'parameters': params})
    managed = action.model_copy(update={'owner_id': ME, 'parameters': {'equipment_hands_model': 1}})
    engine.action_catalog['test:managed'] = managed
    assert hand_occupancy.supports_grips(engine, actor)
    first = engine._catalog_owner_index
    assert hand_occupancy.supports_grips(engine, actor)
    assert engine._catalog_owner_index is first
    managed.parameters.clear()  # nested dictionaries remain mutable on frozen models
    assert not hand_occupancy.supports_grips(engine, actor)
    replacement = managed.model_copy(update={'parameters': {'equipment_grip': 1}})
    engine.action_catalog['test:managed'] = replacement
    assert hand_occupancy.supports_grips(engine, actor)
    del engine.action_catalog['test:managed']
    assert not hand_occupancy.supports_grips(engine, actor)
    expected = tuple(a for a in engine.action_catalog.values() if a.owner_id == ME)
    assert catalog_queries.owned_actions(engine, ME) == expected
    engine.action_catalog = dict(reversed(list(engine.action_catalog.items())))
    assert catalog_queries.owned_actions(engine, ME) == tuple(reversed(expected))
    entry = engine._catalog_owner_index
    engine.state.state_version += 1
    assert catalog_queries.owned_actions(engine, ME) == tuple(reversed(expected))
    assert engine._catalog_owner_index is not entry


def test_flight_search_collects_zones_once_and_matches_uncached_edges(monkeypatch):
    engine = duel([])
    actor = engine.state.actors[ME]
    grant(engine, actor, 15)
    calls = []
    original = zones._hooked_zones
    def counted(e):
        calls.append(1)
        return original(e)
    monkeypatch.setattr(zones, '_hooked_zones', counted)
    before = canonical_bytes(engine.state.model_dump(mode='json'))
    cached = flight.reachable(engine, actor)
    assert len(calls) == 1
    assert canonical_bytes(engine.state.model_dump(mode='json')) == before
    calls.clear()
    with monkeypatch.context() as uncached:
        uncached.setattr(read_queries, 'memo', lambda e, k, compute: compute())
        raw = flight.reachable(engine, actor)
    assert cached == raw and len(calls) > 10
    # No cache survives into a later query, even for unversioned direct edits.
    actor.movement_remaining_ft = 0
    assert flight.reachable(engine, actor) == {}


def test_area_prices_separate_origins_destinations_versions_and_return_fresh_sets(monkeypatch):
    engine = duel([])
    actor = engine.state.actors[ME]
    calls = []
    def price(e, a, destination):
        calls.append(1)
        return destination.x == a.position.x
    monkeypatch.setattr(spatial_areas, '_difficult_at', price)
    from combat import ext
    original = ext.run
    def answers(name, *args):
        return [{(1, 1)}] if name == 'difficult_exempt' else original(name, *args)
    monkeypatch.setattr(ext, 'run', answers)
    @read_queries.pure
    def query(e):
        destination = actor.position
        assert spatial_areas.difficult_at(e, actor, destination)
        assert spatial_areas.difficult_at(e, actor, destination)
        assert len(calls) == 1
        cells = motion.exempt_cells(e, actor)
        cells.clear()
        assert motion.exempt_cells(e, actor) == {(1, 1)}
        actor.position = actor.position.model_copy(update={'x': actor.position.x + 1})
        assert not spatial_areas.difficult_at(e, actor, destination)
        for component in ('state_version', 'event_sequence'):
            setattr(e.state, component, getattr(e.state, component) + 1)
            assert not spatial_areas.difficult_at(e, actor, destination)
        assert len(calls) == 4
    query(engine)
    spatial_areas.difficult_at(engine, actor, actor.position)
    assert len(calls) == 5


def test_table_grip_queries_remain_exact_after_commit_and_reload(tmp_path):
    from combat.gate5_service import CombatService
    from tests.test_tabletop_hunt6 import table_fight, LEFT, HOLD
    from tests.test_lock2_persistence import act
    combat, table, mid = table_fight(tmp_path, [])
    session = combat._load_session(mid)
    engine = session.engine
    before = hand_occupancy.supports_grips(engine, engine.state.actors[LEFT])
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert hand_occupancy.supports_grips(loaded.engine, loaded.engine.state.actors[LEFT]) == before
    assert '_catalog_owner_index' not in loaded.engine.state.model_dump(mode='json')
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_area_membership_reuses_branches_but_separates_projections_and_specs(monkeypatch):
    engine = duel([])
    actor = engine.state.actors[ME]
    origin = actor.position
    area = {'shape': 'sphere', 'size_ft': 15}
    calls = []
    original = spatial_areas.reaches
    def counted(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(spatial_areas, 'reaches', counted)
    @read_queries.pure
    def query(e):
        assert spatial_areas.actor_in_area(e, actor, origin, origin, area)
        assert spatial_areas.actor_in_area(e, actor, origin, origin, area)
        assert len(calls) == 1
        # Recipient policy selects who is checked; it cannot change a square's
        # geometric membership. Equivalent scoped dictionaries share the read.
        assert spatial_areas.actor_in_area(e, actor, origin, origin,
                                          {**area, 'recipients':'hostile', 'exclude_self':True})
        assert len(calls) == 1
        assert spatial_areas.actor_in_area(e, actor, origin, origin,
                                          {**area, 'spreads':False, 'duration':{'rounds':10},
                                           'source_profile':{'damage':99}})
        assert len(calls) == 1
        far = Position(x=11, y=11)
        assert not spatial_areas.actor_in_area(e, actor, origin, origin, area, at=far)
        projection = actor.model_copy(update={'position': far})
        assert not spatial_areas.actor_in_area(e, projection, origin, origin, area)
        other_spec = {**area, 'size_ft': 100}
        assert spatial_areas.actor_in_area(e, projection, origin, origin, other_spec)
        assert len(calls) == 4
    query(engine)
    assert spatial_areas.actor_in_area(engine, actor, origin, origin, area)
    assert len(calls) == 5
    # Next calls see in-place edits even without recorded state changes.
    area['size_ft'] = 5
    assert not spatial_areas.actor_in_area(engine, actor, origin, origin, area, at=Position(x=6,y=6))


def test_volume_position_index_is_call_local_and_shared_across_area_specs(monkeypatch):
    engine = duel([])
    actor = engine.state.actors[ME]
    origin = actor.position
    calls = []
    original = spatial_areas.position
    def counted(cell):
        calls.append(cell)
        return original(cell)
    monkeypatch.setattr(spatial_areas, 'position', counted)
    @read_queries.pure
    def query(e):
        for size in (5, 10, 15):
            assert spatial_areas.actor_in_area(e, actor, origin, origin,
                                              {'shape': 'sphere', 'size_ft': size})
        assert len(calls) == len(e._actor_volume(actor))
        projected = origin.model_copy(update={'x': origin.x + 1})
        assert spatial_areas.actor_positions(e, actor, at=projected)[0] == projected
    query(engine)
    count = len(calls)
    spatial_areas.actor_positions(engine, actor)
    assert len(calls) > count


def test_terrain_memos_retain_projected_actors_until_the_frame_ends():
    import gc, weakref
    engine = duel([])
    @read_queries.pure
    def query(e):
        projection = e.state.actors[ME].model_copy()
        reference = weakref.ref(projection)
        spatial_areas.difficult_at(e, projection, projection.position)
        motion.exempt_cells(e, projection)
        del projection
        gc.collect()
        assert reference() is not None  # id keys cannot be recycled mid-query
        return reference
    reference = query(engine)
    gc.collect()
    assert reference() is None
