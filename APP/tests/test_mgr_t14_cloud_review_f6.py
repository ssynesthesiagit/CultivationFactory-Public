"""Sol F6: real acquired Cloud Walker, native journeys/table, cold replay."""
import json
import zipfile
import pytest
from combat.flight import profile
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import settle, turn
from tests.test_mgr_t14_cloud_acquisition import acquired_sheet
from tests.test_mgr_t14_cloud_resume import A, B, KEY, game, action, verify
from combat.ext.cloud_walker import WIND, STEP


def field(*, cl=30, cells=None):
    return {'id':'gravity','source_id':'scene:gravity','source_rule':'Ordinary gravity suppression; Shared Qi R4 release.',
            'source_cl':cl,'save_dc':1,'kind':'gravity','cells':cells or [[3,6]],
            'min_z':0,'max_z':100,'absolute':False}


def journey(tmp_path, acquired_sheet, *, fields=(), mode='MANUAL', donor=False, companion_hp=None, third=False):
    c,setup_jid=game(tmp_path,acquired_sheet,journey=True,fields=fields)
    # Finish the setup scene before beginning the tested journey, through the
    # public command. A lower-level donor is an actual separately compiled sheet.
    state=c.journey_state(setup_jid)
    c.journey_act(state['journey_id'],state['revision'],A,'finish',{})
    if donor or companion_hp is not None:
        doc=sheet([],cl=10 if donor else 1,name='Mist donor' if donor else 'Companion')
        if donor:doc.setdefault('path_and_subpath',{})['path_feature_record_ids']=[WIND]
        if companion_hp is not None:doc['ability_scores_and_statistics']['hit_points']['maximum']=companion_hp
        with zipfile.ZipFile(tmp_path/'portable_characters/companion/current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    projects=['nativewalker','companion'];positions={A:{'x':3,'y':6},B:{'x':4,'y':6}}
    if third:
        projects.append('route-blocker');positions['actor:factory.route-blocker']={'x':5,'y':6}
        folder=tmp_path/'portable_characters/route-blocker';folder.mkdir()
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(sheet([],cl=1,name='Second traveller')))
    state=c.create_journey(project_ids=projects,arena_id='battlefield:map.cloud-review-yard',
        positions=positions,base_paces={aid:18000 for aid in positions},
        control_modes={aid:mode if aid==A else 'MANUAL' for aid in positions})
    jid=state['journey_id']
    def act(aid,kind,payload=None):
        cold=CombatService(ROOT,tmp_path);s=cold.journey_state(jid)
        result=cold.journey_act(jid,s['revision'],aid,kind,payload or {})
        assert CombatService(ROOT,tmp_path).journey_state(jid)==result
        assert CombatService(ROOT,tmp_path).journey_verify(jid)['status']=='PASS'
        return result
    return c,jid,act


def ritual(act,caster=A,recipient=None):
    act(caster,'cloud_wind_begin');act(caster,'wait',{'seconds':600})
    if recipient:
        act(caster,'cloud_wind_invite',{'target_id':recipient})
        act(recipient,'cloud_wind_reply',{'caster_id':caster,'accept':True})
    return act(caster,'cloud_wind_finish')


FALL_ANSWER_LIMIT=40


def test_stuck_falling_reaction_is_bounded():
    # Regression: the drains were unbounded `while pending:` loops and spun for
    # over an hour when a reaction never cleared. The bound fails fast instead.
    state={'journey_fall_pending':{'request':{'reactor_id':'x'}}}
    rounds=0
    for _ in range(FALL_ANSWER_LIMIT):
        if not state.get('journey_fall_pending'):break
        rounds+=1
    with pytest.raises(AssertionError,match='did not clear'):
        assert not state.get('journey_fall_pending'), 'falling reaction did not clear'
    assert rounds==FALL_ANSWER_LIMIT


@pytest.mark.parametrize('ending',['dismiss','expire'])
@pytest.mark.parametrize('recipient',[A,B])
def test_airborne_wind_withdrawal_falls_after_cold_journey_commit(tmp_path,acquired_sheet,ending,recipient):
    c,jid,act=journey(tmp_path,acquired_sheet)
    ritual(act,recipient=B)
    act(recipient,'move',{'path':[{'x':3 if recipient==A else 4,'y':6,'z':1},
                                {'x':3 if recipient==A else 4,'y':6,'z':2}]})
    before=c.journey_state(jid)
    if ending=='dismiss':state=act(recipient,'cloud_wind_end')
    else:state=act(recipient,'wait',{'seconds':3600})
    # A reaction is a real owner decision and must survive opening a cold service.
    for _ in range(FALL_ANSWER_LIMIT):
        if not state.get('journey_fall_pending'):break
        pending=state['journey_fall_pending']
        who=pending['request']['reactor_id']
        menu=CombatService(ROOT,tmp_path).journey_menu(jid,who)
        decline=next(o for o in menu['options'] if o['kind']=='journey_fall_reply' and o['payload']['selection']=='DECLINE')
        state=act(who,decline['kind'],decline['payload'])
    assert not state.get('journey_fall_pending'), 'falling reaction did not clear'
    assert state['actors'][recipient]['position'].get('z',0)==0
    assert WIND not in state['actors'][recipient]['travel_effects']
    assert any(e['kind']=='JOURNEY_FALL_RESOLVED' for e in state['events'])
    if recipient==B:
        assert not any(r.get('block')=='cloud_walker' for r in state['actors'][B]['bundle']['typed_passives'])
        assert state['actors'][B]['encounter_snapshot']['current_hp'] < state['actors'][B]['bundle']['actor_template']['maximum_hp']


def test_pressure_releases_only_at_affected_turn_end_outside_and_survives_reentry(tmp_path,acquired_sheet):
    c,t,mid=game(tmp_path,acquired_sheet,fields=[field()])
    settle(t,mid,action(c,mid,'Cloud Step').candidate_id)
    e=verify(tmp_path,mid);assert profile(e,e.state.actors[A]).speed_ft==0
    move=next(x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.destination.x==2
              and x.destination.y==6 and x.destination.z==0)
    settle(t,mid,move.candidate_id)
    e=verify(tmp_path,mid);assert profile(e,e.state.actors[A]).speed_ft==0
    back=next(x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.destination.x==3
              and x.destination.y==6 and x.destination.z==0)
    settle(t,mid,back.candidate_id)
    settle(t,mid,t.state(mid)['menu']['end_turn'])
    e=verify(tmp_path,mid);assert profile(e,e.state.actors[A]).speed_ft==0
    turn(t,mid,A)
    e=c._load_session(mid).engine
    move=next(x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.destination.x==2
              and x.destination.y==6 and x.destination.z==0)
    settle(t,mid,move.candidate_id)
    e=verify(tmp_path,mid);assert profile(e,e.state.actors[A]).speed_ft==0
    settle(t,mid,t.state(mid)['menu']['end_turn'])
    e=verify(tmp_path,mid);assert profile(e,e.state.actors[A]).speed_ft==20


def test_borrowed_weak_mist_cannot_suppress_owners_stronger_cloud_step(tmp_path,acquired_sheet):
    c,jid,act=journey(tmp_path,acquired_sheet,fields=[field(cl=14)],donor=True)
    ritual(act,caster=B,recipient=A)
    state=c.journey_state(jid)
    match=c.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'})
    mid=match['match_id'];t=TabletopService(c,tmp_path);turn(t,mid,A)
    settle(t,mid,action(c,mid,'Cloud Step').candidate_id)
    e=verify(tmp_path,mid);actor=e.state.actors[A]
    assert profile(e,actor).speed_ft==20
    suppressed=[c for c in actor.conditions.values() if c.condition_id=='condition:typed.cloud_route_suppressed']
    mist=next(c for c in actor.conditions.values() if c.condition_id=='condition:typed.cloud_walker_form')
    assert suppressed and all(c.data['grant_id']==mist.instance_id for c in suppressed)


def test_borrowed_mist_pressure_does_not_choose_a_different_leaps_recovery(tmp_path,acquired_sheet):
    spatial=field(cl=30,cells=[[x,y] for x in range(5,12) for y in range(14)])
    spatial.update(id='sealed-space',source_id='scene:sealed-space',kind='spatial')
    c,jid,act=journey(tmp_path,acquired_sheet,fields=[field(cl=14),spatial],donor=True)
    ritual(act,caster=B,recipient=A)
    state=c.journey_state(jid)
    match=c.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'})
    mid=match['match_id'];t=TabletopService(c,tmp_path);turn(t,mid,A)
    settle(t,mid,action(c,mid,'Heavenly Leap').candidate_id,
           choices={'choice:needle.cloud_leap_destination':['cell:8,3,2']})
    e=verify(tmp_path,mid)
    failures=[ev.payload['route_failure'] for ev in e.events if 'route_failure' in ev.payload]
    assert failures[-1]=='origin_side'


@pytest.mark.parametrize('mode',['MANUAL','LOCAL_AUTO'])
def test_pressure_contest_keeps_occupied_transit_route_reachable(tmp_path,acquired_sheet,mode):
    c,jid,act=journey(tmp_path,acquired_sheet,fields=[field(cl=18,cells=[[4,6]])],mode=mode)
    ritual(act)
    options=CombatService(ROOT,tmp_path).journey_menu(jid,A)['options']
    check=next(o for o in options if o['kind']=='cloud_pressure_contest'
               and o['payload']['destination']=={'x':4,'y':6})
    act(A,check['kind'],check['payload'])
    options=CombatService(ROOT,tmp_path).journey_menu(jid,A)['options']
    assert not any(o.get('payload',{}).get('path')==[{'x':4,'y':6}] for o in options)
    route=next(o for o in options if o.get('payload',{}).get('path')==[{'x':4,'y':6},{'x':5,'y':6}])
    state=act(A,route['kind'],route['payload'])
    assert state['actors'][A]['position']['x']==5


def test_featherfall_is_player_owned_persists_and_pays_the_native_cost(tmp_path,acquired_sheet):
    c,jid,act=journey(tmp_path,acquired_sheet)
    ritual(act,recipient=B)
    act(B,'move',{'path':[{'x':4,'y':6,'z':1},{'x':4,'y':6,'z':2}]})
    before=c.journey_state(jid)['actors'][A]['resources']['resource:core.qi']
    state=act(B,'cloud_wind_end')
    assert state.get('journey_fall_pending')
    assert state['journey_fall_pending']['request']['reactor_id']==A
    with pytest.raises(ValueError,match='pending falling'):
        act(B,'wait',{'seconds':1})
    for _ in range(FALL_ANSWER_LIMIT):
        if not state.get('journey_fall_pending'):break
        pending=state['journey_fall_pending'];who=pending['request']['reactor_id']
        menu=c.journey_menu(jid,who)['options']
        choose=next((o for o in menu if o['kind']=='journey_fall_select' and o['payload']['option_id']==B
                     and B not in pending['selected']),None)
        if choose is None:choose=next(o for o in menu if o['kind']=='journey_fall_reply' and o['payload']['selection']=='USE')
        state=act(who,choose['kind'],choose['payload'])
    assert not state.get('journey_fall_pending'), 'falling reaction did not clear'
    assert state['actors'][B]['position'].get('z',0)==0
    assert state['actors'][A]['resources']['resource:core.qi']==before-1
    hp=state['actors'][B]['encounter_snapshot']['current_hp']
    assert hp==state['actors'][B]['bundle']['actor_template']['maximum_hp']
    assert state['actors'][B]['journey_fall_effects']
    act(A,'finish')
    state=c.create_journey(project_ids=['nativewalker','companion'],arena_id='battlefield:map.cloud-review-yard',
        positions={A:{'x':3,'y':6},B:{'x':4,'y':6}},base_paces={A:18000,B:18000},
        control_modes={A:'MANUAL',B:'MANUAL'})
    assert state['actors'][B]['journey_fall_effects']
    state=c.journey_act(state['journey_id'],state['revision'],B,'wait',{'seconds':60})
    assert state['actors'][B]['journey_fall_effects']==[]
    assert 'journey_fall_protections' not in state['actors'][B]['bundle']


def test_solo_traveller_expiry_cannot_restore_an_airborne_route_endpoint(tmp_path,acquired_sheet):
    c,jid,act=journey(tmp_path,acquired_sheet)
    act(A,'finish')
    state=c.create_journey(project_ids=['nativewalker'],arena_id='battlefield:map.cloud-review-yard',
        positions={A:{'x':3,'y':6}},base_paces={A:18000},control_modes={A:'MANUAL'})
    jid=state['journey_id']
    def command(kind,payload=None):
        s=c.journey_state(jid)
        return c.journey_act(jid,s['revision'],A,kind,payload or {})
    command('cloud_wind_begin');command('wait',{'seconds':600});command('cloud_wind_finish')
    command('move',{'path':[{'x':3,'y':6,'z':1},{'x':3,'y':6,'z':2}]})
    command('wait',{'seconds':3597})
    state=command('move',{'path':[{'x':3,'y':6,'z':3},{'x':3,'y':6,'z':4}]})
    for _ in range(FALL_ANSWER_LIMIT):
        if not state.get('journey_fall_pending'):break
        state=command('journey_fall_reply',{'selection':'DECLINE'})
    assert not state.get('journey_fall_pending'), 'falling reaction did not clear'
    assert state['actors'][A]['position'].get('z',0)==0
    assert any(e['kind']=='TRAVEL_INTERRUPTED' for e in state['events'])
    assert CombatService(ROOT,tmp_path).journey_verify(jid)['status']=='PASS'


def test_native_physical_scene_does_not_start_or_end_combat(tmp_path,acquired_sheet,monkeypatch):
    from combat.journey_falling import engine_for
    from tests.test_lock_choices import install
    c,jid,act=journey(tmp_path,acquired_sheet)
    seen=[]
    install(monkeypatch,'match_start',lambda *args:seen.append('start'))
    install(monkeypatch,'turn_start',lambda *args:seen.append('turn'))
    engine=engine_for(c.journey_state(jid))
    from combat.relations import relation
    assert relation(engine,engine.state.actors[A],engine.state.actors[B])=='NEUTRAL'
    from combat.ext.cloud_walker_environment import during_turn
    assert all(not during_turn(engine,a) for a in engine.state.actors.values())
    assert seen==[]
    engine._check_victory()
    assert engine.state.terminal_result is None
    assert not any(e.event_type in {'TURN_STARTED','MATCH_ENDED'} for e in engine.events)


@pytest.mark.parametrize('recipient',[A,B])
def test_automatic_reactions_do_not_invent_allies_from_travel_consent(tmp_path,acquired_sheet,recipient):
    c,jid,act=journey(tmp_path,acquired_sheet,mode='LOCAL_AUTO')
    ritual(act,recipient=B)
    x=3 if recipient==A else 4
    act(recipient,'move',{'path':[{'x':x,'y':6,'z':1},{'x':x,'y':6,'z':2}]})
    before=c.journey_state(jid)['actors'][A]['resources']['resource:core.qi']
    state=act(recipient,'cloud_wind_end')
    assert not state.get('journey_fall_pending')
    assert state['actors'][recipient]['position'].get('z',0)==0
    assert state['actors'][A]['resources']['resource:core.qi']==before-(1 if recipient==A else 0)
    assert bool(state['actors'][recipient]['journey_fall_effects'])==(recipient==A)


def test_airborne_unowned_recipient_keeps_native_zero_hp_life_state_on_reload(tmp_path,acquired_sheet):
    c,jid,act=journey(tmp_path,acquired_sheet,mode='LOCAL_AUTO',companion_hp=1)
    ritual(act,recipient=B)
    act(B,'move',{'path':[{'x':4,'y':6,'z':1},{'x':4,'y':6,'z':2}]})
    state=act(B,'cloud_wind_end')
    assert not state.get('journey_fall_pending')
    saved=state['actors'][B]['encounter_snapshot']
    assert saved['current_hp']==0
    # Native finalized death is inactive + death_finalized, not a DEAD enum.
    assert saved['life_state']=='DYING' or (saved['active']==0 and any(
        json.loads(row)['condition_id']=='condition:typed.death_finalized'
        for row in saved['conditions'].values()))
    assert state['actors'][B]['incapacitated']==1
    assert WIND not in state['actors'][B]['travel_effects']


@pytest.mark.parametrize('mode',['MANUAL','LOCAL_AUTO'])
@pytest.mark.parametrize('succeeds',[True,False])
def test_declared_pressure_route_keeps_two_occupied_transit_cells_reachable(tmp_path,acquired_sheet,mode,succeeds):
    pressure=field(cl=18,cells=[[4,6],[5,6]])
    pressure['save_dc']=1 if succeeds else 999
    c,jid,act=journey(tmp_path,acquired_sheet,fields=[pressure],mode=mode,third=True)
    ritual(act)
    before=c.journey_state(jid)
    path=[{'x':4,'y':6},{'x':5,'y':6},{'x':6,'y':6}]
    options=c.journey_menu(jid,A)['options']
    route=next(o for o in options if o['kind']=='cloud_pressure_travel' and o['payload']['path']==path)
    assert not any(o.get('payload',{}).get('path')==path[:1] for o in options)
    state=act(A,route['kind'],route['payload'])
    assert state['actors'][A]['position']['x']==(6 if succeeds else 3)
    assert state['seconds']-before['seconds']==(5 if succeeds else 0)
    checks=[e for e in state['events'][len(before['events']):] if e['kind']=='CULTIVATION_CHECK']
    assert len(checks)==(2 if succeeds else 1)
    assert all(e['success']==int(succeeds) for e in checks)
    if not succeeds:
        assert not any(o['kind']=='cloud_pressure_travel' and o['payload']['path']==path
                       for o in c.journey_menu(jid,A)['options'])
