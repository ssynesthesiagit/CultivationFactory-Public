"""Review regressions through acquired sheets, owner maps and cold services."""
import json
import zipfile
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.gate2_runtime_models import Position
from combat.gate2_runtime_content import AN
from combat.factory_compiler import compile_character
from combat.ext.qi_subpaths_five import CLOUD
from tests.h1_support import ROOT, sheet
from tests.worker2_support import settle, turn
from tests.test_mgr_t14_cloud_acquisition import acquired_sheet, assert_native_qi_payment

A='actor:factory.nativewalker'
B='actor:factory.companion'
KEY='tianxia.subpath.qi.cloud_walker'


@pytest.fixture(scope='module',autouse=True)
def tested_source_identity(tmp_path_factory):
    from pathlib import Path
    import hashlib
    files=['combat/armour.py','combat/asset_anchor_runtime.py','combat/dynamic_size.py','combat/gate2_engine.py','tests/test_mgr_t14_cloud_route_queries.py','tests/test_mgr_t14_cloud_acquisition.py','combat/ext/cloud_walker.py','combat/ext/cloud_walker_environment.py','combat/journey.py',
        'combat/technique_costs.py','tests/test_mgr_t14_cloud_passenger.py','combat/flight.py','combat/movement_costs.py','combat/journey_replay.py','combat/gate2_grid.py','combat/granted_movement.py','combat/gate5_service.py','tests/test_mgr_t14_cloud_resume.py',
        'combat/journey_falling.py']
    hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() if (ROOT/p).is_file() else None for p in files}
    identity=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    evidence=tmp_path_factory.getbasetemp()/'cloud-source-evidence'
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/('tested-source-'+identity[:16]+'.json')).write_text(json.dumps(hashes,indent=2)+'\n')


def game(tmp_path, acquired_sheet, *, surfaces=(), barriers=(), fields=(), width=36, journey=False, companion_size="Medium"):
    companion=sheet([],cl=1,name='Companion')
    companion['identity']['size']=companion_size
    for pid,doc in [('nativewalker',acquired_sheet),('companion',companion)]:
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    # Explicit owner measurements fill only inventory weights the real compiler
    # leaves unknown; they create neither equipment nor source ownership.
    measurements={}
    for aid,doc in [(A,acquired_sheet),(B,companion)]:
        carrying=compile_character(doc,actor_id=aid).get('carrying',{})
        measurements[aid]={aid+'|'+item['key']:1 for item in carrying.get('items',())
            if item['name'] in carrying.get('unweighed',())}
    c=CombatService(ROOT,tmp_path)
    c.tabletop_maps.save({'display_name':'Cloud review yard','width_squares':12,'height_squares':14,
        'walls':[],'starts':{'team1':[[3,6],[4,6]],'team2':[[9,9]]},'source_data':{KEY:{
            'source':KEY,'authority':'map_owner','declared_by':'Scene GM','expires':'scene',
            'bodies':{A:{'body_weight_lb':160,'width_inches':18,'item_weights_lb':measurements[A]},
                B:{'body_weight_lb':160,'width_inches':width,'item_weights_lb':measurements[B]}},
            'surfaces':list(surfaces),'barriers':list(barriers),'fields':list(fields)}}})
    arena='battlefield:map.cloud-review-yard'
    if journey:
        state=c.create_journey(project_ids=['nativewalker','companion'],arena_id=arena,
            positions={A:{'x':3,'y':6},B:{'x':4,'y':6}},base_paces={A:18000,B:18000},
            control_modes={A:'MANUAL',B:'MANUAL'})
        return c,state['journey_id']
    result=c.create_factory_match(project_ids=['nativewalker','companion'],opponent_actor_ids=[AN],arena_id=arena,
        match_seed='CLOUD-REVIEW-BOUNDARIES',control_modes={A:'MANUAL',B:'MANUAL',AN:'MANUAL'})
    t=TabletopService(c,tmp_path);turn(t,result['match_id'],A)
    return c,t,result['match_id']


def action(c,mid,name):
    return next(x for x in c._load_session(mid).engine.legal_candidates()
        if x.display_name.casefold().startswith(name.casefold()))


def verify(tmp_path,mid):
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']==session.mechanical.replay()['status']=='PASS'
    return session.engine


def barrier(opening, *, axis='y',plane=5,low=(0,0),high=(11,100)):
    return {'axis':axis,'plane':plane,'low':list(low),'high':list(high),
        'opening_inches':opening,'total_cover':False,'sealed_formation':False}


@pytest.mark.parametrize('opening,allowed',[(0,False),('1/2',False),(1,True)])
def test_acquired_wind_journey_boundary_menu_commit_and_cold_load(tmp_path,acquired_sheet,opening,allowed):
    c,jid=game(tmp_path,acquired_sheet,journey=True,barriers=[barrier(opening,axis='x',plane=3)])
    def act(kind,payload=None):
        cold=CombatService(ROOT,tmp_path);state=cold.journey_state(jid)
        result=cold.journey_act(jid,state['revision'],A,kind,payload or {})
        if hasattr(cold,'journey_verify'):
            assert CombatService(ROOT,tmp_path).journey_verify(jid)['status']=='PASS'
        return result
    act('cloud_wind_begin');act('wait',{'seconds':600});act('cloud_wind_finish')
    before=CombatService(ROOT,tmp_path).journey_state(jid)
    menu=CombatService(ROOT,tmp_path).journey_menu(jid,A)
    assert any(x['id']=='move:2,6,0' for x in menu['options']) is allowed
    if allowed:
        after=act('move',{'path':[{'x':2,'y':6}]})
        assert Position(**after['actors'][A]['position'])==Position(x=2,y=6,z=0)
    else:
        with pytest.raises(ValueError,match='boundary|opening'):
            act('move',{'path':[{'x':2,'y':6}]})
        assert CombatService(ROOT,tmp_path).journey_state(jid)==before






@pytest.mark.parametrize('kind',['water','liquid','snow','mud','loose_sand','unstable_ground'])
def test_acquired_ground_surface_cross_end_and_cold_reload(tmp_path,acquired_sheet,kind):
    surface={'id':'ground-footing','kind':kind,'cells':[[2,6]],'z':0,'capacity_lb':1,
        'fragile':False,'trigger':'weight'}
    c,t,mid=game(tmp_path,acquired_sheet,surfaces=[surface])
    e=c._load_session(mid).engine
    move=next(x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.destination==Position(x=2,y=6))
    settle(t,mid,move.candidate_id)
    e=verify(tmp_path,mid)
    assert not any(x.data.get('surface_id')=='ground-footing' for x in e.state.actors[A].conditions.values())

    settle(t,mid,t.state(mid)['menu']['end_turn'])
    e=verify(tmp_path,mid)
    held=next(x for x in e.state.actors[A].conditions.values() if x.data.get('surface_id')=='ground-footing')
    assert held.data['kind']==kind
    assert held.data['movement_cost']==2
    turn(t,mid,A)
    move=next(x for x in c._load_session(mid).engine.legal_candidates()
        if x.kind.value=='MOVE' and x.destination==Position(x=1,y=6))
    settle(t,mid,move.candidate_id)
    e=verify(tmp_path,mid)
    assert not any(x.data.get('surface_id')=='ground-footing' for x in e.state.actors[A].conditions.values())


@pytest.mark.parametrize('capacity,flight',[(1000,False),(1,True)])
def test_ground_footing_preserves_actual_support_and_independent_flight(tmp_path,acquired_sheet,capacity,flight):
    surface={'id':'ground-footing','kind':'water','cells':[[2,6]],'z':0,'capacity_lb':capacity,
        'fragile':False,'trigger':'none'}
    c,t,mid=game(tmp_path,acquired_sheet,surfaces=[surface])
    if flight:settle(t,mid,action(c,mid,'Cloud Step').candidate_id)
    e=c._load_session(mid).engine
    move=next(x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.destination==Position(x=2,y=6))
    settle(t,mid,move.candidate_id)
    settle(t,mid,t.state(mid)['menu']['end_turn'])
    e=verify(tmp_path,mid)
    assert not any(x.data.get('surface_id')=='ground-footing' for x in e.state.actors[A].conditions.values())


def test_ground_surface_does_not_give_unowned_companion_feather_crossing(tmp_path,acquired_sheet):
    surface={'id':'ordinary-water','kind':'water','cells':[[4,5]],'z':0,'capacity_lb':1,
        'fragile':False,'trigger':'none'}
    c,t,mid=game(tmp_path,acquired_sheet,surfaces=[surface])
    turn(t,mid,B)
    e=c._load_session(mid).engine
    move=next(x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.destination==Position(x=4,y=5))
    settle(t,mid,move.candidate_id)
    e=verify(tmp_path,mid)
    assert any(x.data.get('surface_id')=='ordinary-water' for x in e.state.actors[B].conditions.values())
    assert not any(row.get('block')=='cloud_walker' for row in e.typed_passive_rows.get(B,()))


@pytest.mark.parametrize('source_cl,absolute,dc,allowed',[(15,False,1,True),(21,False,1,False),
    (1,True,1,False),(18,False,1,True),(18,False,100,False)])
def test_acquired_wind_journey_consumes_real_source_authority(tmp_path,acquired_sheet,source_cl,absolute,dc,allowed):
    field={'id':'route-pressure','source_id':'scene:route-pressure',
        'source_rule':'This spatial source contests cloud passage in its declared volume.',
        'source_cl':source_cl,'save_dc':dc,'kind':'spatial','absolute':absolute,
        'cells':[[2,6]],'min_z':0,'max_z':100}
    c,jid=game(tmp_path,acquired_sheet,journey=True,fields=[field])
    def act(kind,payload=None):
        cold=CombatService(ROOT,tmp_path);state=cold.journey_state(jid)
        result=cold.journey_act(jid,state['revision'],A,kind,payload or {})
        if hasattr(cold,'journey_verify'):
            assert CombatService(ROOT,tmp_path).journey_verify(jid)['status']=='PASS'
        return result
    act('cloud_wind_begin');act('wait',{'seconds':600});act('cloud_wind_finish')
    if source_cl==18 and not absolute:
        options=CombatService(ROOT,tmp_path).journey_menu(jid,A)['options']
        option=next(x for x in options if x['kind']=='cloud_pressure_contest'
            and x['payload']['destination'].get('x')==2 and x['payload']['destination'].get('y')==6
            and not x['payload']['destination'].get('z',0))
        after=act(option['kind'],option['payload'])
        check=next(x for x in after['events'] if x['kind']=='CULTIVATION_CHECK')
        assert check['source']=='scene:route-pressure'
        assert check['success']==int(allowed)
        before=CombatService(ROOT,tmp_path).journey_state(jid)
        with pytest.raises(ValueError,match='already resolved'):
            act(option['kind'],option['payload'])
        assert CombatService(ROOT,tmp_path).journey_state(jid)==before

    before=CombatService(ROOT,tmp_path).journey_state(jid)
    if allowed:
        act('move',{'path':[{'x':2,'y':6}]})
        assert CombatService(ROOT,tmp_path).journey_state(jid)['actors'][A]['position']['x']==2
    else:
        with pytest.raises(ValueError,match='boundary|opening'):
            act('move',{'path':[{'x':2,'y':6}]})
        assert CombatService(ROOT,tmp_path).journey_state(jid)==before


def test_wind_recipient_retains_actual_source_numbers_without_caster_present(tmp_path,acquired_sheet):
    field={'id':'route-pressure','source_id':'scene:route-pressure',
        'source_rule':'An equal-authority spatial effect contests this opening.',
        'source_cl':18,'save_dc':1,'kind':'spatial','absolute':False,
        'cells':[[2,6]],'min_z':0,'max_z':100}
    c,jid=game(tmp_path,acquired_sheet,journey=True,fields=[field])
    def act(kind,payload=None,who=A):
        cold=CombatService(ROOT,tmp_path);state=cold.journey_state(jid)
        result=cold.journey_act(jid,state['revision'],who,kind,payload or {})
        if hasattr(cold,'journey_verify'):
            assert CombatService(ROOT,tmp_path).journey_verify(jid)['status']=='PASS'
        return result
    act('cloud_wind_begin');act('wait',{'seconds':600})
    act('cloud_wind_invite',{'target_id':B});act('cloud_wind_reply',{'caster_id':A,'accept':True},B)
    state=act('cloud_wind_finish')
    numbers=next(r['numbers'] for r in compile_character(acquired_sheet,actor_id=A)['typed_passives']
        if r.get('block')=='cloud_walker')
    receipt=state['actors'][B]['travel_effects'][CLOUD+'wind_walk']
    assert (receipt['source_pb'],receipt['source_key_mod'])==(numbers['pb'],numbers['key_mod'])
    act('finish')
    c=CombatService(ROOT,tmp_path)
    state=c.create_journey(project_ids=['companion'],arena_id='battlefield:map.cloud-review-yard',
        positions={B:{'x':3,'y':6}},base_paces={B:18000})
    jid=state['journey_id']
    assert A not in state['actors']
    assert not any(r.get('block')=='cloud_walker' for r in state['actors'][B]['bundle']['typed_passives'])
    option=next(x for x in c.journey_menu(jid,B)['options'] if x['kind']=='cloud_pressure_contest'
        and x['payload']['destination']=={'x':2,'y':6})
    state=act(option['kind'],option['payload'],B)
    check=next(x for x in state['events'] if x['kind']=='CULTIVATION_CHECK')
    assert check['roll']['modifier']==numbers['pb']+numbers['key_mod']
    act('move',{'path':[{'x':2,'y':6}]},B)
    assert CombatService(ROOT,tmp_path).journey_state(jid)['actors'][B]['position']['x']==2


@pytest.mark.parametrize('value',[-1,'five',1.5])
def test_segment_cost_contract_rejects_malformed_provider_in_native_menu(tmp_path,acquired_sheet,monkeypatch,value):
    from tests.test_lock_choices import install
    c,t,mid=game(tmp_path,acquired_sheet)
    install(monkeypatch,'movement_segment_surcharge',lambda *args:value)
    with pytest.raises(ValueError,match='nonnegative integer'):
        c._load_session(mid).engine.legal_candidates()


def test_journey_edge_contract_rejects_malformed_provider_without_commit(tmp_path,acquired_sheet,monkeypatch):
    from tests.test_lock_choices import install
    c,jid=game(tmp_path,acquired_sheet,journey=True)
    before=c.journey_state(jid)
    install(monkeypatch,'journey_edge_allowed',lambda *args:'yes')
    with pytest.raises(ValueError,match='boolean'):
        c.journey_act(jid,before['revision'],A,'move',{'path':[{'x':2,'y':6}]})
    assert c.journey_state(jid)==before





def test_native_journey_replay_verifies_actual_commands_and_rejects_changed_balance(tmp_path,acquired_sheet):
    c,jid=game(tmp_path,acquired_sheet,journey=True)
    state=c.journey_state(jid)
    c.journey_act(jid,state['revision'],A,'wait',{'seconds':1})
    result=CombatService(ROOT,tmp_path).journey_verify(jid)
    assert result['status']=='PASS' and result['commands']==1
    # An intentionally forged balance is a rejection control, never acquisition
    # or a source receipt. Restore the owned disposable file after the check.
    path=c.journeys.path(jid);original=path.read_bytes()
    try:
        saved=json.loads(original)
        saved['sessions'][jid]['actors'][A]['resources']['resource:core.qi']+=1
        path.write_text(json.dumps(saved))
        with pytest.raises(ValueError,match='replay|boundary'):
            CombatService(ROOT,tmp_path).journey_verify(jid)
    finally:path.write_bytes(original)
    assert CombatService(ROOT,tmp_path).journey_verify(jid)['status']=='PASS'




def test_acquired_wind_journey_crosses_creatures_as_difficult_without_occupied_stop(tmp_path,acquired_sheet):
    c,jid=game(tmp_path,acquired_sheet,journey=True)
    def act(actor,kind,payload=None):
        cold=CombatService(ROOT,tmp_path);s=cold.journey_state(jid)
        return cold.journey_act(jid,s['revision'],actor,kind,payload or {})
    act(A,'cloud_wind_begin');act(A,'wait',{'seconds':600});act(A,'cloud_wind_finish')
    before=c.journey_state(jid)
    with pytest.raises(ValueError,match='occup'):act(A,'move',{'path':[{'x':4,'y':6}]})
    assert c.journey_state(jid)==before
    with pytest.raises(ValueError,match='occup'):act(B,'move',{'path':[{'x':3,'y':6},{'x':2,'y':6}]})
    options=CombatService(ROOT,tmp_path).journey_menu(jid,A)['options']
    crossing=next(o for o in options if o.get('payload',{}).get('path')==[{'x':4,'y':6},{'x':5,'y':6}])
    after=act(A,crossing['kind'],crossing['payload'])
    assert Position(**after['actors'][A]['position'])==Position(x=5,y=6)
    assert after['seconds']-before['seconds']==3
    assert CombatService(ROOT,tmp_path).journey_verify(jid)['status']=='PASS'






@pytest.mark.parametrize('kind,trigger',[('hanging_cloth','weight'),('thin_branch','weight'),
    ('fragile_roof','weight'),('hanging_cloth','qi_pressure')])
def test_acquired_fragile_support_uses_actual_end_weight_and_qi_exception(tmp_path,acquired_sheet,kind,trigger):
    surface={'id':'fragile-support','kind':kind,'cells':[[2,6]],'z':1,'capacity_lb':1,
        'fragile':True,'trigger':trigger}
    c,t,mid=game(tmp_path,acquired_sheet,surfaces=[surface])
    settle(t,mid,action(c,mid,'Heavenly Leap').candidate_id,choices={
        'choice:needle.cloud_leap_destination':['cell:2,6,1']})
    e=verify(tmp_path,mid)
    def failures(engine):
        return [ev for ev in engine.events if ev.event_type=='PASSIVE_TRIGGERED'
            and ev.payload.get('surface_id')=='fragile-support' and ev.payload.get('cloud_surface_failed')==1]
    if trigger=='weight':
        assert not failures(e) and e.state.actors[A].position.z==1
        settle(t,mid,t.state(mid)['menu']['end_turn'])
        e=verify(tmp_path,mid)
    assert len(failures(e))==1
    assert failures(e)[0].payload['trigger']==trigger
    assert e.state.actors[A].position.z==0
