"""BOUNCEf1: real face contacts, finite wall crossings and persisted attacks."""
import pytest

from combat import ext, shot_geometry
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.test_lock8_sight import BOUNCE, KIT
from tests.test_lock_choices import install

LEFT, RIGHT = 'actor:factory.left', 'actor:factory.right'


def table_fight(tmp_path, monkeypatch, walls, origin, target, *, shield=False,
                maximum_range=None, normal_range=None):
    shield_kit = {'starting_kit':{'items':[{'item_id':'tianxia.mortal.armor.shield','quantity':1}]}}
    bundles = [compile_character(sheet(features, cl=20,
               kit=KIT if aid == LEFT else shield_kit if shield else None), actor_id=aid)
               for aid, features in ((LEFT, [BOUNCE]),
                   (RIGHT, ['TAL_SHIELD_FLEXIBLE_COVER'] if shield else ['SAND_BASE_SCOURING_HAND']))]
    for bundle in bundles:
        for action in bundle['action_catalog']:
            if 'Bouncing Shot' not in action['display_name']:
                continue
            typed = action['parameters']['typed']
            if maximum_range is not None:
                action['range_ft'] = typed['long_range_ft'] = maximum_range
            if normal_range is not None:
                typed['range_ft'] = normal_range
        bundle['actor_template'].update(fly_speed_ft=30, hover=True)
        bundle.pop('bundle_sha256')
        bundle['bundle_sha256'] = canonical_sha256(bundle)
    service = CombatService(ROOT, tmp_path)
    arena = to_battlefield(normalize_map({'display_name':'Face bounce yard', 'width_squares':10,
        'height_squares':10, 'walls':[], 'starts':{'team1':[[origin[0], origin[1]]],
        'team2':[[target[0], target[1]]]}}))
    arena['terrain_regions'] = [{'region_id':f'test:wall-{i}', 'terrain_type':kind, 'movement_cost':1,
        'height_ft':height, 'cells':[{'x':x, 'y':y} for x,y in cells]}
        for i,(kind,height,cells) in enumerate(walls)]
    mid = service._finish_factory_match(bundles, [LEFT, RIGHT], {LEFT:'team:a', RIGHT:'team:b'},
        {aid:dict(zip(('x','y','z'), xyz)) for aid,xyz in ((LEFT, origin), (RIGHT, target))},
        arena, [LEFT], [RIGHT], control_modes={LEFT:'MANUAL', RIGHT:'MANUAL'},
        match_seed='BOUNCEf1', display_name='Face bounce yard', maximum_rounds=10)['match_id']
    def focus(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == LEFT:
            engine._gain_resource(engine.state.actors[LEFT], 'resource:core.martial_focus', 1, 'test:ready')
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), focus])
    install(monkeypatch, 'd20_result', lambda *a:{'source_id':'test:roll', 'operation':'replace', 'natural_result':10})
    table = TabletopService(service, tmp_path)
    turn(table, mid, LEFT)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    return service, table, mid


def row(origin, waypoint, target, wall):
    return {'source_id':BOUNCE, 'label':'Bouncing Shot reflects from a wall.',
        'path':[dict(zip(('x','y','z'), p)) for p in (origin, waypoint, target)],
        'surface_contacts':[{'path_index':1, 'cell':dict(zip(('x','y'), wall))}]}


def bounce_candidates(service, mid):
    return [c for c in service._load_session(mid).engine.legal_candidates() if 'Bouncing Shot' in c.display_name]


def commit_and_reload(service, table, mid, tmp_path):
    c = bounce_candidates(service, mid)[0]
    receipt = c.metadata['shot_geometry']
    # Table action invokes the persistent session's mechanical execute_intent.
    result = table.act(mid, c.candidate_id, c.decision_id, c.state_version, table.state(mid)['last_sequence'])
    assert result['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.verify()['status'] == fresh.mechanical.replay()['status'] == 'PASS'
    assert fresh.engine.state.actors[LEFT].resources['resource:core.martial_focus'] == 0
    assert any(ev.event_type == 'ATTACK_ROLLED' for ev in fresh.engine.events)
    assert any(ev.payload.get('shot_geometry') == receipt for ev in fresh.engine.events)
    assert getattr(fresh.engine, '_shot_geometry', None) is None
    return receipt


def test_contact_cannot_open_solid_wall_for_outgoing_leg(tmp_path, monkeypatch):
    origin, target = (3,3,0), (7,6,0)
    service, table, mid = table_fight(tmp_path, monkeypatch, [('BLOCKED',20,[(5,5)])], origin, target)
    crossing = row(origin, (4,5,0), target, (5,5))
    from combat.ext.bouncing_shot import applies
    install(monkeypatch, 'sight_path', lambda e,a,t:crossing if applies(shot_geometry.action(e,a)) else None)
    assert not bounce_candidates(service, mid)
    e = service._load_session(mid).engine
    assert not shot_geometry.valid(e, e.state.actors[LEFT], e.state.actors[RIGHT], crossing)
    # Still illegal after a real session intent commit and a cold service reload.
    c = next(c for c in e.legal_candidates() if c.kind == 'END_TURN')
    service._load_session(mid).submit_intent(ActionIntent(intent_id='bounce-negative-end',
        decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version, actor_id=LEFT),
        primary_decision_record=None, reaction_provider=None)
    turn(table, mid, LEFT)
    fresh = CombatService(ROOT, tmp_path)
    assert not bounce_candidates(fresh, mid)
    loaded = fresh._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    assert not any(ev.event_type == 'ATTACK_ROLLED' for ev in loaded.engine.events)


@pytest.mark.parametrize('kind', ['BLOCKED', 'SIGHT_BLOCKED'])
def test_elevated_bounce_crosses_separating_low_wall(tmp_path, monkeypatch, kind):
    origin, target = (2,4,1), (7,4,1)
    walls = [(kind,3,[(5,y) for y in range(10)]), ('BLOCKED',20,[(4,0)])]
    service, table, mid = table_fight(tmp_path, monkeypatch, walls, origin, target)
    receipt = commit_and_reload(service, table, mid, tmp_path)
    assert receipt['route']['surface_contacts'][0]['cell'] == {'x':4, 'y':0}
    assert all(p['z'] == 1 for p in receipt['route']['path'])


def test_equal_chebyshev_distance_is_a_real_face_bend(tmp_path, monkeypatch):
    origin, target = (3,3,0), (5,3,0)
    service, table, mid = table_fight(tmp_path, monkeypatch, [('BLOCKED',20,[(4,5)])], origin, target)
    receipt = commit_and_reload(service, table, mid, tmp_path)
    e = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert receipt['route']['path'][1] == {'x':4, 'y':4}
    assert shot_geometry.length(e, receipt['route']) == 15
    assert e.grid.distance_ft(e.state.actors[LEFT].position, e.state.actors[RIGHT].position) == 10


def test_reversing_direction_at_a_face_is_a_real_bounce(tmp_path, monkeypatch):
    service, table, mid = table_fight(tmp_path, monkeypatch, [('BLOCKED',20,[(3,6)])], (3,3,0), (3,4,0))
    receipt = commit_and_reload(service, table, mid, tmp_path)
    assert receipt['route']['path'][1] == {'x':3, 'y':5}


def test_corner_route_has_a_reachable_face_and_keeps_overlapping_spans(tmp_path, monkeypatch):
    # Both legs approach a corner wall from its west side, reflecting at its
    # actual west face without crossing that wall's interior.
    origin, target = (3,3,0), (3,7,0)
    walls = [('BLOCKED',20,[(5,5)])]
    service, table, mid = table_fight(tmp_path, monkeypatch, walls, origin, target)
    receipt = commit_and_reload(service, table, mid, tmp_path)
    route = receipt['route']
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    e = loaded.engine
    assert route['surface_contacts'][0]['cell'] == {'x':5, 'y':5}
    # A new overlapping solid span on the waypoint blocks the face approach.
    waypoint = route['path'][1]
    cell = (waypoint['x'], waypoint['y'])
    e.grid.blocked.add(cell)
    e.grid.terrain_spans.setdefault('BLOCKED', {})[cell] = [(0,20)]
    assert not shot_geometry.valid(e, e.state.actors[LEFT], e.state.actors[RIGHT], route)


def test_wall_top_is_exclusive_and_above_top_does_not_reflect(tmp_path, monkeypatch):
    service, table, mid = table_fight(tmp_path, monkeypatch, [('BLOCKED',5,[(4,5)])], (3,3,1), (5,3,1))
    assert not bounce_candidates(service, mid)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_shared_span_geometry_checks_fractional_faces_and_infinite_walls():
    from combat.space import SurfacePoint
    from combat.terrain_occlusion import cell_span_hit
    from fractions import Fraction
    face = SurfacePoint(Fraction(9,2), 5, 1)
    assert not cell_span_hit(SurfacePoint(3,3,1), face, (5,5), 0, None)
    assert cell_span_hit(face, SurfacePoint(7,6,2), (5,5), 0, None)
    assert not cell_span_hit(face, SurfacePoint(3,6,1), (5,5), 0,20)


def test_elevated_face_waypoint_above_low_blocked_cell(tmp_path, monkeypatch):
    walls = [('BLOCKED',3,[(5,y) for y in range(10)] + [(4,1)]), ('BLOCKED',20,[(4,0)])]
    service, table, mid = table_fight(tmp_path, monkeypatch, walls, (2,4,1), (7,4,1))
    receipt = commit_and_reload(service, table, mid, tmp_path)
    assert receipt['route']['path'][1] == {'x':4, 'y':1, 'z':1}
    assert receipt['route']['surface_contacts'][0]['cell'] == {'x':4, 'y':0}


@pytest.mark.parametrize('edge,expected', [('N',0), ('E',5)])
def test_face_outgoing_ray_drives_shield_cover_table_reload(tmp_path, monkeypatch, edge, expected):
    from combat.ext import shield_faces
    from tests.test_shield_fix_r1 import table_action
    service, table, mid = table_fight(tmp_path, monkeypatch, [('BLOCKED',20,[(5,5)])],
                                    (3,3,0), (3,6,0), shield=True)
    # Choose the actual Flexible Cover edge; decline rotating it during the shot.
    monkeypatch.setattr(shield_faces, 'ask', lambda e,i,checkpoint,*a,**kw:
                        [edge] if checkpoint == 'SHIELD_FACE_EDGE' else [])
    turn(table, mid, RIGHT)
    assert table_action(table, mid, 'FLEXIBLE COVER')['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    target = service._load_session(mid).engine.state.actors[RIGHT]
    assert any(c.condition_id == shield_faces.FACE and c.data['edge'] == edge
               for c in target.conditions.values())
    receipt = commit_and_reload(service, table, mid, tmp_path)
    assert receipt['route']['path'][1] == {'x':4, 'y':5}
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    rolls = [ev for ev in fresh.engine.events if ev.event_type == 'ATTACK_ROLLED']
    assert rolls and all(ev.payload['cover_bonus'] == expected for ev in rolls)
    base_ac = target.armor_class + fresh.engine._ac_modifier(fresh.engine.state.actors[RIGHT])
    assert all(ev.payload['target_ac'] == base_ac + expected for ev in rolls)


def test_face_outgoing_ray_drives_terrain_cover_table_reload(tmp_path, monkeypatch):
    walls = [('BLOCKED',20,[(5,5)]), ('SIMPLE_COVER',20,[(4,6)])]
    service, table, mid = table_fight(tmp_path, monkeypatch, walls, (3,3,0), (3,6,0))
    receipt = commit_and_reload(service, table, mid, tmp_path)
    assert receipt['cover_before'] == receipt['cover_after'] == 2
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert all(ev.payload['cover_bonus'] == 2 for ev in fresh.engine.events if ev.event_type == 'ATTACK_ROLLED')


@pytest.mark.parametrize('maximum,allowed', [(15,False), (19,False), (20,True), (21,True)])
def test_face_total_travel_range_boundary_table_reload(tmp_path, monkeypatch, maximum, allowed):
    service, table, mid = table_fight(tmp_path, monkeypatch, [('BLOCKED',20,[(3,6)])],
                                    (3,3,0), (3,4,0), maximum_range=maximum)
    # HOLD_POSITION above is a persisted session execute_intent, including focus.
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    assert bool(bounce_candidates(service, mid)) == allowed
    if allowed:
        receipt = commit_and_reload(service, table, mid, tmp_path)
        fresh = CombatService(ROOT, tmp_path)._load_session(mid)
        assert shot_geometry.length(fresh.engine, receipt['route']) == 20
        assert 'travels 20 feet' in receipt['route']['label']
    else:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
        fresh = CombatService(ROOT, tmp_path)._load_session(mid)
        assert fresh.verify()['status'] == fresh.mechanical.replay()['status'] == 'PASS'
        assert not any(ev.event_type == 'ATTACK_ROLLED' for ev in fresh.engine.events)
        assert fresh.engine.state.actors[LEFT].resources['resource:core.martial_focus'] == 1


@pytest.mark.parametrize('normal,mode', [(34,'DISADVANTAGE'), (35,'NORMAL')])
def test_face_total_travel_normal_range_mode_table_reload(tmp_path, monkeypatch, normal, mode):
    # Ten feet of direct separation avoids the independent adjacent-enemy penalty.
    service, table, mid = table_fight(tmp_path, monkeypatch, [('BLOCKED',20,[(3,6)])],
                                    (3,3,0), (3,1,0), maximum_range=35, normal_range=normal)
    receipt = commit_and_reload(service, table, mid, tmp_path)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert 'travels 35 feet' in receipt['route']['label']
    rolls = [ev for ev in fresh.engine.events if ev.event_type == 'ATTACK_ROLLED']
    assert rolls and all(ev.payload['mode'] == mode for ev in rolls)


def test_shared_contact_path_rounds_total_up_once():
    from types import SimpleNamespace
    from combat.gate2_grid import SquareGrid
    e = SimpleNamespace(grid=SquareGrid({'width_squares':10, 'height_squares':10,
                                       'square_size_ft':5, 'starting_positions':{}, 'terrain_regions':[]}))
    route = row((3,3,0), (4,5,0), (3,6,0), (5,5))
    # 10 + 7.5 feet: ceiling of the summed path, never truncating a half foot.
    assert shot_geometry.length(e, route) == 18
    assert route['path'][1] == {'x':4,'y':5,'z':0}
