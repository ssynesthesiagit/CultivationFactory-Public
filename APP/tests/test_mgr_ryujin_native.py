"""Native acquisition -> journey -> table intent -> cold mechanical replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import candidate, settle, turn
P='tianxia.subpath.body.ryujin'; R=P+'.feature.'
A='actor:factory.dragon'; B='actor:factory.partner'; C='actor:factory.opponent'
STAMINA='resource:core.stamina'
MILESTONES=[(3,'dragon_scales'),(6,'dragon_s_breath'),(10,'storm_step'),(14,'dragon_s_roar'),(18,'ryujin_ascendant_form')]


def access(service,jid,actor=A):
    state=service.journey_state(jid)
    return service.journey_world_fact(jid,state['revision'],{'source':P,'subject':actor,'kind':'source_access','scope':'inheritance',
        'value':{'category':'Rare Inheritance','source_rule':'GM establishes inherited Ryujin bloodline'},'expires_at':3600,'readers':[actor]})


def game(tmp_path,*,cl=18,acquire=True,path='tianxia.path.body_refining',attainment=None,objects=(),owner_kit=None,owner_hp=1000,foe_cl=None):
    for pid in ('dragon','partner','opponent'):
        level=foe_cl if pid=='opponent' and foe_cl is not None else cl
        doc=sheet([],cl=level,primary='Stamina',name=pid.title(),dc=50,kit=owner_kit if pid=='dragon' else None)
        doc['identity']['path']='Body Refining'
        doc['ability_scores_and_statistics']['hit_points']['maximum']=owner_hp if pid=='dragon' else 1000
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
        doc['path_and_subpath']={'path_record_id':path,'path_record_ids':[path],
            'paths':[{'path_id':path,'effective_cl':level if attainment is None else attainment}],
            'path_feature_record_ids':['tianxia.path.body_refining.feature.unarmored_defense']}
        doc['ability_scores_and_statistics']['armor_class']={'base_value':14,
            'generation':{'calculation_feature_id':'tianxia.path.body_refining.feature.unarmored_defense'}}
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    service=CombatService(ROOT,tmp_path)
    service.tabletop_maps.save({'display_name':'Ryujin yard','width_squares':12,'height_squares':12,'walls':[],
        'starts':{'team1':[[3,6],[5,7]],'team2':[[5,6]]},'objects':list(objects)})
    state=service.create_journey(project_ids=['dragon','partner','opponent'],arena_id='battlefield:map.ryujin-yard',
        positions={A:{'x':3,'y':6},B:{'x':5,'y':7},C:{'x':5,'y':6}},base_paces={a:100 for a in (A,B,C)},control_modes={a:'MANUAL' for a in (A,B,C)})
    jid=state['journey_id']
    if acquire:
        state=access(service,jid)
        state=service.journey_act(jid,state['revision'],A,'declare_fact',{'source':P,'subject':A,'kind':'anatomy','scope':'body',
            'value':{'breath_organ':'mouth','scales':'concealable'},'expires_at':3600,'readers':[A]})
        state=service.journey_acquire_source(jid,state['revision'],A,P,{'access_scope':'inheritance','anatomy_scope':'body'})
    return service,jid,state


def fight(service,jid,tmp_path):
    state=service.journey_state(jid)
    mid=service.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:a',C:'team:b'})['match_id']
    service=CombatService(ROOT,tmp_path);table=TabletopService(service,tmp_path);turn(table,mid,A)
    return service,table,mid


def acquired_seeded_fight(service,jid,tmp_path):
    """Seal the actual acquisition output with a fixed native combat seed.

    This uses the same production finalizer as journey_start_combat. It never
    edits a bundle, inserts a feature, injects an action, or scripts a roll.
    Other tests exercise journey entry and continuation themselves.
    """
    state=service.journey_state(jid)
    assert any(e['kind']=='RYUJIN_ACQUIRED' and e['actor_id']==A for e in state['events'])
    ids=[A,B,C]
    mid=service._finish_factory_match([state['actors'][aid]['bundle'] for aid in ids],ids,
        {A:'team:a',B:'team:a',C:'team:b'},
        {aid:state['actors'][aid]['position'] for aid in ids},
        service.factory_arenas()['battlefield:map.ryujin-yard'],[A,B],[C],
        control_modes={aid:'MANUAL' for aid in ids},match_seed='MGR-RYUJIN-STACKED-HIT',
        display_name='Native acquired Ryujin hit',maximum_rounds=15)['match_id']
    service=CombatService(ROOT,tmp_path);table=TabletopService(service,tmp_path);turn(table,mid,A)
    return service,table,mid


def cold(tmp_path,mid):
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status']=='PASS'
    return loaded.engine


@pytest.mark.parametrize('cl',[2,3,6,10,14,18])
def test_native_acquisition_progression_and_wrong_owner(tmp_path,cl):
    if cl<3:
        service,jid,state=game(tmp_path,cl=cl,acquire=False);access(service,jid);state=service.journey_state(jid)
        with pytest.raises(ValueError):service.journey_acquire_source(jid,state['revision'],A,P,{'access_scope':'inheritance','anatomy_scope':'body'})
        assert service.journey_state(jid)==state
        return
    service,jid,state=game(tmp_path,cl=cl)
    assert state['actors'][A]['source_states'][P]['features']==[R+n for l,n in MILESTONES if l<=cl]
    assert 'source_states' not in state['actors'][B]
    service,table,mid=fight(service,jid,tmp_path);engine=cold(tmp_path,mid)
    sources={a.parameters.get('typed',{}).get('source') for a in engine.action_catalog.values() if a.owner_id==A}
    assert {R+n for l,n in MILESTONES if 3<l<=cl}<=sources
    assert not any(a.parameters.get('typed',{}).get('source','').startswith(R) for a in engine.action_catalog.values() if a.owner_id==B)


def test_breath_and_roar_native_commit_save_damage_reload(tmp_path):
    service,jid,_=game(tmp_path);service,table,mid=fight(service,jid,tmp_path)
    for name,cost in [("Dragon's Breath",2),("Dragon's Roar",5)]:
        before=cold(tmp_path,mid).state.actors[A].resources[STAMINA]
        settle(table,mid,candidate(service,mid,name,at=(5,6)).candidate_id,choices={'choice:needle.ryujin_damage':['THUNDER']})
        engine=cold(tmp_path,mid);assert engine.state.actors[A].resources[STAMINA]==before-cost
        for target in (B,C):assert any(e.event_type=='DAMAGE_COMMITTED' and target in e.target_ids for e in engine.events)
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={});turn(table,mid,A)


def test_ascendant_native_profiles_flight_size_and_step(tmp_path):
    from combat.flight import profile
    from combat import dynamic_size
    service,jid,_=game(tmp_path);service,table,mid=fight(service,jid,tmp_path)
    settle(table,mid,candidate(service,mid,'Ryūjin Ascendant Form').candidate_id,choices={'choice:needle.ryujin_size':['large']})
    engine=cold(tmp_path,mid);actor=engine.state.actors[A]
    assert actor.resources[STAMINA]==93
    assert profile(engine,actor).speed_ft==60 and profile(engine,actor).hover
    assert dynamic_size.current_category(engine,actor)=='Large'
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={});turn(table,mid,A)
    settle(table,mid,candidate(service,mid,'Storm Step (Ascendant)').candidate_id,
        choices={'choice:needle.teleport_destination':['cell:7,6'],'choice:needle.ryujin_damage':['LIGHTNING'],'choice:needle.storm_recipients':[C]})
    engine=cold(tmp_path,mid)
    assert engine.state.actors[A].resources[STAMINA]==92 and engine.state.actors[A].position.x==7


@pytest.mark.parametrize('guard',['wrong_path','wrong_attainment','no_access','wrong_subject','bad_anatomy','expired_access','duplicate'])
def test_source_admission_guards_are_atomic(tmp_path,guard):
    service,jid,state=game(tmp_path,acquire=guard=='duplicate',
        path='tianxia.path.qi_cultivation' if guard=='wrong_path' else 'tianxia.path.body_refining',
        attainment=2 if guard=='wrong_attainment' else 18)
    if guard=='duplicate':
        before=service.journey_state(jid)
        with pytest.raises(ValueError):service.journey_acquire_source(jid,before['revision'],A,P,{'access_scope':'inheritance','anatomy_scope':'body'})
        assert service.journey_state(jid)==before
        return
    if guard!='no_access':state=access(service,jid)
    if guard=='wrong_subject':
        before=service.journey_state(jid)
        with pytest.raises(ValueError):service.journey_act(jid,before['revision'],B,'declare_fact',{
            'source':P,'subject':A,'kind':'anatomy','scope':'body','value':{'breath_organ':'mouth','scales':'visible'},'expires_at':3600,'readers':[A]})
        assert service.journey_state(jid)==before
        return
    state=service.journey_act(jid,state['revision'],A,'declare_fact',{'source':P,'subject':A,'kind':'anatomy','scope':'body',
        'value':{'breath_organ':'mouth','scales':'invented'} if guard=='bad_anatomy' else {'breath_organ':'mouth','scales':'visible'},'expires_at':3600,'readers':[A]})
    if guard=='expired_access':state=service.journey_act(jid,state['revision'],A,'wait',{'seconds':3600})
    before=service.journey_state(jid)
    with pytest.raises(ValueError):service.journey_acquire_source(jid,before['revision'],A,P,{'access_scope':'inheritance','anatomy_scope':'body'})
    assert service.journey_state(jid)==before


def test_scales_and_form_share_one_real_unarmed_hit(tmp_path):
    service,jid,_=game(tmp_path);service,table,mid=acquired_seeded_fight(service,jid,tmp_path)
    settle(table,mid,candidate(service,mid,'Ryūjin Ascendant Form').candidate_id,
        choices={'choice:needle.ryujin_size':None})
    engine=service._load_session(mid).engine
    # Use the actual move menu to approach; no placement or turn/economy edit.
    move=next(c for c in engine.legal_candidates() if c.destination and c.destination.x==4 and c.destination.y==6 and c.kind.value=='MOVE')
    settle(table,mid,move.candidate_id,choices={})
    for _ in range(5):
        engine=service._load_session(mid).engine
        attack=next(c for c in engine.legal_candidates() if c.target_ids==(C,) and c.source_definition_id in engine.action_catalog
            and any(r.get('attack_kind')=='unarmed' for r in engine.action_catalog[c.source_definition_id].parameters.get('typed',{}).get('effects',[])))
        settle(table,mid,attack.candidate_id,choices={'choice:needle.ryujin_damage':['THUNDER']})
        engine=cold(tmp_path,mid)
        packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==A and C in e.target_ids]
        scales=[e for e in packets if e.payload.get('damage_type')=='LIGHTNING']
        if scales:
            assert len(scales)==1
            assert scales[0].payload.get('hp_damage')==4
            assert any(e.payload.get('damage_type')=='THUNDER' for e in packets)
            assert not any('Dragon Scales' in a.display_name for a in engine.action_catalog.values())
            return
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={});turn(table,mid,A)
    raise AssertionError('The seeded native unarmed strikes never hit.')


def test_secondary_body_attainment_sets_breath_dice(tmp_path):
    service,jid,state=game(tmp_path,cl=18,attainment=6)
    assert state['actors'][A]['source_states'][P]['features']==[R+'dragon_scales',R+'dragon_s_breath']
    service,table,mid=fight(service,jid,tmp_path)
    settle(table,mid,candidate(service,mid,"Dragon's Breath",at=(5,6)).candidate_id,
        choices={'choice:needle.ryujin_damage':['LIGHTNING']})
    engine=cold(tmp_path,mid)
    assert any(r.expression.startswith('4d6') for r in engine.rolls if r.reason.startswith('DAMAGE:'))
    assert not any(r.expression.startswith('8d6') for r in engine.rolls if r.reason.startswith('DAMAGE:'))


def test_form_clock_survives_real_encounter_resume_wait_and_scene_boundary(tmp_path):
    from fractions import Fraction
    service,jid,state=game(tmp_path)
    mid=service.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:a',C:'team:b'},maximum_rounds=1,
        positions={A:{'x':3,'y':6},B:{'x':9,'y':8},C:{'x':10,'y':6}})['match_id']
    service=CombatService(ROOT,tmp_path);table=TabletopService(service,tmp_path);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,'Ryūjin Ascendant Form').candidate_id,choices={'choice:needle.ryujin_size':['large']})
    engine=cold(tmp_path,mid)
    record=next(c for c in engine.state.actors[A].conditions.values() if c.condition_id=='condition:typed.state.ryujin_ascendant_form')
    assert record.data['transformation']['chosen_size']=='Large'
    for _ in range(12):
        if cold(tmp_path,mid).state.terminal_result:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert cold(tmp_path,mid).state.terminal_result
    state=service.journey_state(jid)
    state=service.journey_resume(jid,state['revision'])
    carried=state['actors'][A]['source_states'][P]['form']
    remaining=Fraction(carried['remaining_num'],carried['remaining_den'])
    assert 0<remaining<=60
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    state=service.journey_act(jid,state['revision'],A,'wait',{'seconds':1})
    carried=state['actors'][A]['source_states'][P]['form']
    assert Fraction(carried['remaining_num'],carried['remaining_den'])==remaining-1
    # Re-enter through the actual journey caller: the remaining form is a
    # continuation, not a new activation, Stamina charge or scene-use refund.
    mid=service.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:a',C:'team:b'},maximum_rounds=1,
        positions={A:{'x':3,'y':6},B:{'x':9,'y':8},C:{'x':10,'y':6}})['match_id']
    service=CombatService(ROOT,tmp_path);table=TabletopService(service,tmp_path)
    engine=cold(tmp_path,mid)
    from combat.flight import profile
    assert profile(engine,engine.state.actors[A]).speed_ft==60
    assert engine.state.actors[A].resources[STAMINA]==93
    assert any('ryujin_deadline_num' in c.data for c in engine.state.actors[A].conditions.values())
    for _ in range(12):
        if cold(tmp_path,mid).state.terminal_result:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    state=service.journey_state(jid);state=service.journey_resume(jid,state['revision'])
    carried=state['actors'][A]['source_states'][P]['form']
    assert Fraction(carried['remaining_num'],carried['remaining_den'])<remaining-1
    uses={r:v for r,v in state['actors'][A]['resources'].items() if r.startswith('resource:uses.')}
    assert any(v==0 for v in uses.values())
    state=service.journey_act(jid,state['revision'],A,'wait',{'seconds':61})
    assert 'form' not in state['actors'][A]['source_states'][P]
    assert {r:state['actors'][A]['resources'][r] for r in uses}==uses
    assert state['actors'][A]['resources'][STAMINA]==93
    state=service.journey_end_scene(jid,state['revision'],'The courtyard encounter and pursuit have ended.')
    assert all(state['actors'][A]['resources'][r]==1 for r in uses)
    assert state['actors'][A]['resources'][STAMINA]==93


def object_row(number,**values):
    return {'id':number,'kind':'custom','size':'tiny','x':5,'y':6,'material':'glass',
            'hp':999,'blocks':False,'unattended':True,**values}


def test_native_map_gm_fragility_classification_immunity_and_threshold(tmp_path):
    objects=[object_row(1,fragile=False),object_row(2,material='wood',fragile=True),
             object_row(3,fragile=True,immune=['THUNDER']),object_row(4,fragile=True,threshold=999)]
    service,jid,state=game(tmp_path,objects=objects)
    saved=service.tabletop_maps.get('ryujin-yard')['objects']
    assert saved[0]['fragile'] is False and saved[1]['fragile'] is True
    service,table,mid=fight(service,jid,tmp_path)
    settle(table,mid,candidate(service,mid,"Dragon's Breath",at=(5,6)).candidate_id,
        choices={'choice:needle.ryujin_damage':['THUNDER']})
    engine=cold(tmp_path,mid)
    assert engine.state.objects['object:map.1'].current_hp==999
    assert engine.state.objects['object:map.2'].current_hp<999
    assert engine.state.objects['object:map.3'].current_hp==999
    assert engine.state.objects['object:map.4'].current_hp==999
    assert engine.state.objects['object:map.1'].component['fragile'] is False
    assert engine.state.objects['object:map.2'].component['fragile'] is True


def test_native_roar_classifications_double_once_and_keep_controlled_objects(tmp_path):
    objects=[object_row(1,material='stone',unattended=False,temporary_barrier=True,formation_anchor=True),
             object_row(2,fragile=False),object_row(3,unattended=False),
             object_row(4,artifact=True,immune=['THUNDER'])]
    service,jid,_=game(tmp_path,objects=objects);service,table,mid=fight(service,jid,tmp_path)
    settle(table,mid,candidate(service,mid,"Dragon's Roar",at=(5,6)).candidate_id,choices={})
    engine=cold(tmp_path,mid)
    first=999-engine.state.objects['object:map.1'].current_hp
    assert first>0 and first==999-engine.state.objects['object:map.2'].current_hp
    assert engine.state.objects['object:map.3'].current_hp==999
    assert engine.state.objects['object:map.4'].current_hp==999
    rolled=next(r.total for r in engine.rolls if r.reason.startswith('DAMAGE:') and r.expression.startswith('5d8'))
    assert first==rolled*2
    assert engine.state.objects['object:map.1'].component['formation_anchor'] is True


def test_native_scales_lightning_resistance_with_worn_armor_and_unconsciousness(tmp_path):
    from combat.typed_reactions import damage_factor
    armor={'items':[{'item_id':'tianxia.mortal.armor.imperial_plate_battle_dress',
                     'name':'Imperial Plate Battle Dress','quantity':1}]}
    service,jid,state=game(tmp_path,owner_kit=armor,owner_hp=20,foe_cl=6)
    state=access(service,jid,C)
    state=service.journey_act(jid,state['revision'],C,'declare_fact',{'source':P,'subject':C,'kind':'anatomy','scope':'body',
        'value':{'breath_organ':'mouth','scales':'visible'},'expires_at':3600,'readers':[C]})
    state=service.journey_acquire_source(jid,state['revision'],C,P,{'access_scope':'inheritance','anatomy_scope':'body'})
    service,table,mid=fight(service,jid,tmp_path)
    engine=cold(tmp_path,mid)
    assert engine.state.actors[A].armor_class==18
    assert any(item.get('worn') for bundle in engine.typed_bundle_documents if bundle['actor_id']==A
               for item in bundle['carrying']['items'])
    turn(table,mid,C)
    source=None
    for index in range(12):
        action=candidate(service,mid,"Dragon's Breath",at=(3,6));source=action.source_definition_id
        settle(table,mid,action.candidate_id,choices={'choice:needle.ryujin_damage':['LIGHTNING']})
        engine=cold(tmp_path,mid)
        if index==0:
            rolled=next(r.total for r in reversed(engine.rolls) if r.reason.startswith('DAMAGE:') and r.expression.startswith('4d6'))
            assert engine.state.actors[A].current_hp==20-rolled//2
        if engine.state.actors[A].current_hp==0:
            assert any('unconscious' in c.condition_id for c in engine.state.actors[A].conditions.values())
            assert damage_factor(engine,engine.state.actors[A],'LIGHTNING',source,C)==0.5
            return
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={});turn(table,mid,C)
    raise AssertionError('Native breath damage did not reach the unconscious boundary.')


def test_native_new_scene_form_refresh_has_one_aura_and_can_decline_large(tmp_path):
    from combat import dynamic_size
    service,jid,state=game(tmp_path)
    def encounter(state):
        mid=service.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:a',C:'team:b'},maximum_rounds=1,
            positions={A:{'x':3,'y':6},B:{'x':9,'y':8},C:{'x':10,'y':6}})['match_id']
        table=TabletopService(service,tmp_path);turn(table,mid,A)
        return table,mid
    def finish(table,mid):
        for _ in range(12):
            if cold(tmp_path,mid).state.terminal_result:break
            settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
        assert cold(tmp_path,mid).state.terminal_result
        state=service.journey_state(jid)
        return service.journey_resume(jid,state['revision'])
    table,mid=encounter(state)
    settle(table,mid,candidate(service,mid,'Ryūjin Ascendant Form').candidate_id,
        choices={'choice:needle.ryujin_size':['large']})
    state=finish(table,mid)
    assert 'form' in state['actors'][A]['source_states'][P]
    state=service.journey_end_scene(jid,state['revision'],'The first confrontation has ended; a new confrontation begins.')
    table,mid=encounter(state)
    settle(table,mid,candidate(service,mid,'Ryūjin Ascendant Form').candidate_id,
        choices={'choice:needle.ryujin_size':None})
    engine=cold(tmp_path,mid)
    assert engine.state.actors[A].resources[STAMINA]==86
    assert dynamic_size.current_category(engine,engine.state.actors[A])=='Medium'
    sources={a.source_definition_id for a in engine.action_catalog.values()
             if a.owner_id==A and a.parameters.get('typed',{}).get('source')==R+'ryujin_ascendant_form'}
    assert len([z for z in engine.state.zones.values() if z.active and z.owner_id==A and z.source_definition_id in sources])==1
