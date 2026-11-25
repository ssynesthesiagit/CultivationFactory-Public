"""Altitude, passage and intercepted geometry through accepted Table actions."""
import pytest

from combat import action_geometry, ext, shot_geometry
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
from combat.gate5_service import CombatService
from combat.tabletop import TabletopMapStore
from combat.tabletop_service import TabletopService
from tests import test_lock9_origins_review as O, test_lock9_sight_review as B
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT
from tests.r10_fixup_support import commit
from tests.test_lock10_flight_movement import grant
from tests.test_lock2_persistence import act


def lift(engine, who, z=2):
    actor = engine.state.actors[who]
    grant(engine, actor, flight_hover=1)
    before = actor.position
    actor.position = before.model_copy(update={'z': z})
    engine._append_event('MOVEMENT_COMMITTED', 'test:lift', actor_id=who,
        payload={'destination': actor.position.model_dump(mode='json'),
                 'path': [before.model_dump(mode='json'), actor.position.model_dump(mode='json')], 'cost_ft': 0})


def at_hold(monkeypatch, owner, callback):
    def run(engine, kind, payload):
        if kind == 'HOLD_POSITION_COMMITTED' and payload.get('actor_id') == owner:
            callback(engine)
    O.add_hook(monkeypatch, 'event', run)


def send(service, ui, mid, candidate):
    sequence = ui.state(mid)['last_sequence']
    return lambda answers=(): ui.act(mid, candidate.candidate_id, candidate.decision_id,
        candidate.state_version, sequence, list(answers))


def checked(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def test_owned_marked_origin_at_altitude_survives_table_menu_and_replay(monkeypatch, tmp_path):
    at_hold(monkeypatch, O.OWNER, lambda e: lift(e, O.ANCHOR))
    service, ui, mid = O.table(monkeypatch, tmp_path)
    engine = service._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.metadata.get('effect_origin') and c.target_ids == (O.FOE,))
    assert c.metadata['effect_origin']['position']['z'] == 2
    commit(send(service, ui, mid, c))
    engine = checked(tmp_path, mid)
    assert engine.state.actors[O.OWNER].position == Position(x=1, y=6)
    assert engine.state.actors[O.FOE].current_hp < engine.state.actors[O.FOE].maximum_hp


def test_owned_bouncing_shot_at_altitude_survives_table_menu_and_replay(monkeypatch, tmp_path):
    at_hold(monkeypatch, B.OWNER, lambda e: lift(e, B.OWNER))
    service, mid, candidate, send_action = B.table(monkeypatch, tmp_path)
    assert candidate.metadata['shot_geometry']['route']['path'][0]['z'] == 2
    commit(send_action)
    engine = checked(tmp_path, mid)
    assert any(ev.event_type == 'ATTACK_ROLLED' and ev.actor_id == B.OWNER for ev in engine.events)
    assert engine.state.actors[B.OWNER].resources['resource:core.martial_focus'] == 0


def test_flight_can_stop_then_depart_above_finite_wall(monkeypatch, tmp_path):
    original = TabletopMapStore.save
    def save(store, definition):
        return original(store, {**definition, 'walls': [
            {'shape': 'rect', 'points': [[4,4],[6,5]], 'height_ft': 5}],
            'starts': {'team1': [[3,4],[1,1]], 'team2': [[9,6]]}})
    monkeypatch.setattr(TabletopMapStore, 'save', save)
    at_hold(monkeypatch, H.LEFT, lambda e: grant(e, e.state.actors[H.LEFT], flight_hover=1))
    service, ui, mid = H.table_fight(tmp_path, [])
    assert act(ui, mid, H.HOLD)['status'] == 'COMMITTED'
    for destination in [Position(x=4, y=4, z=2), Position(x=5, y=4, z=2)]:
        engine = service._load_session(mid).engine
        c = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination == destination)
        commit(send(service, ui, mid, c))
        engine = checked(tmp_path, mid)
        assert engine.state.actors[H.LEFT].position == destination
        assert not any('returns to the last free space' in ev.payload.get('log', '') for ev in engine.events)
        service = CombatService(ROOT, tmp_path); ui = TabletopService(service, tmp_path)


@pytest.mark.parametrize('remote', [False, True])
def test_table_area_range_uses_destination_and_origin_altitude(monkeypatch, tmp_path, remote):
    source = 'test:altitude-area'
    def compile_actions(info):
        if info['actor_id'] != H.LEFT:
            return []
        return [ActionDefinition(source_definition_id=source, display_name='Altitude burst',
            owner_id=H.LEFT, economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='CELL',
            range_ft=30, radius_ft=5, parameters={'typed': {'source': source, 'effects': [],
                'area': {'shape': 'sphere', 'size_ft': 5}, 'zone_spec': {'name': 'Altitude burst'}, 'numbers': {}}})]
    O.add_hook(monkeypatch, 'compile_actions', compile_actions)
    if remote:
        O.add_hook(monkeypatch, 'effect_origins', lambda e,a,action: [
            {'id': 'test:high-anchor', 'label': 'High anchor', 'position': {'x':3,'y':4,'z':20}}]
            if action.source_definition_id == source else None)
    at_hold(monkeypatch, H.LEFT, lambda e: lift(e, H.RIGHT, 20))
    service, ui, mid = H.table_fight(tmp_path, [])
    assert act(ui, mid, H.HOLD)['status'] == 'COMMITTED'
    engine = service._load_session(mid).engine
    assert source in engine.action_catalog
    destination = engine.state.actors[H.RIGHT].position
    choices = [c for c in engine.legal_candidates() if c.source_definition_id == source and c.destination == destination]
    assert bool(choices) == remote
    if choices:
        commit(send(service, ui, mid, choices[0]))
    checked(tmp_path, mid)


def test_interception_keeps_remote_target_inside_shortened_range(monkeypatch, tmp_path):
    O.add_hook(monkeypatch, 'technique_declared', lambda e,a,action,c,i:
        {'source_id': 'test:range-cap', 'label': 'Shortened reach', 'range_delta_ft': -10}
        if c.metadata.get('effect_origin') else None)
    service, ui, mid = O.table(monkeypatch, tmp_path)
    engine = service._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.metadata.get('effect_origin') and c.target_ids == (O.FOE,))
    action = engine.action_catalog[c.source_definition_id]
    assert action.range_ft - 10 >= 45 and action.range_ft - 10 < 75
    commit(send(service, ui, mid, c))
    engine = checked(tmp_path, mid)
    assert any(ev.event_type == 'ATTACK_ROLLED' and ev.actor_id == O.OWNER for ev in engine.events)
    assert engine.state.actors[O.FOE].current_hp < engine.state.actors[O.FOE].maximum_hp


def test_interception_rechecks_full_paid_bouncing_route(monkeypatch, tmp_path):
    def cap(e, a, action, c, intent):
        if not c.metadata.get('shot_geometry', {}).get('route'):
            return None
        target = e.state.actors[c.target_ids[0]]
        direct = e._distance_actor_to_actor(a, target)
        route = c.metadata['shot_geometry']['route']['path']
        length = sum(e.grid.distance_ft(Position(**x), Position(**y)) for x,y in zip(route, route[1:]))
        assert length > direct
        return {'source_id':'test:range-cap', 'label':'Shortened reach', 'range_delta_ft': direct - action.range_ft}
    O.add_hook(monkeypatch, 'technique_declared', cap)
    service, mid, c, send_action = B.table(monkeypatch, tmp_path)
    commit(send_action)
    engine = checked(tmp_path, mid)
    assert not any(ev.event_type == 'ATTACK_ROLLED' and ev.actor_id == B.OWNER for ev in engine.events)
    assert engine.state.actors[B.OWNER].resources['resource:core.martial_focus'] == 0
    assert any('range was reduced' in ev.payload.get('log', '') for ev in engine.events)
