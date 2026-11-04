"""Native acquisition -> CombatService journey command -> exact cold state."""
import pytest
from combat.gate5_service import CombatService
from combat.ext.riverway import PASSAGE,FERRY,MOON,KNOWS,FIELD,QI
from combat.tabletop import TabletopMapStore,to_battlefield
from tests.h1_support import ROOT,sheet
from tests.test_mgr_t14_riverway_native import acquired

A='actor:factory.guide';B='actor:factory.passenger'


def game(tmp_path,monkeypatch,acquired,*,cl=18,regions=None,extra=False,passenger_flying=False,travel_regions=None,foe_position=None,
         passenger_talents=(),control_modes=None,passenger_project='passenger'):
    passenger_id='actor:factory.'+passenger_project
    store=TabletopMapStore(tmp_path/'maps')
    store.save({'map_id':'riverway-journey','display_name':'River journey','width_squares':20,'height_squares':14,
                'route_regions':regions or [],'travel_regions':travel_regions or []})
    arena=to_battlefield(store.get('riverway-journey'))
    def owner_sheet(self,pid):
        if pid=='guide':
            return acquired(cl)
        doc=sheet(list(passenger_talents) if pid==passenger_project else [],cl=cl,
                  name='Passenger' if pid==passenger_project else 'Other creature')
        if pid==passenger_project and passenger_flying:
            doc['ability_scores_and_statistics']['speed']['flying_ft']=30
        return doc
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',owner_sheet)
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self:{'river':arena})
    service=CombatService(ROOT,tmp_path)
    positions={A:{'x':3,'y':6},passenger_id:{'x':4,'y':6}}
    if extra:positions['actor:factory.foe']=foe_position or {'x':15,'y':10}
    state=service.create_journey(project_ids=['guide',passenger_project,*(['foe'] if extra else [])],arena_id='river',
        positions=positions,base_paces={aid:18000 for aid in positions},control_modes=control_modes)
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
    for destination in (6,7):
        act('wait',{'seconds':6})
        option=next(o for o in cold().journey_menu(jid,B)['options']
                    if o['kind']=='riverway_start_step' and o['payload']['source']==PASSAGE
                    and o['payload']['destination']=={'x':destination,'y':6})
        state=act(option['kind'],option['payload'],B)
        assert state['actors'][B]['position']=={'x':destination,'y':6}
        assert not any(o['kind']=='riverway_start_step' and o['payload']['source']==PASSAGE
                       for o in cold().journey_menu(jid,B)['options'])
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
    before=state['seconds']
    state=act('riverway_transit',{'owner_id':A,'gate':0,'arrival':{'x':11,'y':6}},B)
    assert state['seconds']==before
    assert state['actors'][B]['position']['x']==11
    assert state['events'][-1]['willing']==1
    assert state['actors'][A]['resources'][QI]==95
    state=act('wait',{'seconds':60})
    assert MOON not in state['actors'][A]['travel_effects']


@pytest.mark.parametrize('wall',[False,True])
def test_ferry_offers_airborne_arrival_and_settles_native_fall(tmp_path,monkeypatch,acquired,wall):
    face=[{'kind':'vertical_surface','cells':[[11,6]],'max_z':4}] if wall else []
    cold,jid,act=game(tmp_path,monkeypatch,acquired,cl=10,travel_regions=face)
    gates=[{'x':5,'y':6},{'x':10,'y':6,'z':3}]
    act('riverway_create',{'source':MOON,'cells':gates})
    act('move',{'path':[gates[0]]},B)
    arrival={'x':11,'y':6,'z':4}
    option=next(o for o in cold().journey_menu(jid,B)['options']
                if o['kind']=='riverway_transit' and o['payload']['arrival']==arrival)
    assert 'fall' in option['label'].lower()
    state=act(option['kind'],option['payload'],B)
    assert state['actors'][B]['position']=={'x':11,'y':6}
    saved=state['actors'][B]['encounter_snapshot']
    assert saved['current_hp'] < saved['maximum_hp']
    assert any('condition:typed.prone' in c for c in saved['conditions'].values())
    teleport=next(i for i,e in enumerate(state['events']) if e['kind']=='TRAVEL_TELEPORT')
    fall=next(i for i,e in enumerate(state['events'])
              if e['kind']=='MOVEMENT_COMMITTED' and e.get('fall_distance_ft')==20)
    assert teleport < fall
    assert any(e['kind']=='DAMAGE_COMMITTED' and e.get('reduced_to',0)>0 for e in state['events'])
    state=act('wait',{'seconds':6},B)
    assert not any('condition:typed.prone' in c
                   for c in state['actors'][B]['encounter_snapshot']['conditions'].values())
    assert cold().journey_replay(jid)['status']=='PASS'


@pytest.mark.parametrize('prone',[False,True])
def test_ferry_arrival_uses_native_fall_eligibility_for_flyers(tmp_path,monkeypatch,acquired,prone):
    cold,jid,act=game(tmp_path,monkeypatch,acquired,cl=10,passenger_flying=True)
    gates=[{'x':5,'y':6},{'x':10,'y':6,'z':3}]
    act('riverway_create',{'source':MOON,'cells':gates})
    if prone:
        world(cold,jid,'restraint',{'condition':'prone','source_reference':'scene:wind',
            'source_actor_id':A,'source_dc':10,'save_ability':''})
    act('move',{'path':[gates[0]]},B)
    state=act('riverway_transit',{'owner_id':A,'gate':0,'arrival':{'x':11,'y':6,'z':4}},B)
    assert state['actors'][B]['position'].get('z',0)==(0 if prone else 4)
    assert any(e['kind']=='MOVEMENT_COMMITTED' and e.get('fall_distance_ft')==20
               for e in state['events']) is prone
    assert cold().journey_replay(jid)['status']=='PASS'


def install_native_reaction(tmp_path, monkeypatch, *, save=False):
    """A synthetic, normally compiled reaction: no private character or live service."""
    import json
    from combat import factory_compiler
    from combat.tabletop import ButtonStore
    key = 'TEST_JOURNEY_SAVE' if save else 'TEST_JOURNEY_WARD'
    effect = ({'type':'attack_modifier','applies_to':'self','flat':100,
               'on':'the failed saving throw','evidence':'Add 100 to the failed saving throw.'}
              if save else {'type':'damage_modifier','applies_to':'self','formula':'none','flat':100,
                            'evidence':'Reduce the damage by 100.'})
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    authority['mechanics'][key] = {
        'mechanic_id':key,'name':'Journey Save' if save else 'Journey Ward',
        'sphere_id':'tianxia.sphere.test','kind':'talent',
        'activation':{'economy':'reaction','trigger':'You fail a saving throw.' if save else 'You take damage.'},
        'effects':[effect],'riders':[],'range':None,'area':None,
        'duration':{'kind':'instant'},'cost':[]}
    path = tmp_path/'journey-authority.json'
    path.write_text(json.dumps(authority))
    monkeypatch.setattr(factory_compiler, 'TYPED_AUTHORITY', path)
    ButtonStore(tmp_path/'tabletop_buttons').save_reactions('61616161', {'mode':'ask'}, {key})
    return key


@pytest.mark.parametrize('selection',['USE','DECLINE'])
def test_ferry_fall_asks_passenger_and_reaction_refreshes_on_journey_clock(tmp_path,monkeypatch,acquired,selection):
    import json
    ward = install_native_reaction(tmp_path,monkeypatch)
    B='actor:factory.61616161'
    cold,jid,act=game(tmp_path,monkeypatch,acquired,cl=10,passenger_talents=[ward],
                      passenger_project='61616161')
    gates=[{'x':5,'y':6},{'x':10,'y':6,'z':3}]
    act('riverway_create',{'source':MOON,'cells':gates})
    act('move',{'path':[gates[0]]},B)
    before=cold().journey_state(jid)
    state=act('riverway_transit',{'owner_id':A,'gate':0,'arrival':{'x':11,'y':6,'z':4}},B)
    assert state['actors'][B]['position']==before['actors'][B]['position']
    assert not any(e['kind']=='TRAVEL_TELEPORT' for e in state['events'])
    assert state['native_pending']['reactor_id']==B
    assert not cold().journey_menu(jid,A)['options']
    options=cold().journey_menu(jid,B)['options']
    assert all('Journey Ward' in o['label'] and 'Moonlit Ferry' in o['label']
               and 'Passenger' in o['label'] for o in options)
    with pytest.raises(Exception,match='Only the creature asked'):
        act('native_choice_decide',{'selection':'USE'},A)
    with pytest.raises(Exception,match='open reaction'):
        act('wait',{'seconds':6},B)
    answer=next(o for o in options if o['payload']['selection']==selection)
    state=act(answer['kind'],answer['payload'],B)
    assert 'native_pending' not in state
    damage=next(e for e in state['events'] if e['kind']=='DAMAGE_COMMITTED')
    assert (damage['reduced_to']==0) is (selection=='USE')
    assert any(e['kind']=='NATIVE_REACTION_DECIDED' and e['selection']==selection for e in state['events'])
    if selection=='USE':
        patch=json.loads(state['actors'][B]['encounter_snapshot']['native_state'])
        assert patch['reaction_available'] is False
        act('wait',{'seconds':6})
        act('riverway_create',{'source':MOON,'cells':[{'x':12,'y':6},{'x':15,'y':6,'z':3}]})
        act('move',{'path':[{'x':12,'y':6}]},B)
        state=act('riverway_transit',{'owner_id':A,'gate':0,'arrival':{'x':16,'y':6,'z':4}},B)
        assert state['native_pending']['reactor_id']==B
        option=next(o for o in cold().journey_menu(jid,B)['options'] if o['payload']['selection']=='USE')
        state=act(option['kind'],option['payload'],B)
        assert sum(e['kind']=='REACTION_RESOLVED' and e.get('source')==ward for e in state['events'])==2
    assert cold().journey_replay(jid)['status']=='PASS'


def test_ferry_fall_ai_passenger_uses_its_own_reaction_without_a_prompt(tmp_path,monkeypatch,acquired):
    ward=install_native_reaction(tmp_path,monkeypatch)
    B='actor:factory.61616161'
    cold,jid,act=game(tmp_path,monkeypatch,acquired,cl=10,passenger_talents=[ward],
                      control_modes={A:'MANUAL',B:'LOCAL_AUTO'},passenger_project='61616161')
    gates=[{'x':5,'y':6},{'x':10,'y':6,'z':3}]
    act('riverway_create',{'source':MOON,'cells':gates})
    act('move',{'path':[gates[0]]},B)
    state=act('riverway_transit',{'owner_id':A,'gate':0,'arrival':{'x':11,'y':6,'z':4}},B)
    assert 'native_pending' not in state
    assert any(e['kind']=='REACTION_RESOLVED' and e.get('source')==ward for e in state['events'])
    assert next(e for e in state['events'] if e['kind']=='DAMAGE_COMMITTED')['reduced_to']==0
    assert cold().journey_replay(jid)['status']=='PASS'


def test_ai_journey_reaction_refuses_an_unanswered_gm_fact(tmp_path,monkeypatch,acquired):
    from combat import ext
    from combat.ext.needle import ask
    ward=install_native_reaction(tmp_path,monkeypatch)
    passenger='actor:factory.61616161'
    ext._load()
    def question(engine,event):
        if event.source_definition_id==ward and event.actor_id==passenger:
            ask(engine,engine._active_intent,'TEST_GM_FACT',engine.state.actors[passenger],
                'choice:needle.journey_gm_fact',['yes','no'],gm_adjudication=True,
                name='Journey Ward',prompt='The GM must decide the external scene fact.')
    monkeypatch.setitem(ext._HOOKS,'reaction_resolved',[*ext._HOOKS['reaction_resolved'],question])
    cold,jid,act=game(tmp_path,monkeypatch,acquired,cl=10,passenger_talents=[ward],
                      control_modes={A:'MANUAL',passenger:'LOCAL_AUTO'},passenger_project='61616161')
    gates=[{'x':5,'y':6},{'x':10,'y':6,'z':3}]
    act('riverway_create',{'source':MOON,'cells':gates})
    act('move',{'path':[gates[0]]},passenger)
    before=cold().journey_state(jid)
    with pytest.raises(Exception,match='requires GM adjudication'):
        act('riverway_transit',{'owner_id':A,'gate':0,'arrival':{'x':11,'y':6,'z':4}},passenger)
    assert cold().journey_state(jid)==before
    assert cold().journey_replay(jid)['status']=='PASS'


def test_journey_native_expiry_and_repeat_save_follow_the_six_second_clock(tmp_path,monkeypatch,acquired):
    import json
    from combat import ext
    from combat.ext.effect_durations import token,round_token
    ward=install_native_reaction(tmp_path,monkeypatch,save=True)
    passenger='actor:factory.61616161'
    ext._load()
    def apply_timed_effects(engine,event):
        if (event.source_definition_id!=ward or event.actor_id!=passenger
                or event.payload.get('source_save')==ward):
            return
        actor=engine.state.actors[passenger]
        engine._apply_condition(actor,'condition:typed.journey_clock_probe',ward,A,
            expires_on=token('start',passenger,actor.turns_started+1))
        engine._apply_condition(actor,'condition:typed.journey_end_probe',ward,A,
            expires_on=token('end',passenger,actor.turns_started+1))
        engine._apply_condition(actor,'condition:typed.journey_permanent_probe',ward,A,
            expires_on='UNTIL_REMOVED')
        engine._apply_condition(actor,'condition:typed.journey_repeat_probe',ward,A,
            expires_on='UNTIL_REMOVED',data={'repeat_save':{'ability':'DEX','dc':30,'when':'end'}})
        engine._add_modifier(actor,ward,'speed_ft','ADD',-5,'ALL_MOVEMENT',
            expires_on=round_token(engine,2),source_actor_id=A)
    monkeypatch.setitem(ext._HOOKS,'reaction_resolved',[*ext._HOOKS['reaction_resolved'],apply_timed_effects])
    cold,jid,act=game(tmp_path,monkeypatch,acquired,passenger_talents=[ward],
                      passenger_project='61616161')
    act('riverway_create',{'source':FIELD,'cells':[{'x':3,'y':6}],'chosen':[A]})
    state=world(cold,jid,'restraint',{'condition':'restrained','source_reference':'scene:snare',
        'source_actor_id':A,'source_dc':30,'save_ability':'DEX'},subject=passenger)
    iid=next(iter(state['actors'][passenger]['encounter_snapshot']['conditions']))
    act('riverway_command',{'mode':'Wash Away','target':passenger,'condition_instance':iid})
    state=act('native_choice_decide',{'selection':'USE'},passenger)
    def contents(state):
        saved=state['actors'][passenger]['encounter_snapshot']
        names={json.loads(row)['condition_id'] for row in saved['conditions'].values()}
        modifiers=json.loads(saved['native_state'])['modifiers']['set']
        return names,modifiers
    names,modifiers=contents(state)
    assert {'condition:typed.journey_clock_probe','condition:typed.journey_end_probe',
            'condition:typed.journey_repeat_probe','condition:typed.journey_permanent_probe'} <= names
    assert any(m['target_field']=='speed_ft' for m in modifiers.values())
    state=act('wait',{'seconds':5})
    assert contents(state)==(names,modifiers)
    state=act('wait',{'seconds':1})
    names,modifiers=contents(state)
    assert 'condition:typed.journey_clock_probe' not in names
    assert 'condition:typed.journey_repeat_probe' in names
    assert 'condition:typed.journey_end_probe' in names
    assert 'condition:typed.journey_permanent_probe' in names
    assert any(m['target_field']=='speed_ft' for m in modifiers.values())
    assert any(e['kind']=='SAVE_ROLLED' and e['seconds']==6 for e in state['events'])
    act('wait',{'seconds':5})
    state=act('move',{'path':[{'x':5,'y':6}]},passenger)
    assert state['seconds']==11 and state['native_pending']['reactor_id']==passenger
    state=act('native_choice_decide',{'selection':'USE'},passenger)
    assert state['seconds']==12 and 'native_pending' not in state
    assert (state['subsecond_num'],state['subsecond_den'])==(1,6)
    step=next(e for e in reversed(state['events']) if e['kind']=='TRAVEL_STEP')
    assert (step['elapsed_num'],step['elapsed_den'])==(7,6)
    names,modifiers=contents(state)
    assert 'condition:typed.journey_repeat_probe' not in names
    assert 'condition:typed.journey_end_probe' not in names
    assert 'condition:typed.journey_permanent_probe' in names
    assert not any(m['target_field']=='speed_ft' for m in modifiers.values())
    assert cold().journey_replay(jid)['status']=='PASS'


@pytest.mark.parametrize('owner_mode',['MANUAL','LOCAL_AUTO'])
def test_wash_away_asks_passenger_before_native_save_settles(tmp_path,monkeypatch,acquired,owner_mode):
    ability=install_native_reaction(tmp_path,monkeypatch,save=True)
    B='actor:factory.61616161'
    cold,jid,act=game(tmp_path,monkeypatch,acquired,passenger_talents=[ability],
                      control_modes={A:owner_mode,B:'MANUAL'},passenger_project='61616161')
    act('riverway_create',{'source':FIELD,'cells':[{'x':3,'y':6}],'chosen':[A,B]})
    state=world(cold,jid,'restraint',{'condition':'restrained','source_reference':'scene:snare',
        'source_actor_id':A,'source_dc':30,'save_ability':'DEX'},subject=B)
    iid=next(iter(state['actors'][B]['encounter_snapshot']['conditions']))
    before=state
    state=act('riverway_command',{'mode':'Wash Away','target':B,'condition_instance':iid})
    assert state['native_pending']['reactor_id']==B
    assert state['actors'][B]['encounter_snapshot']['conditions']==before['actors'][B]['encounter_snapshot']['conditions']
    assert not any(e['kind']=='COMMAND_THE_CURRENT' for e in state['events'])
    options=cold().journey_menu(jid,B)['options']
    assert all('Journey Save' in o['label'] and 'Wash Away' in o['label'] for o in options)
    use=next(o for o in options if o['payload']['selection']=='USE')
    state=act(use['kind'],use['payload'],B)
    assert not state['actors'][B]['encounter_snapshot']['conditions']
    assert any(e['kind']=='REACTION_RESOLVED' and e.get('source')==ability for e in state['events'])
    assert any(e['kind']=='COMMAND_THE_CURRENT' and e['mode']=='Wash Away' for e in state['events'])
    assert cold().journey_replay(jid)['status']=='PASS'


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


@pytest.mark.parametrize('dc',[1,40])
def test_wash_away_journey_matches_native_table_save_and_settlement(tmp_path,monkeypatch,acquired,dc):
    from combat import ext
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import reload,settle,turn
    from tests.test_mgr_t14_riverway_native import candidate

    def bonus(engine,target,ability,save_dc,source,intent):
        if target.entity_id==B and ability=='DEX' and source=='scene:snare':
            return 7
    monkeypatch.setitem(ext._HOOKS,'save_bonus',[*ext._HOOKS.get('save_bonus',()),bonus])
    exposure={'condition':'grappled','source_reference':'scene:snare',
              'source_actor_id':'actor:factory.foe','source_dc':dc,'save_ability':''}

    cold,jid,act=game(tmp_path/'journey',monkeypatch,acquired,extra=True,foe_position={'x':5,'y':6})
    act('riverway_create',{'source':FIELD,'cells':[{'x':3,'y':6}],'chosen':[A,B]})
    state=world(cold,jid,'restraint',exposure)
    iid=next(iter(state['actors'][B]['encounter_snapshot']['conditions']))
    state=act('riverway_command',{'mode':'Wash Away','target':B,'condition_instance':iid,'ability':'DEX'})
    travel_save=next(e for e in reversed(state['events']) if e['kind']=='SAVE_ROLLED')
    travel_removed=iid not in state['actors'][B]['encounter_snapshot']['conditions']
    assert cold().journey_replay(jid)['status']=='PASS'

    cold2,jid2,_=game(tmp_path/'table',monkeypatch,acquired,extra=True,foe_position={'x':5,'y':6})
    state2=world(cold2,jid2,'restraint',exposure)
    iid2=next(iter(state2['actors'][B]['encounter_snapshot']['conditions']))
    result=cold2().journey_start_combat(jid2,state2['revision'],
        {A:'team:factory',B:'team:factory','actor:factory.foe':'team:opponents'})
    mid=result['match_id'];combat=cold2();table=TabletopService(combat,tmp_path/'table')
    turn(table,mid,A)
    settle(table,mid,candidate(combat,mid,'Imperial River Field',at=(3,6)).candidate_id,
        choices={'choice:riverway.Imperial River Field':[A,B]})
    settle(table,mid,candidate(combat,mid,'Command the Current').candidate_id,
        choices={'choice:riverway.command':['Wash Away:'+B],'choice:riverway.wash':[iid2],
                 'choice:riverway.wash_ability':['DEX']})
    engine=reload(tmp_path/'table',mid)
    table_save=next(e.payload for e in reversed(engine.events)
                    if e.event_type=='SAVE_ROLLED' and e.actor_id==B)
    assert travel_save['roll']['modifier']==table_save['modifier']==engine.state.actors[B].saving_throws['DEX']+7
    assert travel_save['roll']['mode']==table_save['mode']=='ADVANTAGE'
    assert travel_save.get('save_bonus_contributions',{})==table_save.get('save_bonus_contributions',{})
    assert travel_removed==(iid2 not in engine.state.actors[B].conditions)==(dc==1)


def test_native_table_wash_uses_actual_imported_restraint_and_source_dc(tmp_path,monkeypatch,acquired):
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import reload,settle,turn
    from tests.test_mgr_t14_riverway_native import candidate
    cold,jid,act=game(tmp_path,monkeypatch,acquired,extra=True,foe_position={'x':5,'y':6})
    state=world(cold,jid,'restraint',{'condition':'grappled','source_reference':'scene:snare',
        'source_actor_id':'actor:factory.foe','source_dc':1,'save_ability':''})
    iid=next(iter(state['actors'][B]['encounter_snapshot']['conditions']))
    result=cold().journey_start_combat(jid,state['revision'],{A:'team:factory',B:'team:factory','actor:factory.foe':'team:opponents'})
    mid=result['match_id'];combat=cold();table=TabletopService(combat,tmp_path)
    turn(table,mid,A)
    settle(table,mid,candidate(combat,mid,'Imperial River Field',at=(3,6)).candidate_id,
        choices={'choice:riverway.Imperial River Field':[A,B]})
    settle(table,mid,candidate(combat,mid,'Command the Current').candidate_id,
        choices={'choice:riverway.command':['Wash Away:'+B],'choice:riverway.wash':[iid],
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
