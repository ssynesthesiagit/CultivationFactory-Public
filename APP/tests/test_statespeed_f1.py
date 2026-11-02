"""State speed caches stay isolated and are scoped to the saved state version."""
from combat import action_legality
from combat.senses import perception
from combat.tabletop_service import TabletopService
from tests.test_door_interaction import DOOR, FOE, ME, setup


def test_cached_target_refusal_is_copied_for_every_caller(tmp_path):
    service, session = setup(tmp_path)
    engine = session.engine
    source = 'system:door.open.free'
    actor = engine.state.actors[ME]
    actor.resources['resource:core.qi'] = 0
    engine.action_catalog[source] = engine.action_catalog[source].model_copy(
        update={'costs': (('resource:core.qi', 3),)})
    service._legal_candidates(session)
    frame = engine._cf_availability
    refusal = frame[4][source]['result']
    assert refusal['code'] == 'COST' and 'details' in refusal

    first = action_legality.query_targets(engine, ME, [(source, DOOR)])
    answer = first[(source, DOOR)]
    answer['reason'] = 'caller changed this'
    answer['details']['costs'][0][1] = 99

    assert frame[4]['system:door.open.free']['result'] == refusal
    assert action_legality.query_targets(engine, ME, [(source, DOOR)])[(source, DOOR)] == refusal


def test_fog_perception_is_cached_per_viewer_and_invalidated_by_state_version(monkeypatch, tmp_path):
    service, session = setup(tmp_path)
    table = TabletopService(service, tmp_path)
    engine = session.engine
    calls = []

    def counted(engine_arg, viewer):
        calls.append(viewer.entity_id)
        return perception(engine_arg, viewer)

    monkeypatch.setattr('combat.senses.perception', counted)
    viewers = table._own_fog_viewers(engine, (ME,))
    assert viewers == {ME}
    first = table._fog_perception(session.match_id, engine, viewers)
    second = table._fog_perception(session.match_id, engine, viewers)
    assert first == second
    assert calls == [ME]

    engine.state.state_version += 1
    refreshed = table._fog_perception(session.match_id, engine, viewers)
    assert refreshed == first
    assert calls == [ME, ME]


def test_own_fog_snapshot_only_returns_the_bound_fighter_perception(tmp_path):
    service, session = setup(tmp_path)
    table = TabletopService(service, tmp_path)
    all_views = table.state(session.match_id, fog=True)
    own_view = table.state(session.match_id, fog=True, fog_view='own', fog_actor_ids=(ME,))

    assert set(all_views['fog_perception']) == {ME, FOE}
    assert set(own_view['fog_perception']) == {ME}
    assert {k: v for k, v in own_view.items() if k not in {'fog_perception', 'fog_geometry'}} == {
        k: v for k, v in all_views.items() if k not in {'fog_perception', 'fog_geometry'}}
    own_geometry = dict(own_view['fog_geometry'])
    all_geometry = dict(all_views['fog_geometry'])
    own_limits = own_geometry.pop('limits', {})
    all_limits = all_geometry.pop('limits', {})
    assert own_geometry == all_geometry
    assert own_limits == ({ME: all_limits[ME]} if ME in all_limits else {})
