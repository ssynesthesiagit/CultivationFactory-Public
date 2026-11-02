"""Native acquisition -> CombatService journey command -> exact cold state."""
import pytest
from combat.gate5_service import CombatService
from combat.ext.riverway import PASSAGE,FERRY,MOON,KNOWS,FIELD,QI
from combat.tabletop import TabletopMapStore,to_battlefield
from tests.h1_support import ROOT,sheet
from tests.test_mgr_t14_riverway_native import acquired

A='actor:factory.guide';B='actor:factory.passenger'


def game(tmp_path,monkeypatch,acquired,*,cl=18,regions=None,extra=False):
    store=TabletopMapStore(tmp_path/'maps')
    store.save({'map_id':'riverway-journey','display_name':'River journey','width_squares':20,'height_squares':14,
                'route_regions':regions or []})
    arena=to_battlefield(store.get('riverway-journey'))
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:acquired(cl) if pid=='guide' else sheet([],cl=cl))
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self:{'river':arena})
    service=CombatService(ROOT,tmp_path)
    positions={A:{'x':3,'y':6},B:{'x':4,'y':6}}
    if extra:positions['actor:factory.foe']={'x':15,'y':10}
    state=service.create_journey(project_ids=['guide','passenger',*(['foe'] if extra else [])],arena_id='river',
        positions=positions,base_paces={aid:18000 for aid in positions})
    jid=state['journey_id']
    def cold():return CombatService(ROOT,tmp_path)
    def act(kind,payload,aid=A):
        before=cold().journey_state(jid)
        after=cold().journey_act(jid,before['revision'],aid,kind,payload)
        assert cold().journey_state(jid)==after
        return after
    return cold,jid,act


def test_passage_travel_clock_and_expiry(tmp_path,monkeypatch,acquired):
    cold,jid,act=game(tmp_path,monkeypatch,acquired,cl=14)
    cells=[{'x':x,'y':6} for x in range(3,15)]
    state=act('riverway_create',{'source':PASSAGE,'cells':cells,'chosen':[A,B],'starters':[B]})
    assert state['actors'][A]['resources'][QI]==99
    assert cold().journey_menu(jid,A)['properties']['speed_bonus_ft']==5
    act('move',{'path':[{'x':5,'y':6}]},B)
    state=act('wait',{'seconds':60})
    assert PASSAGE not in state['actors'][A]['travel_effects']
    assert 'speed_bonus_ft' not in cold().journey_menu(jid,A)['properties']


def test_creation_menu_collects_real_route_and_recipients_before_payment(tmp_path,monkeypatch,acquired):
    cold,jid,act=game(tmp_path,monkeypatch,acquired,cl=3)
    create=next(o for o in cold().journey_menu(jid,A)['options'] if o['kind']=='riverway_create')
    state=act(create['kind'],create['payload'])
    assert state['actors'][A]['resources'][QI]==100 and not state['actors'][A]['travel_effects']
    for ident in ('cell:3,6,0','ally:'+B,'finish'):
        selected=next(o for o in cold().journey_menu(jid,A)['options'] if o['id']==ident)
        state=act(selected['kind'],selected['payload'])
    assert state['actors'][A]['resources'][QI]==99
    effect=state['actors'][A]['travel_effects'][PASSAGE]
    assert effect['cells']==[{'x':3,'y':6}] and effect['chosen']==[B]
    assert 'riverway_declaration' not in state['actors'][A]


def test_passenger_own_entry_transit_and_expiry(tmp_path,monkeypatch,acquired):
    cold,jid,act=game(tmp_path,monkeypatch,acquired,cl=10)
    gates=[{'x':5,'y':6},{'x':10,'y':6}]
    act('riverway_create',{'source':MOON,'cells':gates})
    state=act('move',{'path':[gates[0]]},B)
    arrivals=[o['payload']['arrival'] for o in cold().journey_menu(jid,B)['options'] if o['kind']=='riverway_transit']
    assert arrivals and all(p['z']==0 for p in arrivals)
    before=state['seconds']
    state=act('riverway_transit',{'owner_id':A,'gate':0,'arrival':{'x':11,'y':6}},B)
    assert state['seconds']==before
    assert state['actors'][B]['position']['x']==11
    assert state['events'][-1]['willing']==1
    assert state['actors'][A]['resources'][QI]==95
    state=act('wait',{'seconds':60})
    assert MOON not in state['actors'][A]['travel_effects']


@pytest.mark.parametrize('kind',['spatial_lock','sealed_formation','planar_boundary','teleport_barrier'])
def test_mapped_route_barriers_reject_without_committing(tmp_path,monkeypatch,acquired,kind):
    cold,jid,act=game(tmp_path,monkeypatch,acquired,cl=10,
        regions=[{'id':'ward','kind':kind,'cells':[{'x':7,'y':6}]}])
    act('riverway_create',{'source':MOON,'cells':[{'x':5,'y':6},{'x':10,'y':6}]})
    act('move',{'path':[{'x':5,'y':6}]},B)
    before=cold().journey_state(jid)
    with pytest.raises(Exception,match='blocks this Ferry'):
        act('riverway_transit',{'owner_id':A,'gate':0,'arrival':{'x':11,'y':6}},B)
    assert cold().journey_state(jid)==before


def test_river_knowledge_outside_combat_and_unknown_facts(tmp_path,monkeypatch,acquired):
    cold,jid,act=game(tmp_path,monkeypatch,acquired,cl=14,
        regions=[{'id':'connected-water','kind':'water','flow':'east','stagnant':0,'poisoned':1,
                  'cells':[{'x':x,'y':6} for x in range(3,19)]}])
    p=cold().journey_menu(jid,A)['properties']
    assert p['swim_speed_ft']==30
    assert p['air_breathing']==p['water_breathing']==1
    assert 'water routes' in p['navigation_advantage']
    assert any(f.get('poisoned')==1 for f in p['connected_water'])
    assert all('actively_cultivated' not in f for f in p['connected_water'])
    assert not cold().journey_menu(jid,B)['properties']
    state=cold().journey_state(jid)
    cold().journey_world_fact(jid,state['revision'],{'source':'world:journey_check','subject':A,'kind':'ability_check',
        'scope':'canal-navigation','value':{'ability':'WIS','skill':'Survival','dc':15,'reason':'Navigate the mapped connected canal',
            'context':{'purpose':'navigation','region_id':'connected-water'}},'expires_at':60,'readers':[]})
    check=next(o for o in cold().journey_menu(jid,A)['options'] if o['kind']=='ability_check')
    state=act(check['kind'],check['payload'])
    roll=state['events'][-1]['roll']
    assert roll['mode']=='ADVANTAGE' and len(roll['dice'])==2
    from combat.gate2_rolls import DeterministicRollAuthority
    replay=DeterministicRollAuthority(jid).d20(modifier=roll['modifier'],actor_id=A,reason=roll['reason'],mode='ADVANTAGE')
    assert replay.model_dump(mode='json')==roll


def test_field_scene_cap_concentration_and_no_reversal(tmp_path,monkeypatch,acquired):
    cold,jid,act=game(tmp_path,monkeypatch,acquired)
    act('riverway_create',{'source':FIELD,'cells':[{'x':3,'y':6}],'chosen':[A,B]})
    state=act('riverway_create',{'source':MOON,'cells':[{'x':5,'y':6},{'x':10,'y':6}]})
    assert state['actors'][A]['travel_effects'][MOON]['waived']==1
    assert FIELD in state['actors'][A]['travel_effects']
    act('move',{'path':[{'x':5,'y':6}]},B)
    state=act('riverway_transit',{'owner_id':A,'gate':0,'arrival':{'x':11,'y':6}},B)
    with pytest.raises(Exception,match='once per scene'):
        act('riverway_create',{'source':FIELD,'cells':[{'x':3,'y':6}],'chosen':[A]})
    state=act('wait',{'seconds':60})
    assert state['actors'][B]['position']['x']==11
    assert FIELD not in state['actors'][A]['travel_effects']


@pytest.mark.parametrize('route',['river','canal','flood','delta','swamp','coastline','water_route'])
def test_source_recorded_navigation_contexts_and_nonowner_guard(tmp_path,monkeypatch,acquired,route):
    cold,jid,act=game(tmp_path,monkeypatch,acquired,cl=14)
    for subject,mode in ((A,'ADVANTAGE'),(B,'NORMAL')):
        before=cold().journey_state(jid)
        cold().journey_world_fact(jid,before['revision'],{'source':'world:journey_check','subject':subject,'kind':'ability_check',
            'scope':'navigation:'+route+':'+subject,'value':{'ability':'WIS','skill':'Survival','dc':12,
                'reason':'Navigate the source-recorded '+route,'context':{'purpose':'navigation','route_kind':route}},
            'expires_at':60,'readers':[]})
        option=next(o for o in cold().journey_menu(jid,subject)['options'] if o['kind']=='ability_check')
        state=act(option['kind'],option['payload'],subject)
        assert state['events'][-1]['roll']['mode']==mode


def test_real_damage_checks_field_concentration_and_restores_gate_requirement(tmp_path,monkeypatch,acquired):
    cold,jid,act=game(tmp_path,monkeypatch,acquired)
    act('riverway_create',{'source':FIELD,'cells':[{'x':3,'y':6}],'chosen':[A,B]})
    act('riverway_create',{'source':MOON,'cells':[{'x':5,'y':6},{'x':10,'y':6}]})
    state=world(cold,jid,'settled_damage',{'source_reference':'scene:falling-boulder','amount':59,'damage_type':'BLUDGEONING'},subject=A)
    saves=[e for e in state['events'] if e['kind']=='SAVE_ROLLED' and e['source']=='system:combat.concentration']
    assert len(saves)==1 and saves[0]['dc']==29 and saves[0]['success']==0
    remaining=state['actors'][A]['travel_effects']
    assert FIELD not in remaining
    assert remaining[MOON]['waived']==0 and remaining[MOON]['concentration']==1
    assert state['actors'][A]['encounter_snapshot']['current_hp']==1


def world(cold,jid,kind,value,subject=B,scope='source-event-1'):
    before=cold().journey_state(jid)
    after=cold().journey_world_fact(jid,before['revision'],{'source':'world:journey_exposure','subject':subject,
        'kind':kind,'scope':scope,'value':value,'expires_at':before['seconds']+60,'readers':[A]})
    assert cold().journey_state(jid)==after
    return after


def test_outside_combat_rescue_uses_real_owner_recorded_damage(tmp_path,monkeypatch,acquired):
    cold,jid,act=game(tmp_path,monkeypatch,acquired,cl=6)
    act('riverway_create',{'source':PASSAGE,'cells':[{'x':x,'y':6} for x in range(3,9)],'chosen':[A,B]})
    before=cold().journey_state(jid)
    exposure={'source_reference':'scene:falling-branch','amount':7,'damage_type':'BLUDGEONING'}
    with pytest.raises(Exception):act('record_damage',exposure,B)
    assert cold().journey_state(jid)==before
    state=world(cold,jid,'settled_damage',exposure)
    assert state['actors'][B]['encounter_snapshot']['current_hp']==53
    options=cold().journey_menu(jid,A)['options']
    rescue=next(o for o in options if o['kind']=='riverway_rescue' and o['payload']['destination']=={'x':6,'y':6})
    state=act(rescue['kind'],rescue['payload'])
    assert state['actors'][B]['position']=={'x':6,'y':6}
    assert state['actors'][B]['encounter_snapshot']['temporary_hp']==3
    assert state['actors'][A]['resources'][QI]==97
    damage=next(i for i,e in enumerate(state['events']) if e['kind']=='DAMAGE_COMMITTED')
    reaction=next(i for i,e in enumerate(state['events']) if e['kind']=='REACTION_RESOLVED')
    move=next(i for i,e in enumerate(state['events']) if e['kind']=='MOVEMENT_COMMITTED')
    protection=next(i for i,e in enumerate(state['events']) if e['kind']=='TEMP_HP_GRANTED')
    assert damage<reaction<move<protection
    with pytest.raises(Exception,match='already resolved'):world(cold,jid,'settled_damage',exposure)


@pytest.mark.parametrize('mode',['Buoy','Carry','Sweep','Wash Away'])
def test_every_field_command_native_journey_and_cold_replay(tmp_path,monkeypatch,acquired,mode):
    cold,jid,act=game(tmp_path,monkeypatch,acquired)
    act('riverway_create',{'source':FIELD,'cells':[{'x':3,'y':6}],'chosen':[A,B]})
    payload={'mode':mode,'target':B}
    if mode=='Carry':
        act('riverway_carry_propose',{'mode':'Carry','target':B,'destination':{'x':6,'y':6}})
        consent=next(o for o in cold().journey_menu(jid,B)['options'] if o['kind']=='declare_fact')
        state=act(consent['kind'],consent['payload'],B)
    elif mode=='Sweep':
        world(cold,jid,'relations',{'kind':'ACTOR_RELATION','subject':A,'other':B,'relation':'ENEMY'})
        payload['direction']='push'
    elif mode=='Wash Away':
        state=world(cold,jid,'restraint',{'condition':'grappled','source_reference':'scene:recorded-snare',
            'source_actor_id':A,'source_dc':1,'save_ability':''})
        payload.update(condition_instance=next(iter(state['actors'][B]['encounter_snapshot']['conditions'])),ability='DEX')
    if mode!='Carry':state=act('riverway_command',payload)
    assert state['actors'][A]['resources'][QI]==92
    assert any(e['kind']=='COMMAND_THE_CURRENT' and e['mode']==mode for e in state['events'])
    if mode=='Buoy':assert state['actors'][B]['encounter_snapshot']['temporary_hp']==12
    elif mode=='Carry':assert state['actors'][B]['position']['x']==6
    elif mode=='Sweep':
        save=next(e for e in reversed(state['events']) if e['kind']=='SAVE_ROLLED')
        assert state['actors'][B]['position']['x']==(5 if save['success'] else 7)
    else:
        assert not state['actors'][B]['encounter_snapshot']['conditions']
        save=next(e for e in reversed(state['events']) if e['kind']=='SAVE_ROLLED')
        assert save['dc']==1 and save['roll']['mode']=='ADVANTAGE'
    with pytest.raises(Exception,match='already used'):act('riverway_command',{'mode':'Buoy','target':A})


def test_native_table_wash_uses_actual_imported_restraint_and_source_dc(tmp_path,monkeypatch,acquired):
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import candidate,reload,settle,turn
    cold,jid,act=game(tmp_path,monkeypatch,acquired,extra=True)
    state=world(cold,jid,'restraint',{'condition':'grappled','source_reference':'scene:snare',
        'source_actor_id':'actor:factory.foe','source_dc':1,'save_ability':''})
    iid=next(iter(state['actors'][B]['encounter_snapshot']['conditions']))
    result=cold().journey_start_combat(jid,state['revision'],{A:'team:factory',B:'team:factory','actor:factory.foe':'team:opponents'})
    mid=result['match_id'];combat=cold();table=TabletopService(combat,tmp_path)
    turn(table,mid,A)
    settle(table,mid,candidate(combat,mid,'Imperial River Field',at=(3,6)).candidate_id,
        choices={'choice:riverway.Imperial River Field':[A,B],
            'choice:riverway.command':['Wash Away:'+B],'choice:riverway.wash':[iid],
            'choice:riverway.wash_ability':['DEX']})
    engine=reload(tmp_path,mid)
    assert iid not in engine.state.actors[B].conditions
    save=next(e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==B)
    assert save.payload['dc']==1 and save.payload['mode']=='ADVANTAGE'


def test_field_movement_teleport_and_explicit_scene_boundary(tmp_path,monkeypatch,acquired):
    cold,jid,act=game(tmp_path,monkeypatch,acquired)
    act('riverway_create',{'source':FIELD,'cells':[{'x':3,'y':6}],'chosen':[A,B]})
    act('wait',{'seconds':6})
    menu=cold().journey_menu(jid,B)
    free=next(o for o in menu['options'] if o['kind']=='riverway_start_step' and o['payload']['destination']=={'x':5,'y':6})
    act(free['kind'],free['payload'],B)
    act('riverway_distance_propose',{'target':B,'destination':{'x':9,'y':6}})
    consent=next(o for o in cold().journey_menu(jid,B)['options'] if o['kind']=='declare_fact' and o['payload']['kind']=='riverway_distance_consent' and o['payload']['value']==1)
    state=act(consent['kind'],consent['payload'],B)
    assert state['actors'][B]['position']=={'x':9,'y':6}
    assert state['seconds']==6
    with pytest.raises(Exception):act('riverway_distance_propose',{'target':B,'destination':{'x':10,'y':6}})
    state=cold().journey_state(jid)
    with pytest.raises(Exception):act('riverway_create',{'source':FIELD,'cells':[{'x':3,'y':6}]})
    state=cold().journey_end_scene(jid,state['revision'],'The river crossing encounter is over; begin the next travel scene.')
    assert state['events'][-1]['kind']=='SCENE_ENDED'
    act('riverway_create',{'source':FIELD,'cells':[{'x':3,'y':6}],'chosen':[A,B]})
