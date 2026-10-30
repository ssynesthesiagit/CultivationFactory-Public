"""Acquisition -> journey rite -> table intent -> persisted native state/replay."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT,sheet
from tests.worker2_support import turn,settle
PARENT='tianxia.subpath.qi.cremation_cinder_heart'
ASH='resource:named.ash_charge'
FIELD='condition:typed.cremation.field'
A='actor:factory.cremator'; B='actor:factory.target'


def game(tmp_path,monkeypatch,cl=18,owner=True,target_cl=None,target_features=None,target_dc=16,target_hp=60,owner_score=14,parent_features=(),extra_target=False,qi_cl=None,qi_key=None,other_subpath=None,extra_target_hp=None,journey_token=None,owner_features=(),target_scores=None,owner_first=False):
    docs={'cremator':sheet(['tianxia.path.qi_cultivation.feature.qi_sensing',('FIRE_TAL_FIREBALL_ART' if cl>=5 else 'FIRE_TAL_FLAME_LASH'),*parent_features,*owner_features],cl=cl,name='Wren',dc=50,key='CHA',score=owner_score),
          'target':sheet(['tianxia.path.qi_cultivation.feature.qi_sensing',*(target_features or ['FIRE_TAL_FLAME_LASH'])],cl=target_cl or cl,name='Mara',dc=target_dc,key='CHA')}
    if owner_first:
        docs['cremator']['ability_scores_and_statistics']['initiative']={'bonus':1000}
        docs['target']['ability_scores_and_statistics']['initiative']={'bonus':-1000}
    if extra_target:
        import copy
        docs['target2']=copy.deepcopy(docs['target']);docs['target2']['identity']['name']='Tobin'
        for key,bonus in [('cremator',1000),('target',0),('target2',-1000)]:docs[key]['ability_scores_and_statistics']['initiative']={'bonus':bonus}
    if target_scores:
        for key,doc in docs.items():
            if key=='cremator':continue
            for ability in doc['ability_scores_and_statistics']['abilities']:
                if ability['ability'] in target_scores:
                    ability['score']=target_scores[ability['ability']];ability['modifier']=(ability['score']-10)//2
    for doc in docs.values():
        doc['path_and_subpath'].update(path_record_id='tianxia.path.qi_cultivation',path_record_ids=['tianxia.path.qi_cultivation'],paths=[{'path_id':'tianxia.path.qi_cultivation','attainment':doc['identity']['cultivation_level']}])
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
    docs['target']['ability_scores_and_statistics']['hit_points']['maximum']=target_hp
    if extra_target:docs['target2']['ability_scores_and_statistics']['hit_points']['maximum']=extra_target_hp or target_hp
    if qi_cl is not None:docs['cremator']['path_and_subpath']['paths'][0]['attainment']=qi_cl
    if qi_key is not None:docs['cremator']['path_and_subpath']['paths'][0]['key_ability']=qi_key
    if other_subpath:
        docs['cremator']['path_and_subpath'].update(subpath_record_ids=[other_subpath],subpaths=[{'subpath_id':other_subpath,'owning_path_id':'tianxia.path.body_cultivation'}],bindings=[{'path_id':'tianxia.path.body_cultivation','subpath_id':other_subpath}])
    if parent_features:
        docs['cremator']['path_and_subpath'].update(subpath_record_id='tianxia.subpath.qi.cinder_heart_cultivator',subpath_record_ids=['tianxia.subpath.qi.cinder_heart_cultivator'])
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:docs[pid])
    arena={'display_name':'Cremation courtyard','stable_id':'battlefield:cremation-test','width_squares':16,'height_squares':16,'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':arena})
    def cold():return CombatService(ROOT,tmp_path)
    positions={A:{'x':3,'y':3},B:{'x':6,'y':3}}
    if extra_target:positions['actor:factory.target2']={'x':6,'y':4}
    with monkeypatch.context() as setup:
        if journey_token is not None:
            import combat.journey as native_journey
            setup.setattr(native_journey.secrets,'token_hex',lambda n:journey_token)
        state=cold().create_journey(project_ids=list(docs),arena_id='scene',positions=positions,base_paces={aid:100 for aid in positions})
    jid=state['journey_id']
    def world(kind,scope,value,subject=A):
        s=cold();before=s.journey_state(jid)
        return s.journey_world_fact(jid,before['revision'],{'source':PARENT,'subject':subject,'kind':kind,'scope':scope,'value':value,'expires_at':2592000,'readers':[A]})
    def act(kind,payload,actor=A):
        s=cold();before=s.journey_state(jid);after=s.journey_act(jid,before['revision'],actor,kind,payload)
        assert cold().journey_state(jid)==after
        return after
    if owner:
        state=world('source_access','access',{'variant':PARENT,'route':'direct','source_rule':'Native table owner grants legal direct Forbidden Variant access under Shared Qi R4 14.2.'})
        state=cold().journey_acquire_source(jid,state['revision'],A,PARENT,{'access_scope':'access'})
        assert any(e['kind']=='CREMATION_SOURCE_ACQUIRED' for e in state['events'])
    return cold,jid,world,act


def fight(cold,jid,tmp_path,maximum_rounds=20):
    s=cold();state=s.journey_state(jid);mid=s.journey_start_combat(jid,state['revision'],{aid:'team:a' if aid==A else 'team:b' for aid in state['actors']},maximum_rounds=maximum_rounds)['match_id']
    s=cold();table=TabletopService(s,tmp_path);turn(table,mid,A)
    return s,table,mid


def verify(cold,mid):
    session=cold()._load_session(mid)
    assert session.mechanical.replay()['status']=='PASS'
    return session.engine


def test_native_direct_acquisition_rite_ash_reload(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=3)
    world('remains','corpse',{'id':'remains:fallen','kind':'corpse','meaningful':1,'position':{'x':3,'y':4},'source_cl':3,'properties':{'curse':1}})
    state=act('cremation_rite',{'scope':'corpse','result':'ash'})
    assert state['seconds']==600 and state['actors'][A]['source_states'][PARENT]['ash']==1
    with pytest.raises(ValueError,match='already'):act('cremation_rite',{'scope':'corpse','result':'ash'})
    s,t,mid=fight(cold,jid,tmp_path);engine=verify(cold,mid)
    assert engine.state.actors[A].resources[ASH]==1
    assert engine.state.actors[A].resource_maximums[ASH]==next(r['numbers']['pb'] for r in engine.typed_passive_rows[A] if r.get('block')=='cremation_cinder_heart')
    assert not any((a.parameters.get('typed') or {}).get('source','').startswith('tianxia.subpath.qi.cinder_heart_cultivator') for a in engine.action_catalog.values() if a.owner_id==A)


@pytest.mark.parametrize('operation',['Cremation Prison','Cremate Heaven and Earth'])
def test_native_field_activation_concentration_anchor_reload(tmp_path,monkeypatch,operation):
    cold,jid,world,act=game(tmp_path,monkeypatch)
    s,t,mid=fight(cold,jid,tmp_path)
    c=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith(operation) and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,c.candidate_id)
    engine=verify(cold,mid)
    zones=[z for z in engine.state.zones.values() if z.active and z.owner_id==A]
    assert len(zones)==1 and zones[0].concentration_link
    assert zones[0].trigger_profile['visual']['material']=='ash'
    from combat import concentration
    actor=engine.state.actors[A]
    assert actor.concentration is not None or concentration.held(actor)
    if operation=='Cremation Prison':
        anchors=[o for o in engine.state.objects.values() if (o.component or {}).get('cremation_zone')]
        assert len(anchors)==1 and anchors[0].ac==17 and anchors[0].current_hp==90
        assert anchors[0].object_kind=='CULTIVATION_ANCHOR'
    else:assert any(c.condition_id==FIELD for c in engine.state.actors[A].conditions.values())


def test_default_inert_no_owner(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,owner=False)
    s,t,mid=fight(cold,jid,tmp_path);engine=verify(cold,mid)
    assert ASH not in engine.state.actors[A].resources
    assert not any(a.parameters.get('cremation_operation') for a in engine.action_catalog.values())


def test_native_qi_damage_touch_sentence_and_repeat_save(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=6,target_hp=500)
    s,t,mid=fight(cold,jid,tmp_path)
    engine=s._load_session(mid).engine
    c=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    prompts=settle(t,mid,c.candidate_id)
    engine=verify(cold,mid)
    assert any('Cremation Touch' in str(p) for p in prompts)
    assert any('Ash Sentence' in str(p) for p in prompts)
    sentences=[c for c in engine.state.actors[B].conditions.values() if c.condition_id=='condition:typed.cremation.sentence']
    assert len(sentences)==1 and sentences[0].source_actor_id==A
    assert sentences[0].data['full']==1
    assert sentences[0].expires_on.startswith('START_OF_SLOT_AT:')
    packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and B in e.target_ids]
    assert len(packets)>=2
    assert any(e.event_type=='RESOURCE_SPENT' and e.actor_id==A and (engine.action_catalog.get(e.source_definition_id).parameters.get('cremation_operation') if engine.action_catalog.get(e.source_definition_id) else None)=='sentence_trigger' and e.payload['amount']==2 for e in engine.events)


@pytest.mark.parametrize('result',['reanimation','purify','determine'])
def test_native_rite_results_and_touch_guards(tmp_path,monkeypatch,result):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=3)
    doc={'id':'remains:fallen','kind':'corpse','meaningful':1,'position':{'x':3,'y':4},'source_cl':3,'properties':{'curse':1,'poison':1,'possession':0,'corruption':0,'soul_fragment':0,'cultivation_imprint':0}}
    world('remains','corpse',doc)
    state=act('cremation_rite',{'scope':'corpse','result':result})
    outcome=state['actors'][A]['source_states'][PARENT]['rites'][-1]
    assert state['seconds']==600 and outcome['result']==result
    if result=='determine':assert outcome['properties']['curse']==1 and outcome['properties']['poison']==1
    world('remains','far',{**doc,'id':'remains:far','position':{'x':12,'y':12}})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='touch'):act('cremation_rite',{'scope':'far','result':result})
    assert cold().journey_state(jid)==before


@pytest.mark.parametrize('cl,expected',[(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_progression_gates_and_wrong_owner(tmp_path,monkeypatch,cl,expected):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=cl)
    state=cold().journey_state(jid)
    acquired=state['actors'][A]['source_states'][PARENT]
    import json
    ids=json.loads(acquired['sheet'])['path_and_subpath']['source_granted_subpath_feature_record_ids']
    assert len([i for i in ids if i.startswith(PARENT+'.feature.')])==expected
    before=state
    with pytest.raises(ValueError):act('cremation_rite',{'scope':'none','result':'ash'},actor=B)
    assert cold().journey_state(jid)==before


def test_native_spend_ash_temp_hp_payment_and_reload(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=6)
    world('remains','corpse',{'id':'remains:fallen','kind':'corpse','meaningful':1,'position':{'x':3,'y':4},'source_cl':3,'properties':{}})
    act('cremation_rite',{'scope':'corpse','result':'ash'})
    s,t,mid=fight(cold,jid,tmp_path)
    prep=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Spend Ash:'))
    settle(t,mid,prep.candidate_id,picks={'choice:needle.cremation.spend_ash':'temp_hp'})
    engine=verify(cold,mid)
    assert engine.state.actors[A].resources[ASH]==1
    cast=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    settle(t,mid,cast.candidate_id)
    engine=verify(cold,mid)
    assert engine.state.actors[A].resources[ASH]==0
    pb=next(r['numbers']['pb'] for r in engine.typed_passive_rows[A] if r.get('block')=='cremation_cinder_heart')
    assert engine.state.actors[A].temporary_hp==2*pb


@pytest.mark.parametrize('source_cl,mode',[(9,'end'),(10,'minute'),(11,'next_turn')])
def test_native_burn_scripture_source_cl_branches_and_scripture_ash(tmp_path,monkeypatch,source_cl,mode):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=10,target_cl=source_cl,target_features=['FIRE_TAL_BURNING_WEAPON'],target_dc=1,owner_score=40)
    s,t,mid=fight(cold,jid,tmp_path)
    turn(t,mid,B)
    ward=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name=='Burning Weapon')
    settle(t,mid,ward.candidate_id)
    engine=verify(cold,mid)
    assert any(c.condition_id=='condition:typed.state.burning_weapon' for c in engine.state.actors[B].conditions.values())
    turn(t,mid,A)
    cast=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Burn the Scripture — 5 Qi') and c.target_ids==(B,))
    settle(t,mid,cast.candidate_id)
    engine=verify(cold,mid)
    assert engine.state.actors[A].resources[ASH]==1
    ashes=[c for c in engine.state.actors[A].conditions.values() if c.condition_id=='condition:typed.cremation.scripture']
    assert len(ashes)==1
    import json
    assert json.loads(ashes[0].data['profile'])['types']==['FIRE']
    if mode=='end':assert not any(c.condition_id.endswith('burning_weapon') for c in engine.state.actors[B].conditions.values())
    else:
        assert any(c.condition_id=='condition:typed.suppressed.state.burning_weapon' for c in engine.state.actors[B].conditions.values())
        suppressed=engine.state.actors[B].turn_flags['typed_round_suppressed']
        assert suppressed[0]['turn']==engine.state.actors[A].turns_started+(10 if mode=='minute' else 1)


def test_native_prison_start_turn_judgment_is_one_per_turn(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14)
    s,t,mid=fight(cold,jid,tmp_path)
    cast=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,cast.candidate_id)
    turn(t,mid,B)
    engine=verify(cold,mid)
    packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and B in e.target_ids]
    assert packets
    assert any(c.condition_id=='condition:typed.cremation.sealed' for c in engine.state.actors[B].conditions.values())
    assert any(c.condition_id=='condition:typed.cremation.prison_lock' for c in engine.state.actors[B].conditions.values())
    assert any(r.expression.startswith('5d8') for r in engine.rolls)


def test_native_heaven_judgment_final_cremation_and_scene_limit(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=18,target_hp=500)
    s,t,mid=fight(cold,jid,tmp_path)
    lash=next(c for c in s._load_session(mid).engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    settle(t,mid,lash.candidate_id)
    assert any(c.condition_id=='condition:typed.cremation.sentence' for c in verify(cold,mid).state.actors[B].conditions.values())
    # Advance a full native initiative cycle, including the printed repeat save.
    settle(t,mid,t.state(mid)['menu']['end_turn'])
    turn(t,mid,A)
    cast=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremate Heaven and Earth') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,cast.candidate_id)
    engine=verify(cold,mid)
    finals=[c for c in engine.legal_candidates() if c.display_name.startswith('Final Cremation') and c.target_ids==(B,)]
    assert finals
    settle(t,mid,finals[0].candidate_id)
    engine=verify(cold,mid)
    assert any(c.condition_id=='condition:typed.cremation.final' for c in engine.state.actors[B].conditions.values())
    assert any(r.expression.startswith('12d10') for r in engine.rolls)
    assert not any(c.display_name.startswith('Final Cremation') or c.display_name.startswith('Cremate Heaven and Earth') for c in engine.legal_candidates())
    turn(t,mid,B)
    engine=verify(cold,mid)
    assert any(r.expression.startswith('8d8') for r in engine.rolls)
    assert not any(a.costs and a.source_definition_id in {c.source_definition_id for c in engine.legal_candidates()} for a in engine.action_catalog.values() if a.owner_id==B and any(r in ('resource:core.qi','resource:core.stamina','resource:core.resonance') for r,n in a.costs))


def test_native_paid_conversion_replaces_parent_simultaneously(tmp_path,monkeypatch):
    base='tianxia.subpath.qi.cinder_heart_cultivator.feature.cinder_touch'
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=3,owner=False,owner_score=40,parent_features=[base])
    state=world('source_access','conversion',{'variant':PARENT,'route':'conversion','source_rule':'Native inheritance grants Conversion Entry under Shared Qi R4 14.2.'})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='Session'):
        cold().journey_acquire_source(jid,state['revision'],A,PARENT,{'access_scope':'conversion'})
    assert cold().journey_state(jid)==before
    state=act('declare_fact',{'source':PARENT,'subject':A,'kind':'conversion_environment','scope':'training','value':1,'expires_at':28800,'readers':[A]})
    state=cold().journey_acquire_source(jid,state['revision'],A,PARENT,{'access_scope':'conversion','procedure':'train','environment_scope':'training'})
    assert state['seconds']==7200
    state=cold().journey_acquire_source(jid,state['revision'],A,PARENT,{'access_scope':'conversion'})
    import json
    paths=json.loads(state['actors'][A]['source_states'][PARENT]['sheet'])['path_and_subpath']
    assert base not in paths['path_feature_record_ids']
    assert PARENT+'.feature.cremation_furnace_core' in paths['path_feature_record_ids']
    s,t,mid=fight(cold,jid,tmp_path);engine=verify(cold,mid)
    assert ASH in engine.state.actors[A].resources
    assert not any((a.parameters.get('typed') or {}).get('source')==base for a in engine.action_catalog.values() if a.owner_id==A)


def test_native_scripture_ash_resistance_uses_burned_damage_profile(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=10,target_features=['FIRE_TAL_BURNING_WEAPON'],target_cl=9,target_hp=500,owner_score=40)
    s,t,mid=fight(cold,jid,tmp_path)
    turn(t,mid,B)
    ward=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name=='Burning Weapon')
    settle(t,mid,ward.candidate_id);turn(t,mid,A)
    cast=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Burn the Scripture — 5 Qi') and c.target_ids==(B,))
    settle(t,mid,cast.candidate_id)
    prep=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Scripture Ash:'))
    settle(t,mid,prep.candidate_id,picks={'choice:needle.cremation.scripture_benefit':'resistance','choice:needle.cremation.scripture_type':'FIRE'})
    assert any(c.condition_id=='condition:typed.cremation.scripture' for c in verify(cold,mid).state.actors[A].conditions.values())
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    fireball=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    settle(t,mid,fireball.candidate_id)
    engine=verify(cold,mid)
    assert not any(c.condition_id=='condition:typed.cremation.scripture' for c in engine.state.actors[A].conditions.values())
    assert any(m.target_field=='damage_resistance' and str(m.value).upper()=='FIRE' and m.source_definition_id==PARENT+'.feature.burn_the_scripture' for m in engine.state.actors[A].modifiers.values())


def test_native_ordinary_drop_then_cremation_on_zero_hp_does_not_generate_ash(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=6,target_hp=1)
    world('qualifying_subject','threat',{'actor_id':B,'genuine_threat':1,'farmed':0})
    act('cremation_collect_facts',{'scope':'threat'})
    s,t,mid=fight(cold,jid,tmp_path)
    cast=next(c for c in s._load_session(mid).engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    settle(t,mid,cast.candidate_id)
    engine=verify(cold,mid)
    packets=[e.payload for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and B in e.target_ids]
    assert any(p['hp_before']==1 and p['remaining_hp']==0 for p in packets)
    assert engine.state.actors[A].resources[ASH]==0


def test_native_two_cremation_drops_same_round_gain_only_one_charge(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_hp=1,extra_target=True)
    other='actor:factory.target2'
    for aid in (B,other):
        world('qualifying_subject',aid,{'actor_id':aid,'genuine_threat':1,'farmed':0})
        act('cremation_collect_facts',{'scope':aid})
    s,t,mid=fight(cold,jid,tmp_path)
    cast=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(7,5))
    settle(t,mid,cast.candidate_id)
    for _ in range(4):
        engine=verify(cold,mid)
        drops={tid for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.payload.get('hp_before',0)>0 and e.payload.get('remaining_hp')==0 for tid in e.target_ids}
        if {B,other}<=drops:break
        settle(t,mid,t.state(mid)['menu']['end_turn'],picks={'choice:needle.cremation.spend_ash':None})
    assert {B,other}<=drops
    assert engine.state.round_number==1
    assert engine.state.actors[A].resources[ASH]==1
    gains=[e for e in engine.events if e.event_type=='RESOURCE_GAINED' and e.actor_id==A and e.payload.get('resource_id')==ASH]
    assert sum(e.payload['gained'] for e in gains)==1


@pytest.mark.parametrize('kind',['corpse','spirit_shell','destroyed_summon','cultivation_residue','artifact_fragment'])
def test_native_world_declaration_cannot_turn_a_living_native_actor_into_a_corpse(tmp_path,monkeypatch,kind):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=3)
    world('remains','false-corpse',{'id':B,'kind':kind,'meaningful':1,'position':{'x':6,'y':3},'source_cl':3,'properties':{}})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='recorded death'):act('cremation_rite',{'scope':'false-corpse','result':'ash'})
    assert cold().journey_state(jid)==before


def test_native_collected_fact_expires_before_encounter_without_becoming_authority(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=6)
    before=cold().journey_state(jid)
    cold().journey_world_fact(jid,before['revision'],{'source':PARENT,'subject':A,'kind':'qualifying_subject','scope':'brief-threat',
        'value':{'actor_id':B,'genuine_threat':1,'farmed':0},'expires_at':1,'readers':[A]})
    act('cremation_collect_facts',{'scope':'brief-threat'})
    act('wait',{'seconds':1})
    s,t,mid=fight(cold,jid,tmp_path)
    engine=verify(cold,mid)
    assert not any(c.condition_id=='condition:typed.cremation.facts' for c in engine.state.actors[A].conditions.values())


def test_native_collected_fact_preserves_authority_receipt_and_live_expiry(tmp_path,monkeypatch):
    import json
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=6)
    world('qualifying_subject','threat',{'actor_id':B,'genuine_threat':1,'farmed':0})
    act('cremation_collect_facts',{'scope':'threat'})
    s,t,mid=fight(cold,jid,tmp_path)
    engine=verify(cold,mid)
    rows=[c for c in engine.state.actors[A].conditions.values() if c.condition_id=='condition:typed.cremation.facts']
    assert len(rows)==1 and rows[0].expires_on.startswith('START_OF_SLOT_AT:')
    record=json.loads(rows[0].data['record'])
    assert record['authority']=='table_owner' and record['source']==PARENT and record['subject']==A
    assert record['readers']==[A] and record['receipt_id']
    assert not any(c.condition_id=='condition:typed.cremation.facts' for c in engine.state.actors[B].conditions.values())


def test_native_qi_attainment_and_key_are_independent_of_character_primary_path(tmp_path,monkeypatch):
    import json
    other='tianxia.subpath.body.iron_body_cultivator'
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=18,qi_cl=6,qi_key='INT',other_subpath=other)
    state=cold().journey_state(jid)
    paths=json.loads(state['actors'][A]['source_states'][PARENT]['sheet'])['path_and_subpath']
    assert other in paths['subpath_record_ids'] and PARENT in paths['subpath_record_ids']
    assert any(r['subpath_id']==other for r in paths['bindings'])
    s,t,mid=fight(cold,jid,tmp_path);engine=verify(cold,mid)
    rows=[r for r in engine.typed_passive_rows[A] if r.get('block')=='cremation_cinder_heart']
    assert len(rows)==2 and all(r['numbers']['cl']==6 for r in rows)
    assert not any(a.parameters.get('cremation_operation') in ('burn','prison','heaven','final') for a in engine.action_catalog.values() if a.owner_id==A)


@pytest.mark.parametrize('relation',['ALLY','NEUTRAL'])
def test_native_prison_uses_committed_relationship_not_roster_team(tmp_path,monkeypatch,relation):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_hp=500,extra_target=True)
    s,t,mid=fight(cold,jid,tmp_path)
    engine=verify(cold,mid)
    cold().change_relations(mid,change={'kind':'ACTOR_RELATION','subject':A,'other':B,'relation':relation},expected_state_version=engine.state.state_version)
    engine=verify(cold,mid)
    cast=next(c for c in engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,cast.candidate_id)
    turn(t,mid,B)
    engine=verify(cold,mid)
    assert engine.state.actors[B].current_hp==500
    assert not any(c.condition_id.startswith('condition:typed.cremation.') for c in engine.state.actors[B].conditions.values())
    assert not any(r.expression.startswith('5d8') for r in engine.rolls)


@pytest.mark.parametrize('benefit',['damage','discount','move','reveal'])
def test_native_spend_ash_damage_cost_movement_and_reveal_choices(tmp_path,monkeypatch,benefit):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=6,target_hp=500)
    world('remains','residue',{'id':'remains:one','kind':'cultivation_residue','meaningful':1,'position':{'x':3,'y':4},'source_cl':6,'properties':{}})
    act('cremation_rite',{'scope':'residue','result':'ash'})
    s,t,mid=fight(cold,jid,tmp_path)
    engine=verify(cold,mid);before_qi=engine.state.actors[A].resources['resource:core.qi'];before_position=engine.state.actors[A].position
    prep=next(c for c in engine.legal_candidates() if c.display_name.startswith('Spend Ash:'))
    settle(t,mid,prep.candidate_id,picks={'choice:needle.cremation.spend_ash':benefit})
    engine=verify(cold,mid)
    cast=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    listed=dict(engine.action_catalog[cast.source_definition_id].costs)['resource:core.qi']
    prompts=settle(t,mid,cast.candidate_id,picks={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None,'choice:needle.rider_step':'cell:2,3','choice:needle.cremation.ash_reveal':B})
    engine=verify(cold,mid);owner=engine.state.actors[A]
    assert owner.resources[ASH]==0
    assert owner.resources['resource:core.qi']==before_qi-listed+(1 if benefit=='discount' else 0)
    if benefit=='damage':assert any('SPEND_ASH' in str(r.reason) for r in engine.rolls)
    elif benefit=='move':
        assert owner.position!=before_position and engine.grid.distance_ft(before_position,owner.position)<=10
        assert any('Spend Ash' in str(p) for p in prompts)
    elif benefit=='reveal':
        markers=[c for c in engine.state.actors[B].conditions.values() if c.condition_id=='condition:typed.cremation.revealed']
        assert len(markers)==1 and markers[0].source_actor_id==A
        assert markers[0].expires_on.startswith('START_OF_TURN_AT:')


def test_native_prison_continues_with_remaining_time_and_expires_during_journey(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_hp=500)
    s,t,mid=fight(cold,jid,tmp_path,maximum_rounds=1)
    cast=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,cast.candidate_id)
    for _ in range(4):
        if verify(cold,mid).state.terminal_result is not None:break
        settle(t,mid,t.state(mid)['menu']['end_turn'])
    assert verify(cold,mid).state.terminal_result is not None
    before=cold().journey_state(jid)
    state=cold().journey_resume(jid,before['revision'])
    assert cold().journey_state(jid)==state
    fields=state['actors'][A]['source_states'][PARENT]['fields']
    assert len(fields)==1
    remaining=fields[0]['until']-state['seconds']
    assert 0<remaining<=60
    state=act('wait',{'seconds':remaining})
    assert not state['actors'][A]['source_states'][PARENT]['fields']
    s,t,next_mid=fight(cold,jid,tmp_path)
    engine=verify(cold,next_mid)
    assert not any(z.active and (z.trigger_profile.get('profile') or {}).get('cremation') for z in engine.state.zones.values())
    assert not any(not o.destroyed and (o.component or {}).get('cremation_zone') for o in engine.state.objects.values())


def test_native_overlapping_own_seals_burn_each_actual_point_spend_once(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_hp=500,target_features=['FIRE_TAL_FIREBALL_ART'])
    s,t,mid=fight(cold,jid,tmp_path)
    cast=next(c for c in s._load_session(mid).engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    settle(t,mid,cast.candidate_id)
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    prison=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,prison.candidate_id);turn(t,mid,B)
    engine=verify(cold,mid)
    assert any(c.condition_id=='condition:typed.cremation.sentence' and c.data.get('full') for c in engine.state.actors[B].conditions.values())
    assert any(c.condition_id=='condition:typed.cremation.sealed' and c.data.get('full') for c in engine.state.actors[B].conditions.values())
    start=engine.state.event_sequence
    lash=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(0,3))
    settle(t,mid,lash.candidate_id,picks={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None})
    engine=verify(cold,mid)
    spent=[e for e in engine.events if e.sequence>start and e.event_type=='RESOURCE_SPENT' and e.actor_id==B and e.payload['resource_id']=='resource:core.qi']
    burns=[e for e in engine.events if e.sequence>start and e.event_type=='DAMAGE_COMMITTED' and e.actor_id==A and B in e.target_ids]
    assert spent and len(burns)==len(spent)
    assert sum(e.payload['hp_damage'] for e in burns)==sum(e.payload['amount'] for e in spent)


def test_native_zero_cost_qi_sphere_damage_retains_cremation_touch_choice(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=3,target_hp=500,owner_score=40)
    s,t,mid=fight(cold,jid,tmp_path)
    prompts=[]
    for _ in range(4):
        engine=verify(cold,mid)
        lash=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FLAME_LASH') and c.target_ids==(B,))
        assert not engine.action_catalog[lash.source_definition_id].costs
        prompts+=settle(t,mid,lash.candidate_id)
        engine=verify(cold,mid)
        if any('Cremation Touch' in str(p) for p in prompts):break
        settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    assert any('Cremation Touch' in str(p) for p in prompts)
    assert any(e.event_type=='DAMAGE_COMMITTED' and e.payload.get('display_source_id')==PARENT+'.feature.cremation_furnace_core' for e in engine.events)
    assert not any(e.event_type=='RESOURCE_SPENT' and e.actor_id==A and e.payload['resource_id']=='resource:core.qi' for e in engine.events)


def test_native_burn_other_acquired_furnace_uses_sealed_source_profile(tmp_path,monkeypatch):
    import json
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=10,target_cl=14,target_hp=500,owner_score=40)
    state=world('source_access','other-furnace',{'variant':PARENT,'route':'direct','source_rule':'The native table owner grants this second creature legal direct Forbidden Variant access.'},subject=B)
    cold().journey_acquire_source(jid,state['revision'],B,PARENT,{'access_scope':'other-furnace'})
    s,t,mid=fight(cold,jid,tmp_path);turn(t,mid,B)
    prison=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,prison.candidate_id);turn(t,mid,A)
    burn=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Burn the Scripture — 5 Qi') and c.target_ids==(B,))
    settle(t,mid,burn.candidate_id)
    engine=verify(cold,mid)
    zone=next(z for z in engine.state.zones.values() if z.owner_id==B and z.active)
    assert zone.trigger_profile.get('suppressed')
    profile=json.loads(next(c.data['profile'] for c in engine.state.actors[A].conditions.values() if c.condition_id=='condition:typed.cremation.scripture'))
    assert profile['types']==['FIRE','NECROTIC'] and profile['cl']==14 and profile['category']=='Subpath'
    assert profile['tags']==[]


def test_native_ash_journey_menu_rest_and_explicit_scene_boundary(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=3)
    world('remains','residue',{'id':'remains:scene-one','kind':'cultivation_residue','meaningful':1,'position':{'x':3,'y':4},'source_cl':3,'properties':{}})
    state=act('cremation_rite',{'scope':'residue','result':'ash'})
    assert state['actors'][A]['resources'][ASH]==1
    assert cold().journeys.load(jid).menu(A)['resources'][ASH]==1
    state=act('long_rest',{})
    assert state['actors'][A]['resources'][ASH]==0
    assert state['actors'][A]['source_states'][PARENT]['ash']==0
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='already'):act('cremation_rite',{'scope':'residue','result':'ash'})
    assert cold().journey_state(jid)==before
    state=cold().journey_end_scene(jid,before['revision'],'The custodians finish the funerary scene and admit a new scene.')
    assert cold().journey_state(jid)==state
    with pytest.raises(ValueError,match='already cremated'):act('cremation_rite',{'scope':'residue','result':'ash'})
    world('remains','fresh-residue',{'id':'remains:scene-two','kind':'cultivation_residue','meaningful':1,'position':{'x':3,'y':4},'source_cl':3,'properties':{}})
    state=act('cremation_rite',{'scope':'fresh-residue','result':'ash'})
    assert state['actors'][A]['resources'][ASH]==1
    s,t,mid=fight(cold,jid,tmp_path)
    assert verify(cold,mid).state.actors[A].resources[ASH]==1


def test_native_common_artifact_fragment_rite_does_not_grant_unprinted_cl3_results(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=3)
    world('remains','fragment',{'id':'remains:artifact-fragment','kind':'artifact_fragment','meaningful':1,'position':{'x':3,'y':4},'source_cl':10,'properties':{}})
    before=cold().journey_state(jid)
    for result in ('reanimation','purify','determine'):
        with pytest.raises(ValueError,match='artifact-fragment'):act('cremation_rite',{'scope':'fragment','result':result})
        assert cold().journey_state(jid)==before
    state=act('cremation_rite',{'scope':'fragment','result':'ash'})
    assert state['seconds']==600 and state['actors'][A]['resources'][ASH]==1
    s,t,mid=fight(cold,jid,tmp_path)
    assert verify(cold,mid).state.actors[A].resources[ASH]==1


def test_native_sentence_reduces_real_healing_and_denies_real_temporary_hp(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=6,target_hp=500,target_features=['LIFE_BASE_MEND_THE_PULSE','LIFE_BASE_BORROWED_BREATH','tianxia.talent.life.greater_invigorate'])
    s,t,mid=fight(cold,jid,tmp_path)
    cast=next(c for c in s._load_session(mid).engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    settle(t,mid,cast.candidate_id);turn(t,mid,B)
    engine=verify(cold,mid);start=engine.state.event_sequence
    mend=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.LIFE_BASE_MEND_THE_PULSE') and c.target_ids==(B,))
    settle(t,mid,mend.candidate_id)
    engine=verify(cold,mid)
    heals=[e for e in engine.events if e.sequence>start and e.event_type=='HEALING_APPLIED' and B in e.target_ids]
    rolls=[r for r in engine.rolls if str(r.reason).startswith('HEALING:')]
    assert len(heals)==1 and rolls
    assert heals[0].payload['offered']==max(0,rolls[-1].total-4)
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,B)
    engine=verify(cold,mid)
    invigorate=next(c for c in engine.legal_candidates()
        if c.display_name=='Borrowed Breath + Greater Invigorate' and c.target_ids==(B,))
    settle(t,mid,invigorate.candidate_id)
    engine=verify(cold,mid)
    assert engine.state.actors[B].temporary_hp==0
    # A complete denial is a refusal, not a zero-sized grant: the engine must not
    # emit TEMP_HP_GRANTED at all. The old assertion accepted a 0 offer that only
    # appeared because Borrowed Breath caps at missing HP -- it passed while the
    # Sentence's "cannot gain Temporary Hit Points" was inert.
    assert not any(e.sequence>start and e.event_type=='TEMP_HP_GRANTED' and B in e.target_ids for e in engine.events)
    assert any(e.sequence>start and e.event_type=='PASSIVE_TRIGGERED' and B in e.target_ids
        and 'cannot gain Temporary Hit Points' in str(e.payload.get('log','')) for e in engine.events)


def test_native_final_cremation_body_ash_and_failed_restoration_cost(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=18,target_cl=6,target_hp=45,extra_target=True,extra_target_hp=500,
        target_features=['LIFE_BASE_MEND_THE_PULSE','tianxia.talent.life.one_breath_resuscitation'],journey_token='84'*12)
    s,t,mid=fight(cold,jid,tmp_path)
    cast=next(c for c in s._load_session(mid).engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    settle(t,mid,cast.candidate_id)
    assert verify(cold,mid).state.actors[B].current_hp>0
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    heaven=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremate Heaven and Earth') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,heaven.candidate_id)
    final=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Final Cremation') and c.target_ids==(B,))
    settle(t,mid,final.candidate_id)
    engine=verify(cold,mid);target=engine.state.actors[B]
    assert target.current_hp==0
    ash=next(c for c in target.conditions.values() if c.condition_id=='condition:typed.cremation.sovereign_ash')
    assert all(ash.data[k]==0 for k in ('true_soul_erased','samsara_identity_erased','secret_law_erased','artifact_existence_erased'))
    wards=[c for c in target.conditions.values() if c.condition_id=='condition:typed.cremation.funeral' and c.source_actor_id==A]
    assert len(wards)==1 and wards[0].data['sovereign']==1
    assert any(e.event_type=='SAVE_ROLLED' and e.actor_id==B and e.source_definition_id==final.source_definition_id and e.payload['mode']=='DISADVANTAGE' for e in engine.events)
    other='actor:factory.target2';turn(t,mid,other)
    engine=verify(cold,mid);before_qi=engine.state.actors[other].resources['resource:core.qi'];start=engine.state.event_sequence
    heal=next(c for c in engine.legal_candidates() if c.target_ids==(B,) and (c.display_name.startswith('Mend the Pulse') or 'Resuscitation' in c.display_name))
    listed=dict(engine.action_catalog[heal.source_definition_id].costs)['resource:core.qi']
    settle(t,mid,heal.candidate_id)
    engine=verify(cold,mid)
    assert engine.state.actors[B].current_hp==0
    assert engine.state.actors[other].resources['resource:core.qi']==before_qi-listed
    assert not engine.state.actors[other].action_available
    checks=[e for e in engine.events if e.sequence>start and e.event_type=='CHECK_ROLLED' and e.actor_id==other]
    assert len(checks)==1 and checks[0].payload['success'] is False


def test_native_ai_uses_its_own_ash_selector_and_damage_choices(tmp_path,monkeypatch):
    from combat.gate4_adapters import ManualControllerAdapter
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=6,target_hp=500)
    world('remains','residue',{'id':'remains:ai','kind':'cultivation_residue','meaningful':1,'position':{'x':3,'y':4},'source_cl':6,'properties':{}})
    act('cremation_rite',{'scope':'residue','result':'ash'})
    s,t,mid=fight(cold,jid,tmp_path);real=s.controller
    s.set_controller_mode(mid,actor_id=A,controller_mode='LOCAL_AUTO')
    class Fixed:
        operation='prepare'
        def choose_primary_action(self,context):
            if self.operation=='prepare':
                chosen=next(c for c in context.legal_candidates if c.display_name.startswith('Spend Ash:'))
            else:
                chosen=next(c for c in context.legal_candidates if c.display_name.startswith('Fireball Art —') and c.metadata.get('placement_evaluation'))
            choice=ManualControllerAdapter(lambda _: (chosen.candidate_id,())).choose_primary_action(context)
            if chosen.metadata.get('placement_evaluation'):
                from combat.gate2_runtime_models import Position
                # Use only the square projected in this actor's observed context.
                choice=choice.model_copy(update={'intent':choice.intent.model_copy(update={'placement_destination':Position.model_validate(chosen.metadata['placement_evaluation']['destination'])})})
            return choice
        def __getattr__(self,name):return getattr(real,name)
    controller=Fixed();s.controller=controller
    result=t.auto_step(mid,0,[])
    assert result['status']=='COMMITTED',result
    assert verify(cold,mid).state.actors[A].resources[ASH]==1
    controller.operation='fireball'
    result=t.auto_step(mid,0,[])
    assert result['status']=='COMMITTED',result
    engine=verify(cold,mid)
    assert engine.state.actors[A].resources[ASH]==0
    assert any(c.condition_id=='condition:typed.cremation.sentence' and c.source_actor_id==A for actor in engine.state.actors.values() for c in actor.conditions.values())
    assert any(e.event_type=='DAMAGE_COMMITTED' and B in e.target_ids for e in engine.events)


def test_native_human_cremation_choices_remain_on_an_ai_creatures_turn(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_hp=500)
    s,t,mid=fight(cold,jid,tmp_path)
    prison=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,prison.candidate_id)
    s.set_controller_mode(mid,actor_id=B,controller_mode='LOCAL_AUTO')
    prompts=settle(t,mid,t.state(mid)['menu']['end_turn'])
    engine=verify(cold,mid)
    assert engine.state.current_actor_id==B
    assert any('Cremation Touch' in str(p) and p['context']['reactor_id']==A for p in prompts)
    assert any(c.condition_id=='condition:typed.cremation.sentence' and c.source_actor_id==A for c in engine.state.actors[B].conditions.values())


def test_native_spend_ash_moves_an_actually_manifested_domain_armament(tmp_path,monkeypatch):
    from combat.ext.qi_path import armament_point,armament_condition
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=10,target_hp=500,owner_features=['tianxia.path.qi_cultivation.feature.domain_armament'])
    world('remains','residue',{'id':'remains:armament','kind':'cultivation_residue','meaningful':1,'position':{'x':3,'y':4},'source_cl':10,'properties':{}})
    act('cremation_rite',{'scope':'residue','result':'ash'})
    s,t,mid=fight(cold,jid,tmp_path)
    manifest=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Domain Armament: Manifest'))
    settle(t,mid,manifest.candidate_id,picks={'choice:needle.cremation.spend_ash':None})
    engine=verify(cold,mid)
    assert armament_condition(engine.state.actors[A]) is not None
    before=armament_point(engine.state.actors[A])
    prep=next(c for c in engine.legal_candidates() if c.display_name.startswith('Spend Ash:'))
    settle(t,mid,prep.candidate_id,picks={'choice:needle.cremation.spend_ash':'armament'})
    cast=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    prompts=settle(t,mid,cast.candidate_id)
    engine=verify(cold,mid);after=armament_point(engine.state.actors[A])
    assert after!=before and engine.grid.distance_ft(before,after)<=20
    assert engine.state.actors[A].resources[ASH]==0
    assert any('Domain Armament' in str(p) and '20' in str(p) for p in prompts)


@pytest.mark.parametrize('target_cl,expected',[(8,0),(9,1)])
def test_native_qualifying_enemy_cl_boundary_cannot_be_overridden_by_a_declaration(tmp_path,monkeypatch,target_cl,expected):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_cl=target_cl,target_hp=1)
    world('qualifying_subject','threat',{'actor_id':B,'genuine_threat':1,'farmed':0})
    act('cremation_collect_facts',{'scope':'threat'})
    s,t,mid=fight(cold,jid,tmp_path)
    prison=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,prison.candidate_id)
    settle(t,mid,t.state(mid)['menu']['end_turn'])
    engine=verify(cold,mid)
    assert engine.state.actors[B].current_hp==0 and engine.state.actors[A].resources[ASH]==expected


def test_native_unknown_threat_requires_a_private_player_declaration_after_actual_drop(tmp_path,monkeypatch):
    import json
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_hp=1)
    s,t,mid=fight(cold,jid,tmp_path)
    prison=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,prison.candidate_id)
    prompts=settle(t,mid,t.state(mid)['menu']['end_turn'])
    engine=verify(cold,mid)
    assert engine.state.actors[A].resources[ASH]==1
    assert any('genuine threat' in str(p) for p in prompts)
    records=[json.loads(c.data['record']) for c in engine.state.actors[A].conditions.values() if c.condition_id=='condition:typed.fact_consent_admission']
    record=next(r for r in records if r['kind']=='ash_qualifying_subject')
    assert record['authority']==A and record['subject']==A and record['source']==PARENT+'.feature.cremation_furnace_core'
    assert record['value']=='eligible' and record['receipt_id']


def test_native_rite_commits_physical_remains_across_scene_and_casters(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=3)
    doc={'id':'remains:unique-corpse','kind':'corpse','meaningful':1,'position':{'x':3,'y':4},'source_cl':3,'properties':{}}
    world('remains','corpse',doc)
    state=act('cremation_rite',{'scope':'corpse','result':'ash'})
    remains=state['actors'][A]['source_states'][PARENT]['remains'][doc['id']]
    assert remains.get('physical_state')=='cremated_ash'
    assert remains.get('cremator')==A and remains.get('receipt_id')
    state=cold().journey_end_scene(jid,state['revision'],'The funerary scene ends; the same corpse has not returned.')
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='already cremated'):
        act('cremation_rite',{'scope':'corpse','result':'ash'})
    assert cold().journey_state(jid)==before
    state=world('source_access','second-access',{'variant':PARENT,'route':'direct','source_rule':'The table owner grants the second cultivator legal direct entry.'},subject=B)
    state=cold().journey_acquire_source(jid,state['revision'],B,PARENT,{'access_scope':'second-access'})
    world('remains','same-corpse',doc,subject=B)
    act('move',{'path':[{'x':5,'y':4},{'x':4,'y':4}]},actor=B)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='already cremated'):
        act('cremation_rite',{'scope':'same-corpse','result':'ash'},actor=B)
    assert cold().journey_state(jid)==before


def test_native_scripture_damage_adds_one_roll_to_every_recipient_of_that_roll(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=10,target_features=['FIRE_TAL_BURNING_WEAPON'],target_cl=9,target_hp=500,owner_score=40,extra_target=True,extra_target_hp=500)
    s,t,mid=fight(cold,jid,tmp_path);turn(t,mid,B)
    ward=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name=='Burning Weapon')
    settle(t,mid,ward.candidate_id);turn(t,mid,A)
    burn=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Burn the Scripture — 5 Qi') and c.target_ids==(B,))
    settle(t,mid,burn.candidate_id)
    prep=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Scripture Ash:'))
    settle(t,mid,prep.candidate_id,picks={'choice:needle.cremation.scripture_benefit':'damage','choice:needle.cremation.scripture_type':'FIRE'})
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    engine=verify(cold,mid);start=engine.state.event_sequence
    cast=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(5,3))
    settle(t,mid,cast.candidate_id,picks={'choice:needle.cremation.spend_ash':None,'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None})
    engine=verify(cold,mid)
    packets=[e for e in engine.events if e.sequence>start and e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id==cast.source_definition_id]
    # The caster is not one of the engine's hostile-area recipients; use the
    # second enemy so both real recipients of the shared Scripture roll are
    # checked instead of asserting a self-hit the table does not produce.
    assert len([e for e in packets if B in e.target_ids])==2
    assert len([e for e in packets if 'actor:factory.target2' in e.target_ids])==2
    assert len([r for r in engine.rolls if r.expression.startswith('3d8')])==1


def test_native_unspent_prison_ash_roll_survives_encounter_continuation(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_hp=500,owner_first=True)
    world('remains','residue',{'id':'remains:delayed','kind':'cultivation_residue','meaningful':1,'position':{'x':3,'y':4},'source_cl':14,'properties':{}})
    act('cremation_rite',{'scope':'residue','result':'ash'})
    s,t,mid=fight(cold,jid,tmp_path,maximum_rounds=1)
    cast=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,cast.candidate_id,picks={'choice:needle.cremation.spend_ash':'damage'})
    for _ in range(4):
        engine=verify(cold,mid)
        if engine.state.terminal_result:break
        settle(t,mid,t.state(mid)['menu']['end_turn'],picks={'choice:needle.cremation.ash_roll':None,'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None})
    assert verify(cold,mid).state.terminal_result
    state=cold().journey_state(jid);cold().journey_resume(jid,state['revision'])
    s,t,next_mid=fight(cold,jid,tmp_path)
    engine=verify(cold,next_mid)
    # The original creating activation, with an unused paid roll benefit, is still running.
    assert any(z.active for z in engine.state.zones.values())
    prompts=settle(t,next_mid,t.state(next_mid)['menu']['end_turn'],picks={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None})
    assert any(p['context']['reaction_source_id']=='choice:needle.cremation.ash_roll' for p in prompts)
    engine=verify(cold,next_mid)
    assert any(r.payload.get('reason')=='SPEND_ASH' for r in engine.events if r.event_type=='DAMAGE_ROLLED') or any('SPEND_ASH' in str(r) for r in engine.rolls)


@pytest.mark.parametrize('escape_success',[False,True])
def test_native_prison_escape_uses_real_con_then_cha_cost_and_round_limits(tmp_path,monkeypatch,escape_success):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_hp=500,target_features=['TAL_SPACE_FOLD_STEP'],extra_target=True,target_scores={'CON':200,'CHA':200 if escape_success else 2})
    for aid in (B,'actor:factory.target2'):
        world('qualifying_subject',aid,{'actor_id':aid,'genuine_threat':1,'farmed':0});act('cremation_collect_facts',{'scope':aid})
    s,t,mid=fight(cold,jid,tmp_path)
    cast=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,cast.candidate_id)
    for aid in (B,'actor:factory.target2'):
        engine=verify(cold,mid)
        while engine.state.current_actor_id!=aid:
            settle(t,mid,t.state(mid)['menu']['end_turn'],picks={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None})
            engine=verify(cold,mid)
        assert not any(c.condition_id.endswith('prison_lock') for c in engine.state.actors[aid].conditions.values())
        old=engine.state.actors[aid].position;before=engine.state.actors[aid].resources['resource:core.qi']
        step=next(c for c in engine.legal_candidates() if 'Fold Step' in c.display_name and c.destination and c.destination!=old)
        settle(t,mid,step.candidate_id,picks={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None})
        engine=verify(cold,mid)
        assert engine.state.actors[aid].resources['resource:core.qi']==before-1
        assert (engine.state.actors[aid].position!=old)==escape_success
    assert engine.state.actors[A].resources[ASH]==(0 if escape_success else 1)
    assert len([r for r in engine.rolls if 'CHA' in r.reason])>=2


def test_native_anchor_can_be_attacked_and_destroyed_ends_prison(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_hp=500,target_scores={'STR':200,'CON':200})
    s,t,mid=fight(cold,jid,tmp_path)
    cast=next(c for c in s._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,cast.candidate_id)
    settle(t,mid,t.state(mid)['menu']['end_turn'],picks={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None})
    turn(t,mid,B)
    engine=verify(cold,mid);anchor=next(o for o in engine.state.objects.values() if (o.component or {}).get('cremation_zone'))
    for _ in range(4):
        strike=next(c for c in engine.legal_candidates() if c.target_ids==(anchor.object_id,) and engine.action_catalog[c.source_definition_id].parameters.get('object_attack'))
        settle(t,mid,strike.candidate_id)
        engine=verify(cold,mid)
        if engine.state.objects[anchor.object_id].destroyed:break
        settle(t,mid,t.state(mid)['menu']['end_turn'],picks={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None});turn(t,mid,B)
        engine=verify(cold,mid)
    assert engine.state.objects[anchor.object_id].destroyed
    assert not engine.state.zones[anchor.component['cremation_zone']].active
    assert any(e.event_type=='ZONE_REMOVED' and e.payload.get('reason')=='ANCHOR_DESTROYED' for e in engine.events)


def test_native_ai_keeps_prison_placement_and_every_observed_square(tmp_path,monkeypatch):
    from combat.placement_menu import cells
    from combat.candidate_knowledge import query as observed
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_hp=500)
    s,t,mid=fight(cold,jid,tmp_path)
    s.set_controller_mode(mid,actor_id=A,controller_mode='LOCAL_AUTO')
    session=cold()._load_session(mid)
    context=s.ai_decision_context(session)
    root=next(c for c in context.legal_candidates if c.display_name.startswith('Cremation Prison') and c.metadata.get('placement_picker'))
    with observed(session.engine):
        squares=list(cells(session.engine,root))
    assert len(squares)>1 and all(c.destination is not None for c in squares)
    assert any(c.destination.x==7 and c.destination.y==4 for c in squares)


def test_native_sovereign_two_distinct_ash_activations_and_three_qi_bonus_burn(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=18,target_cl=14,target_hp=500,target_features=['FIRE_TAL_BURNING_WEAPON'],owner_score=40)
    for n in range(2):
        world('remains','residue'+str(n),{'id':'remains:sovereign:'+str(n),'kind':'cultivation_residue','meaningful':1,'position':{'x':3,'y':4},'source_cl':18,'properties':{}})
        act('cremation_rite',{'scope':'residue'+str(n),'result':'ash'})
    s,t,mid=fight(cold,jid,tmp_path);turn(t,mid,B)
    ward=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name=='Burning Weapon')
    settle(t,mid,ward.candidate_id);turn(t,mid,A)
    heaven=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremate Heaven and Earth') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,heaven.candidate_id,picks={'choice:needle.cremation.spend_ash':'temp_hp'})
    engine=verify(cold,mid)
    assert engine.state.actors[A].resources[ASH]==1
    assert engine.state.actors[A].temporary_hp==8
    prep=next(c for c in engine.legal_candidates() if c.display_name.startswith('Spend Ash:'))
    prompts=settle(t,mid,prep.candidate_id,picks={'choice:needle.cremation.spend_ash':'discount'})
    options=next(p['choice']['options'] for p in prompts if p['context']['reaction_source_id']=='choice:needle.cremation.spend_ash')
    assert 'temp_hp' not in [r['id'] for r in options]
    bonus=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Burn the Scripture — sovereign Bonus') and c.target_ids==(B,))
    before=verify(cold,mid).state.actors[A].resources['resource:core.qi']
    settle(t,mid,bonus.candidate_id)
    engine=verify(cold,mid)
    assert engine.state.actors[A].resources['resource:core.qi']==before-2
    assert not engine.state.actors[A].bonus_action_available
    import json
    ledger=json.loads(next(c.data['ledger'] for c in engine.state.actors[A].conditions.values() if c.condition_id=='condition:typed.cremation.ledger'))
    assert ledger['benefits']==['temp_hp','discount']
    assert engine.state.actors[A].resources[ASH]==1  # two spent; the burned law generates one.
    assert not any(c.display_name.startswith('Spend Ash:') for c in engine.legal_candidates())
    assert not any(c.display_name.startswith('Burn the Scripture — sovereign Bonus') for c in engine.legal_candidates())


def test_native_successful_sentence_save_has_short_healing_penalty_without_cp_burn(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=6,target_features=['tianxia.talent.life.greater_invigorate'],target_hp=500,target_scores={'CON':200})
    s,t,mid=fight(cold,jid,tmp_path)
    cast=next(c for c in s._load_session(mid).engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    settle(t,mid,cast.candidate_id)
    engine=verify(cold,mid)
    sentence=next(c for c in engine.state.actors[B].conditions.values() if c.condition_id=='condition:typed.cremation.sentence')
    assert not sentence.data['full']
    assert sentence.expires_on.startswith('START_OF_TURN_AT:'+A+':')
    turn(t,mid,B);engine=verify(cold,mid);start=engine.state.event_sequence
    invigorate=next(c for c in engine.legal_candidates() if 'Greater Invigorate' in c.display_name and c.target_ids==(B,))
    settle(t,mid,invigorate.candidate_id)
    engine=verify(cold,mid)
    assert engine.state.actors[B].temporary_hp==0
    assert not any(e.sequence>start and e.event_type=='DAMAGE_COMMITTED' and e.actor_id==A and B in e.target_ids for e in engine.events)
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    assert not any(c.condition_id=='condition:typed.cremation.sentence' and c.source_actor_id==A for c in verify(cold,mid).state.actors[B].conditions.values())


def test_native_world_ash_judgment_uses_public_sphere_name(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=18,target_features=['FIRE_TAL_BURNING_WEAPON'],target_scores={'CON':-100},target_hp=500,owner_first=True)
    s,t,mid=fight(cold,jid,tmp_path)
    turn(t,mid,B)
    ward=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name=='Burning Weapon')
    settle(t,mid,ward.candidate_id)
    turn(t,mid,A)
    field=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Cremate Heaven and Earth') and c.destination and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,field.candidate_id)
    end=t.state(mid)['menu']['end_turn']
    prompts=settle(t,mid,end,picks={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None,'choice:needle.cremation.scorch':'tianxia.sphere.fire'})
    prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.cremation.scorch')
    assert any(option['label']=='Fire' for option in prompt['choice']['options'])
    engine=verify(cold,mid)
    scorched=next(c for c in engine.state.actors[B].conditions.values() if c.condition_id=='condition:typed.cremation.system_scorched')
    assert scorched.data['system']=='tianxia.sphere.fire'
    assert scorched.data['label']=='World-Ash Judgment suppresses Fire'


def test_native_same_casters_overlapping_prisons_do_not_stack_judgment(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_hp=500)
    s,t,mid=fight(cold,jid,tmp_path)
    decline={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None}
    for x in (7,8):
        engine=verify(cold,mid)
        cast=next(c for c in engine.legal_candidates() if c.display_name.startswith('Cremation Prison') and c.destination and (c.destination.x,c.destination.y)==(x,4))
        settle(t,mid,cast.candidate_id)
        if x==7:
            settle(t,mid,t.state(mid)['menu']['end_turn'],picks=decline);turn(t,mid,A)
    engine=verify(cold,mid)
    assert len([z for z in engine.state.zones.values() if z.active and z.owner_id==A])==2
    start=engine.state.event_sequence
    settle(t,mid,t.state(mid)['menu']['end_turn'],picks=decline)
    engine=verify(cold,mid)
    rolls=[e for e in engine.events if e.sequence>start and e.event_type=='DAMAGE_ROLLED' and e.actor_id==A and str(e.payload.get('expression','')).startswith('5d8')]
    assert len(rolls)==1


@pytest.mark.parametrize('outcome',['successful_save','failed_check'])
def test_native_burn_save_and_check_failure_preserve_effect_and_private_information(tmp_path,monkeypatch,outcome):
    from combat.observer_information import readings
    scores={'CON':200} if outcome=='successful_save' else {'CHA':200}
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=10,target_cl=9,target_hp=500,target_features=['FIRE_TAL_BURNING_WEAPON'],target_scores=scores)
    s,t,mid=fight(cold,jid,tmp_path);turn(t,mid,B)
    ward=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name=='Burning Weapon')
    settle(t,mid,ward.candidate_id);turn(t,mid,A)
    engine=verify(cold,mid);start=engine.state.event_sequence
    burn=next(c for c in engine.legal_candidates() if c.display_name.startswith('Burn the Scripture — 5 Qi') and c.target_ids==(B,))
    settle(t,mid,burn.candidate_id,picks={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None})
    engine=verify(cold,mid)
    assert any(c.condition_id=='condition:typed.state.burning_weapon' for c in engine.state.actors[B].conditions.values())
    assert engine.state.actors[A].resources[ASH]==0
    assert not any(c.condition_id=='condition:typed.cremation.scripture' for c in engine.state.actors[A].conditions.values())
    if outcome=='successful_save':
        assert any(e.sequence>start and e.event_type=='DAMAGE_ROLLED' and e.payload.get('expression','').startswith('3d8') for e in engine.events)
        assert not readings(engine,engine.state.actors[A])
    else:
        learned=readings(engine,engine.state.actors[A])
        assert learned and learned[-1]['details']['source_cl']==9 and learned[-1]['details']['category']=='Sphere'
        assert not readings(engine,engine.state.actors[B])
        private=t.state(mid,fog=True,fog_view='own',fog_actor_ids=(A,B))['fog_perception']
        assert any('Source CL 9' in line and 'Sphere' in line
                   for line in private[A].get('information_text',[]))
        assert not private.get(B,{}).get('information_text')
        assert not any(e.sequence>start and e.event_type=='DAMAGE_COMMITTED' for e in engine.events)
