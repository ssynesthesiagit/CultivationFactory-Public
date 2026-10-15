"""Installed Qi character -> source acquisition -> journey/table -> replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import turn, candidate, settle
FAMILY='tianxia.subpath.qi.living_quicksilver_immortal_embryo'
FEATURES=[FAMILY+'.feature.'+s for s in ('living_mercury_body','divide_the_immortal_embryo','assimilate_the_pattern','thousandfold_quicksilver_court','undying_prima_materia')]
A='actor:factory.mercury';B='actor:factory.opponent';QI='resource:core.qi';MASS='resource:named.quicksilver_mass'

def setup(tmp_path,monkeypatch,cl=18,acquire=True,own_features=(),enemy_features=(),positions=None,qi_cl=None,items=()):
    for name in ('mercury','opponent'):
        doc=sheet([*(own_features if name=='mercury' else enemy_features),'tianxia.path.qi_cultivation.feature.qi_sensing',*(['tianxia.path.qi_cultivation.feature.domain_armament'] if cl>=9 else [])],cl=cl,name=name.title())
        if name=='mercury' and items:doc['equipment']=[{'starting_kit':{'items':[{'item_id':item,'name':item,'quantity':1} for item in items]}}]
        doc['identity']['proficiency_bonus']=2+(cl-1)//4
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=max(30,2*cl)
        doc['path_and_subpath'].update(path_record_id='tianxia.path.qi_cultivation',path_record_ids=['tianxia.path.qi_cultivation'],paths=[{'path_id':'tianxia.path.qi_cultivation','attainment':cl if qi_cl is None else qi_cl,'effective_cl':cl if qi_cl is None else qi_cl}])
        folder=tmp_path/'portable_characters'/name;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    arena={'display_name':'Mercury courtyard','stable_id':'battlefield:mercury','width_squares':12,'height_squares':12,'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':arena})
    def cold():return CombatService(ROOT,tmp_path)
    state=cold().create_journey(project_ids=['mercury','opponent'],arena_id='scene',positions=positions or {A:{'x':3,'y':3},B:{'x':8,'y':3}},base_paces={A:100,B:100})
    jid=state['journey_id']
    def world(kind,scope,value,subject=A,readers=None):
        s=cold();state=s.journey_state(jid)
        return s.journey_world_fact(jid,state['revision'],{'source':FAMILY,'subject':subject,'kind':kind,'scope':scope,'value':value,'expires_at':int(state['seconds'])+2592000,'readers':readers or [A]})
    def act(kind,payload=None,who=A):
        s=cold();state=s.journey_state(jid);after=s.journey_act(jid,state['revision'],who,kind,payload or {})
        assert cold().journey_state(jid)==after
        return after
    if acquire:
        world('source_access','inheritance',{'variant':FAMILY,'route':'direct','source_rule':'A living mercury inheritance grants the first Qi Subpath choice.'})
        state=cold().journey_state(jid);state=cold().journey_acquire_source(jid,state['revision'],A,FAMILY,{'access_scope':'inheritance'})
        assert any(e['kind']=='QUICKSILVER_SOURCE_ACQUIRED' for e in state['events'])
    return cold,jid,act,world

def combat(cold,jid,tmp_path):
    s=cold();state=s.journey_state(jid);mid=s.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'})['match_id']
    table=TabletopService(cold(),tmp_path);turn(table,mid,A)
    return table,mid

def engine(cold,mid):
    session=cold()._load_session(mid)
    assert session.mechanical.replay()['status']=='PASS'
    assert not any(e.event_type=='GM_RIDER' and e.source_definition_id.startswith('ext:combat.ext.mgr_reserve_living') for e in session.engine.events)
    return session.engine

def use(cold,table,mid,label,picks=None):
    c=candidate(cold(),mid,label,at=(3,4) if label.startswith('Create Quicksilver Body') else None)
    settle(table,mid,c.candidate_id,picks=picks)
    return engine(cold,mid)

@pytest.mark.parametrize('cl,count',[(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_access_acquires_only_earned_progression_and_scene_mass(tmp_path,monkeypatch,cl,count):
    cold,jid,act,world=setup(tmp_path,monkeypatch,cl)
    state=cold().journey_state(jid);bundle=state['actors'][A]['bundle']
    owned={p['feature_id'] for p in bundle['typed_passives'] if p.get('block')=='living_quicksilver'}
    assert owned==set(FEATURES[:count])
    assert state['actors'][A]['resources'][MASS]==(bundle['actor_template']['proficiency_bonus']+1)//2
    assert MASS not in state['actors'][B]['resources']
    table,mid=combat(cold,jid,tmp_path);e=engine(cold,mid)
    assert e.state.actors[A].resources[MASS]==(bundle['actor_template']['proficiency_bonus']+1)//2
    assert MASS not in e.state.actors[B].resources

def test_no_access_or_unknown_source_cannot_grant_features(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,acquire=False)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):cold().journey_acquire_source(jid,before['revision'],A,FAMILY,{'access_scope':'invented'})
    assert cold().journey_state(jid)==before
    with pytest.raises(ValueError):cold().journey_acquire_source(jid,before['revision'],A,'unknown',{})
    assert cold().journey_state(jid)==before

def test_body_creation_rejoin_cost_capacity_and_cold_replay(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,6)
    table,mid=combat(cold,jid,tmp_path)
    e=use(cold,table,mid,'Create Quicksilver Body: 2 Qi')
    bodies=[o for o in e.state.objects.values() if o.component.get('quicksilver_body') and not o.destroyed]
    assert len(bodies)==1 and bodies[0].maximum_hp==12 and bodies[0].ac==14
    assert e.state.actors[A].resources[QI]==28
    e=use(cold,table,mid,'Rejoin: regain Quicksilver Mass')
    assert all(o.destroyed for o in e.state.objects.values() if o.component.get('quicksilver_body'))
    assert e.state.actors[A].resources[MASS]==3


def test_full_cultivation_changes_only_superficial_profile_and_uses_two_hours(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,3)
    act('declare_fact',{'source':FAMILY,'subject':A,'kind':'cultivation_environment','scope':'calm','value':{'calm':1,'ambient_qi':1},'expires_at':10000,'readers':[A]})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('quicksilver_cultivate',{'environment_scope':'calm','appearance':{'functional_wings':'yes'}})
    assert cold().journey_state(jid)==before
    after=act('quicksilver_cultivate',{'environment_scope':'calm','appearance':{'hair':'silver','voice_resonance':'deep'}})
    assert after['seconds']==7200
    assert after['actors'][A]['source_states'][FAMILY]['appearance']=={'hair':'silver','voice_resonance':'deep'}
    table,mid=combat(cold,jid,tmp_path)
    e=engine(cold,mid)
    held=next(c for c in e.state.actors[A].conditions.values() if c.condition_id=='condition:typed.living_quicksilver_ledger')
    assert held.data['appearance']['hair']=='silver'


def test_undying_native_activation_free_body_turn_choice_expiry_and_replay(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,18)
    table,mid=combat(cold,jid,tmp_path)
    e=use(cold,table,mid,'Undying Prima Materia')
    assert e.state.actors[A].resources[QI]==28
    from combat.flight import profile
    assert profile(e,e.state.actors[A]).speed_ft==50 and profile(e,e.state.actors[A]).hover
    turn(table,mid,B)
    from tests.worker2_support import settle
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.quicksilver.configuration':'mirror'})
    e=engine(cold,mid)
    bs=[o for o in e.state.objects.values() if o.component.get('quicksilver_body') and not o.destroyed]
    assert bs and all(o.maximum_hp==72 and o.component['hover']==1 for o in bs)
    # The transformation still has a native ten-round expiry, never rest-of-fight.
    held=next(c for c in e.state.actors[A].conditions.values() if c.condition_id=='condition:typed.undying_prima_materia')
    from combat.ext.effect_durations import parse_round
    assert parse_round(held.expires_on)==(11,e.state.initiative_order.index(A))


def test_body_occupies_space_without_creating_a_wall_and_wrong_owner_is_inert(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,6)
    table,mid=combat(cold,jid,tmp_path)
    e=use(cold,table,mid,'Create Quicksilver Body: 2 Qi')
    body=next(o for o in e.state.objects.values() if o.component.get('quicksilver_body'))
    assert (3,4) in e._occupied_cells_except(A)
    assert e.grid.line_of_sight(e.state.actors[A].position,e.state.actors[B].position)
    assert not any(c.destination==body.position for c in e.legal_candidates() if c.kind=='MOVE')
    assert not any(c.parameters.get('quicksilver_command') for c in e.action_catalog.values() if c.owner_id==B)
    # No dependent creature/initiative slot was invented for the targetable Body.
    assert set(e.state.actors)=={A,B}
    assert set(e.state.initiative_order)=={A,B}


def test_native_scene_boundary_cannot_be_faked_by_rest_or_actor_declaration(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,18)
    act('declare_fact',{'source':FAMILY,'subject':A,'kind':'cultivation_environment','scope':'calm','value':{'calm':1,'ambient_qi':1},'expires_at':10000,'readers':[A]})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):
        act('declare_fact',{'source':'system:journey.scene','subject':A,'kind':'scene_end','scope':'false-end','value':'It ended','expires_at':1,'readers':[A]})
    assert cold().journey_state(jid)==before
    after=act('long_rest')
    assert not any(e['kind']=='SCENE_ENDED' for e in after['events'])
    next_scene=cold().journey_end_scene(jid,after['revision'],'The table owner ends the courtyard encounter and begins a new meaningful situation.')
    assert next_scene['actors'][A]['resources'][MASS]==3
    assert any(e['kind']=='SCENE_ENDED' for e in next_scene['events'])


@pytest.mark.parametrize('guard',['below_path_level','expired_access','wrong_subject','repeat_acquisition','unowned_cultivation'])
def test_source_authority_boundaries_are_native_atomic(tmp_path,monkeypatch,guard):
    cold,jid,act,world=setup(tmp_path,monkeypatch,2 if guard=='below_path_level' else 6,acquire=guard in ('repeat_acquisition','unowned_cultivation'))
    if guard=='unowned_cultivation':
        before=cold().journey_state(jid)
        with pytest.raises(ValueError):act('quicksilver_cultivate',{'environment_scope':'unknown'},B)
        assert cold().journey_state(jid)==before
        return
    if guard!='repeat_acquisition':
        world('source_access','inheritance',{'variant':FAMILY,'route':'direct','source_rule':'An actual inheritance Source grants the first Subpath choice.'})
    if guard=='expired_access':act('wait',{'seconds':2592000})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):
        cold().journey_acquire_source(jid,before['revision'],B if guard=='wrong_subject' else A,FAMILY,{'access_scope':'inheritance'})
    assert cold().journey_state(jid)==before


def test_native_qi_damage_conversion_poison_resistance_and_mass_are_not_blanket_immunity(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,3,own_features=['FIRE_BASE_CONFLAGRATION'])
    world('source_access','second-inheritance',{'variant':FAMILY,'route':'direct','source_rule':'A second actual living mercury inheritance grants this creature its first Qi Subpath choice.'},subject=B,readers=[B])
    state=cold().journey_state(jid)
    cold().journey_acquire_source(jid,state['revision'],B,FAMILY,{'access_scope':'second-inheritance'})
    table,mid=combat(cold,jid,tmp_path)
    before=engine(cold,mid).state.actors[B].current_hp
    c=candidate(cold(),mid,'Conflagration',at=(8,3))
    prompts=settle(table,mid,c.candidate_id,picks={'choice:needle.quicksilver.conversion':'POISON'})
    e=engine(cold,mid)
    packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and B in x.target_ids]
    assert packets and packets[-1].payload['damage_type']=='POISON'
    p=packets[-1].payload
    assert p['reduced_to']==p['rolled_or_pending_damage']//2
    assert e.state.actors[B].current_hp<before
    assert e.state.actors[B].resources[MASS]==2
    assert e.state.actors[A].resources[QI]==27
    assert any(p['context']['reactor_id']==A for p in prompts if p['context']['reaction_source_id']=='choice:needle.quicksilver.conversion')


def test_record_pattern_comes_from_actual_hostile_qi_resolution_and_replays(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,10,enemy_features=['FIRE_BASE_CONFLAGRATION'])
    table,mid=combat(cold,jid,tmp_path)
    turn(table,mid,B)
    c=candidate(cold(),mid,'Conflagration',at=(3,3))
    prompts=settle(table,mid,c.candidate_id,picks={'choice:needle.quicksilver.record_pattern':'0'})
    e=engine(cold,mid)
    d=next(c.data for c in e.state.actors[A].conditions.values() if c.condition_id=='condition:typed.living_quicksilver_ledger')
    assert d['pattern']['kind']=='damage' and d['pattern']['value']=='FIRE'
    assert d['pattern']['source']=='FIRE_BASE_CONFLAGRATION'
    assert e.state.actors[A].resources[QI]==27 and not e.state.actors[A].reaction_available
    assert e.state.actors[A].resources[MASS]==3
    assert any(p['context']['reactor_id']==A for p in prompts if p['context']['reaction_source_id']=='choice:needle.quicksilver.record_pattern')


def test_cultivation_menu_requires_live_environment_and_keeps_existing_appearance(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,3)
    def options():return cold().journey_menu(jid,A)['options']
    assert not any(o['kind']=='quicksilver_cultivate' for o in options())
    act('declare_fact',{'source':FAMILY,'subject':A,'kind':'cultivation_environment','scope':'calm','value':{'calm':1,'ambient_qi':1},'expires_at':30000,'readers':[A]})
    option=next(o for o in options() if o['kind']=='quicksilver_cultivate')
    assert option['payload']=={'environment_scope':'calm'} and option['auto_select']==0
    act('quicksilver_cultivate',{**option['payload'],'appearance':{'hair':'silver'}})
    after=act('quicksilver_cultivate',option['payload'])
    assert after['seconds']==14400
    assert after['actors'][A]['source_states'][FAMILY]['appearance']=={'hair':'silver'}
    gains=[e for e in after['events'] if e['kind']=='RESOURCE_GAINED' and e.get('recovery_method')=='full']
    assert len(gains)==1
    act('quicksilver_short_rest')
    act('quicksilver_short_rest')
    after=act('long_rest')
    assert after['seconds']==50400
    assert len([e for e in after['events'] if e['kind']=='RESOURCE_GAINED' and e.get('recovery_method')=='short'])==1
    assert len([e for e in after['events'] if e['kind']=='RESOURCE_GAINED' and e.get('recovery_method')=='long'])==1
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('quicksilver_short_rest',who=B)
    assert cold().journey_state(jid)==before
    assert not any(e['kind']=='SCENE_ENDED' for e in after['events'])


def test_perfected_body_flight_mirror_object_attack_and_native_replay(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,18,positions={A:{'x':3,'y':3},B:{'x':4,'y':4}})
    table,mid=combat(cold,jid,tmp_path)
    e=use(cold,table,mid,'Create Quicksilver Body: 2 Qi')
    first=next(o for o in e.state.objects.values() if o.component.get('quicksilver_body'))
    assert first.current_hp==36 and first.maximum_hp==36 and 'PSYCHIC' in first.damage_immunities
    turn(table,mid,B);turn(table,mid,A)
    e=use(cold,table,mid,'Undying Prima Materia')
    assert e.state.objects[first.object_id].current_hp==36 and e.state.objects[first.object_id].maximum_hp==72
    turn(table,mid,B)
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.quicksilver.free_body':'5,4,0','choice:needle.quicksilver.configuration':'mirror'})
    e=engine(cold,mid)
    second=next(o for o in e.state.objects.values() if o.component.get('quicksilver_body') and o.object_id!=first.object_id)
    assert second.current_hp==72
    e=use(cold,table,mid,'Move Quicksilver Bodies',picks={
        'choice:needle.quicksilver.move_'+first.object_id:'3,4,1',
        'choice:needle.quicksilver.move_'+second.object_id:'5,4,0'})
    assert e.state.objects[first.object_id].position.z==1
    assert e.state.objects[first.object_id].component['repair_allowed'] is False
    turn(table,mid,B)
    c=candidate(cold(),mid,'Attack an object',target=first.object_id)
    settle(table,mid,c.candidate_id,picks={'choice:needle.quicksilver.body_exchange':None})
    e=engine(cold,mid)
    attack=next(x for x in reversed(e.events) if x.event_type=='ATTACK_ROLLED' and first.object_id in x.target_ids)
    assert attack.payload['mode']=='DISADVANTAGE'


@pytest.mark.parametrize('invalid',[{'categories':['ordinary']},{'categories':['secret','secret']},{'categories':[{}]},{'categories':['secret'],'save_dc':1}])
def test_native_pattern_authority_admission_is_typed_atomic_and_cannot_be_actor_supplied(tmp_path,monkeypatch,invalid):
    cold,jid,act,world=setup(tmp_path,monkeypatch,10,enemy_features=['FIRE_BASE_CONFLAGRATION'])
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):world('pattern_authority','FIRE_BASE_CONFLAGRATION',invalid,subject=B,readers=[A])
    assert cold().journey_state(jid)==before
    with pytest.raises(ValueError):act('declare_fact',{'source':FAMILY,'subject':A,'kind':'pattern_authority','scope':'FIRE_BASE_CONFLAGRATION','value':{'categories':['secret']},'expires_at':100,'readers':[A]})
    assert cold().journey_state(jid)==before


def test_native_protected_pattern_uses_actual_source_dc_check_and_replays(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,10,enemy_features=['FIRE_BASE_CONFLAGRATION'])
    world('pattern_authority','FIRE_BASE_CONFLAGRATION',{'categories':['secret']},subject=B,readers=[A])
    table,mid=combat(cold,jid,tmp_path);turn(table,mid,B)
    c=candidate(cold(),mid,'Conflagration',at=(3,3))
    settle(table,mid,c.candidate_id,picks={'choice:needle.quicksilver.record_pattern':'0'})
    e=engine(cold,mid)
    check=next(x for x in e.events if x.event_type=='CHECK_ROLLED' and x.source_definition_id==FEATURES[2])
    assert check.payload['dc']==16
    state=next(c.data for c in e.state.actors[A].conditions.values() if c.condition_id=='condition:typed.living_quicksilver_ledger')
    assert bool(state.get('pattern')) is check.payload['success']
    assert e.state.actors[A].resources[QI]==27 and e.state.actors[A].resources[MASS]==3
    assert not e.state.actors[A].reaction_available
    if check.payload['success']:assert state['pattern']['authority']==['secret']
    else:assert any('exceeds your current assimilation' in str(x.payload) for x in e.events)


def test_weapon_sea_two_guard_origins_do_not_stack_and_end_on_native_departure(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,18,positions={A:{'x':3,'y':3},B:{'x':4,'y':4}})
    table,mid=combat(cold,jid,tmp_path)
    e=use(cold,table,mid,'Create Quicksilver Body: 2 Qi')
    first=next(o.object_id for o in e.state.objects.values() if o.component.get('quicksilver_body'))
    turn(table,mid,B);turn(table,mid,A)
    c=candidate(cold(),mid,'Create Quicksilver Body: 2 Qi',at=(5,4));settle(table,mid,c.candidate_id)
    e=engine(cold,mid);second=next(o.object_id for o in e.state.objects.values() if o.component.get('quicksilver_body') and o.object_id!=first)
    turn(table,mid,B);turn(table,mid,A)
    use(cold,table,mid,'Undying Prima Materia');turn(table,mid,B)
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.quicksilver.free_body':'6,4,0','choice:needle.quicksilver.configuration':'sea'})
    e=use(cold,table,mid,'Weapon-Sea: Guard Mode from two origins',picks={
        'choice:needle.quicksilver.sea_first':first,'choice:needle.quicksilver.sea_second':second,
        'choice:needle.quicksilver.sea_guard_'+first:B,'choice:needle.quicksilver.sea_guard_'+second:B})
    guards=[m for m in e.state.actors[B].modifiers.values() if m.source_definition_id=='passive:'+FEATURES[4]+'.guard']
    assert len(guards)==1 and guards[0].value==2 and guards[0].source_actor_id==A
    assert guards[0].expires_on=='START_OF_SOURCE_NEXT_TURN'
    held=next(c for c in e.state.actors[B].conditions.values() if c.condition_id=='condition:typed.quicksilver_sea_guard')
    assert set(held.data['origins'])=={first,second}
    turn(table,mid,B)
    e=engine(cold,mid)
    move=next(c for c in e.legal_candidates() if c.kind=='MOVE' and c.destination.x==9 and c.destination.y==4 and c.destination.z==0)
    settle(table,mid,move.candidate_id)
    e=engine(cold,mid)
    assert not any(c.condition_id=='condition:typed.quicksilver_sea_guard' for c in e.state.actors[B].conditions.values())
    assert not any(m.source_definition_id=='passive:'+FEATURES[4]+'.guard' for m in e.state.actors[B].modifiers.values())


def test_variant_progression_scales_with_actual_qi_path_cl_in_multi_path_native_build(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,18,qi_cl=6)
    state=cold().journey_state(jid)
    rows=[p for p in state['actors'][A]['bundle']['typed_passives'] if p.get('block')=='living_quicksilver']
    assert {p['feature_id'] for p in rows}==set(FEATURES[:2])
    assert all(p['numbers']['cl']==6 for p in rows)
    table,mid=combat(cold,jid,tmp_path)
    e=use(cold,table,mid,'Create Quicksilver Body: 2 Qi')
    body=next(o for o in e.state.objects.values() if o.component.get('quicksilver_body'))
    assert body.current_hp==12 and body.component['source_cl']==6
    assert not any(c.display_name=='Undying Prima Materia' for c in e.legal_candidates())


def test_native_body_sensing_projection_is_private_and_does_not_publish_source_identity(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,14)
    table,mid=combat(cold,jid,tmp_path)
    e=use(cold,table,mid,'Create Quicksilver Body: 2 Qi')
    from combat.senses import perception
    before=e.state.model_dump(mode='json');events=len(e.events)
    own=perception(e,e.state.actors[A]);other=perception(e,e.state.actors[B])
    rows=own['information']
    body=next(r for r in rows if r['kind']=='quicksilver_body')
    assert body['viewer_id']==A and body['details']['hp']==28
    presence=[r for r in rows if r['kind']=='qi_presence']
    assert presence and any(r['details']['origin_id'].startswith('object:asset:') for r in presence)
    assert all(set(r['details'])=={'origin_id','direction','presence'} for r in presence)
    assert not any(r['kind'] in ('quicksilver_body','qi_presence') for r in other.get('information',[]))
    assert e.state.model_dump(mode='json')==before and len(e.events)==events
    assert engine(cold,mid).state.model_dump(mode='json')==before



def test_full_cultivation_requires_native_appropriate_substitute_when_ambient_qi_is_absent(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,3)
    act('declare_fact',{'source':FAMILY,'subject':A,'kind':'cultivation_environment','scope':'spring','value':{'calm':1,'ambient_qi':0,'substitute_scope':'actual-spring'},'expires_at':10000,'readers':[A]})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('quicksilver_cultivate',{'environment_scope':'spring'})
    assert cold().journey_state(jid)==before
    assert not any(o['kind']=='quicksilver_cultivate' for o in cold().journey_menu(jid,A)['options'])
    with pytest.raises(ValueError):world('cultivation_substitute','actual-spring',{'scene_id':'a different scene','source_description':'Consecrated alchemical spring','appropriate':1})
    assert cold().journey_state(jid)==before
    world('cultivation_substitute','actual-spring',{'scene_id':'battlefield:mercury','source_description':'Consecrated alchemical spring','appropriate':1})
    option=next(o for o in cold().journey_menu(jid,A)['options'] if o['kind']=='quicksilver_cultivate')
    after=act(option['kind'],option['payload'])
    assert after['seconds']==7200
    completed=next(e for e in after['events'] if e['kind']=='QUICKSILVER_FULL_CULTIVATION')
    admitted=next(e for e in after['events'] if e['kind']=='WORLD_FACT_DECLARED' and e['kind_name']=='cultivation_substitute')
    assert completed['substitute_receipt']==admitted['receipt_id']



def test_later_installed_qi_attainment_earns_only_variant_progression_on_native_continuation(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,6)
    act('finish')
    packet=tmp_path/'portable_characters/mercury/current.zip'
    with zipfile.ZipFile(packet) as z:advanced=json.loads(z.read('Tianxia_Owner_Character_Sheet_v1.json'))
    # New installed build output changes attainment. It grants no family ID;
    # the previously committed native acquisition owns the progression grant.
    advanced['identity'].update(cultivation_level=10,proficiency_bonus=4)
    advanced['path_and_subpath']['paths']=[{'path_id':'tianxia.path.qi_cultivation','attainment':10,'effective_cl':10}]
    with zipfile.ZipFile(packet,'w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(advanced))
    next_state=cold().create_journey(project_ids=['mercury','opponent'],arena_id='scene',positions={A:{'x':3,'y':3},B:{'x':8,'y':3}},base_paces={A:100,B:100})
    next_jid=next_state['journey_id']
    assert cold().journey_state(next_jid)==next_state
    rows=[p for p in next_state['actors'][A]['bundle']['typed_passives'] if p.get('block')=='living_quicksilver']
    assert {p['feature_id'] for p in rows}==set(FEATURES[:3])
    grants=[e for e in next_state['events'] if e['kind']=='QUICKSILVER_PROGRESSION_EARNED']
    assert len(grants)==1 and grants[0]['earned_features']==[FEATURES[2]]
    assert not any(p.get('feature_id','').startswith('tianxia.subpath.qi.mercurial_cultivator.') for p in next_state['actors'][A]['bundle']['typed_passives'])
    table,mid=combat(cold,next_jid,tmp_path)
    e=use(cold,table,mid,'Create Quicksilver Body: 2 Qi')
    body=next(o for o in e.state.objects.values() if o.component.get('quicksilver_body'))
    assert body.current_hp==20 and body.component['source_cl']==10



def test_mutable_armament_uses_actual_inventory_identity_consent_free_grips_and_turn_clock(tmp_path,monkeypatch):
    weapon='tianxia.mortal.weapon.jian'
    cold,jid,act,world=setup(tmp_path,monkeypatch,3,items=[weapon],enemy_features=['TAL_SCOUNDREL_STEAL'],positions={A:{'x':3,'y':3},B:{'x':4,'y':3}})
    item=next(i for i in cold().journey_state(jid)['actors'][A]['bundle']['carrying']['items'] if i['item_id']==weapon)
    world('item_authority','selected-jian',{'item_id':item['key'],'name':'Jian','kind':'weapon','held':1,'legal_use':1,'sentient':1,'artifact_merge':'allowed'})
    act('declare_fact',{'source':FAMILY,'subject':A,'kind':'cultivation_environment','scope':'calm','value':{'calm':1,'ambient_qi':1},'expires_at':20000,'readers':[A]})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('quicksilver_cultivate',{'environment_scope':'calm','item_scope':'selected-jian'})
    assert cold().journey_state(jid)==before
    world('sentient_item_consent','actual-jian-consent',{'item_id':item['key'],'consent':1})
    after=act('quicksilver_cultivate',{'environment_scope':'calm','item_scope':'selected-jian','consent_scope':'actual-jian-consent'})
    assert after['seconds']==7200
    table,mid=combat(cold,jid,tmp_path);e=engine(cold,mid)
    from combat import carry
    from combat.ext.hand_occupancy import free_hands
    from combat.ext.scoundrel_riders import possessions,held_possessions
    root=A+'|'+item['key']
    actual=[r for r in possessions(e,e.state.actors[A]) if r['object']==root]
    assert len(actual)==1 and actual[0]['location']=='merged'
    assert not any(r['object']==root for r in held_possessions(e,e.state.actors[A]))
    assert len(free_hands(e,e.state.actors[A]))==2
    weight=carry.weight(e,e.state.actors[A]);qi=e.state.actors[A].resources[QI]
    e=use(cold,table,mid,'Mutable Armament: manifest or merge',picks={'choice:needle.quicksilver.armament_hand':'hand:right'})
    assert any(r['object']==root for r in held_possessions(e,e.state.actors[A]))
    assert len(free_hands(e,e.state.actors[A]))==1
    assert carry.weight(e,e.state.actors[A])==weight and e.state.actors[A].resources[QI]==qi
    assert not any(c.display_name=='Mutable Armament: manifest or merge' for c in e.legal_candidates())
    turn(table,mid,B);turn(table,mid,A)
    e=use(cold,table,mid,'Mutable Armament: manifest or merge')
    assert len(free_hands(e,e.state.actors[A]))==2 and carry.owned_item_location(e.state.actors[A],item['key'])=='merged'
    assert not any(any(r.get('item')==item['key'] for r in (e.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('effects',[])) for c in e.legal_candidates() if c.source_definition_id in e.action_catalog)
    turn(table,mid,B)
    c=candidate(cold(),mid,'STEAL',target=A)
    prompts=settle(table,mid,c.candidate_id)
    assert not any('Jian' in str(p.get('choice',{})) for p in prompts)
    e=engine(cold,mid)
    assert carry.owned_item_location(e.state.actors[A],item['key'])=='merged'
    assert len([r for r in possessions(e,e.state.actors[A]) if r['object']==root])==1


def test_native_lethal_fire_packet_reconstitutes_once_with_actual_body_destruction_and_exhaustion(tmp_path,monkeypatch):
    # Fix only the journey's external identity generator, so its ordinary native
    # deterministic match seed is reproducible. Rolls, ownership, HP, resources,
    # trigger receipts and the engine's runtime methods are not patched.
    from types import SimpleNamespace
    from combat import journey
    monkeypatch.setattr(journey,'secrets',SimpleNamespace(token_hex=lambda size:f'{18180001:024x}'))
    cold,jid,act,world=setup(tmp_path,monkeypatch,18,enemy_features=['FIRE_BASE_CONFLAGRATION'])
    table,mid=combat(cold,jid,tmp_path)
    use(cold,table,mid,'Undying Prima Materia')
    picks={'choice:needle.quicksilver.record_pattern':None,
        'choice:needle.quicksilver.configuration':'mirror',
        'choice:needle.quicksilver.reconstitution_space':'current'}
    found=False
    for _ in range(10):
        if table.state(mid)['menu']['actor_id']==A:
            settle(table,mid,table.state(mid)['menu']['end_turn'],picks=picks)
        c=candidate(cold(),mid,'Conflagration',at=(3,3))
        settle(table,mid,c.candidate_id,picks=picks)
        e=engine(cold,mid)
        if any(x.event_type=='HEALING_APPLIED' and x.source_definition_id==FEATURES[4] for x in e.events):found=True;break
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks=picks)
        e=engine(cold,mid)
        if any(x.event_type=='HEALING_APPLIED' and x.source_definition_id==FEATURES[4] for x in e.events):found=True;break
    assert found,'The deterministic native hostile packets must reach the transformation’s first zero-HP trigger.'
    owner=e.state.actors[A]
    heals=[x for x in e.events if x.event_type=='HEALING_APPLIED' and x.source_definition_id==FEATURES[4]]
    assert len(heals)==1 and heals[0].payload['after']==5*owner.proficiency_bonus
    assert owner.current_hp>0 and owner.resources[QI]==0 and owner.active
    assert not any(c.condition_id=='condition:typed.undying_prima_materia' for c in owner.conditions.values())
    bodies=[o for o in e.state.objects.values() if o.component.get('quicksilver_body')]
    assert bodies and all(o.destroyed and o.current_hp==0 for o in bodies)
    from combat.ext.forged_exhaustion import level
    assert level(owner)==1
    ledger=next(c.data for c in owner.conditions.values() if c.condition_id=='condition:typed.living_quicksilver_ledger')
    assert ledger['transformation_used']==1 and not ledger.get('replacement_used')
    assert any(x.event_type=='DAMAGE_COMMITTED' and A in x.target_ids for x in e.events)
