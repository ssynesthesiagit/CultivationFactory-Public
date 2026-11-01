"""Direct engine menus own the same pure-query boundary as service menus."""
from combat.ext import objects
from combat.gate2_runtime_models import ZoneState
from tests.h1_support import duel
from tests.test_speed2_queries import _wall


def test_direct_menus_validate_walls_once_and_observe_unrecorded_edits(monkeypatch):
    engine = duel([])
    wall = _wall(engine)
    seen = []
    init = ZoneState.__init__
    def counted(self, *args, **kwargs):
        if kwargs.get('zone_id') == f'zone:{wall.object_id}':
            seen.append(wall.position)
        init(self, *args, **kwargs)
    monkeypatch.setattr(ZoneState, '__init__', counted)
    first = engine.legal_candidates()
    assert first and len(seen) == 1
    assert engine.legal_candidates() == first and len(seen) == 2
    # No recorded clock advance: a later independent menu still sees the edit.
    wall.destroyed = True
    engine.legal_candidates()
    assert len(seen) == 2 and objects.blocking_zones(engine) == []


def test_temporary_query_inputs_live_exactly_as_long_as_their_identity_cache(monkeypatch):
    import gc
    import weakref
    from combat import ext
    from combat.hook_queries import actor_action
    from combat.read_queries import candidate_pass
    from tests.h1_support import ME
    from tests.test_speed2_queries import _probe

    engine = duel([])
    actor = engine.state.actors[ME].model_copy(deep=True)
    action = engine.action_catalog[actor.action_ids[0]].model_copy()
    actor_ref, action_ref = weakref.ref(actor), weakref.ref(action)
    def provider(*args):
        return False
    _probe(monkeypatch, 'speed2_lifetime', [provider])
    monkeypatch.setitem(ext._HOOK_QUERY_KEYS, ('speed2_lifetime', provider), actor_action)
    with candidate_pass(engine):
        assert ext.any_false('speed2_lifetime', engine, actor, None, action)
        del actor, action
        gc.collect()
        assert actor_ref() is not None and action_ref() is not None
    gc.collect()
    assert actor_ref() is None and action_ref() is None


def test_custom_object_geometry_keeps_its_projected_dependencies(monkeypatch):
    from combat import ext
    from combat.read_queries import candidate_pass
    from combat.gate2_runtime_models import Position
    from tests.h1_support import ME

    engine = duel([])
    _wall(engine)
    actor = engine.state.actors[ME]
    def following_geometry(engine, obj):
        return (engine.state.actors[ME].position,)
    ext._load()
    monkeypatch.setitem(ext._HOOKS, 'object_target_cells', [following_geometry])
    with candidate_pass(engine):
        first = objects.blocking_zones(engine)[0].affected_cells
        assert first == (actor.position,)
        actor.position = Position(x=actor.position.x + 1, y=actor.position.y)
        assert objects.blocking_zones(engine)[0].affected_cells == (actor.position,) != first


def test_new_static_geometry_registration_invalidates_derived_walls(monkeypatch):
    from combat import ext
    from combat.read_queries import candidate_pass
    from combat.gate2_runtime_models import Position

    engine = duel([])
    wall = _wall(engine)
    ext._load()
    monkeypatch.setitem(ext._HOOKS, 'object_target_cells', [objects.rectangular_cells])
    monkeypatch.setattr(ext, '_STABLE_QUERIES', set(ext._STABLE_QUERIES))
    with candidate_pass(engine):
        assert objects.blocking_zones(engine)[0].affected_cells == (wall.position,)
        @ext.hook('object_target_cells', stable=True)
        def geometry(engine, obj):
            return (Position(x=2, y=2),)
        assert objects.blocking_zones(engine)[0].affected_cells == (Position(x=2, y=2),)
