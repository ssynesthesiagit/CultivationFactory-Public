"""Native declarations -> paid ritual -> CombatService -> table -> cold replay."""
import hashlib
import json
import pytest
from tests.soul_contract_evidence_support import source_checkpoint
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet
from tests.worker2_support import turn, settle, candidate
PARENT='tianxia.subpath.qi.soul_collateral_contract_cultivator'
FEATURES=[PARENT+'.feature.'+s for s in ('sign_in_living_qi','foreclose_minor_collateral','major_soul_covenant','soul_foreclosure','sovereign_soul_contract')]
A='actor:factory.creditor';B='actor:factory.debtor';QI='resource:core.qi';E='condition:typed.soul_contract_ledger'

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def game(tmp_path,monkeypatch,cl=6,owner=True,debtor_kit=None,debtor_cl=None,owner_dc=16,parent_features=None,path_level=None,positions=None):
    qi_sense='tianxia.path.qi_cultivation.feature.qi_sensing'
    docs={'creditor':sheet([qi_sense,*(parent_features or [])],cl=cl,name='Wren',dc=owner_dc,key='CHA'),
          'debtor':sheet([qi_sense],cl=debtor_cl if debtor_cl is not None else cl,name='Mara',kit=debtor_kit,key='CHA')}
    for doc in docs.values():
        paths=doc.setdefault('path_and_subpath',{})
        paths.update(path_record_id='tianxia.path.qi_cultivation',path_record_ids=['tianxia.path.qi_cultivation'],
            paths=[{'path_id':'tianxia.path.qi_cultivation','attainment':path_level if path_level is not None else doc['identity']['cultivation_level']}])
    if parent_features:
        docs['creditor']['path_and_subpath'].update(subpath_record_id=PARENT.replace('soul_collateral_contract','oath_ledger'),
            subpath_record_ids=[PARENT.replace('soul_collateral_contract','oath_ledger')])
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:docs[pid])
    arena={'display_name':'Contract courtyard','stable_id':'battlefield:soul-test','width_squares':12,'height_squares':12,'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':arena})
    s=CombatService(ROOT,tmp_path)
    state=s.create_journey(project_ids=list(docs),arena_id='scene',positions=positions or {A:{'x':3,'y':3},B:{'x':4,'y':3}},base_paces={A:100,B:100})
    jid=state['journey_id']
    if owner:
        # The Source features are earned by the actual native acquisition path,
        # never inserted into the fixture owner's feature list.
        access={'source':PARENT,'subject':A,'kind':'source_access','scope':'native-access',
            'value':{'variant':PARENT,'route':'direct','source_rule':'The table owner grants direct Forbidden Variant access under the Compendium R19 Soul-Collateral entry and Lineage Rules R17'},
            'expires_at':2592000,'readers':[A]}
        state=s.journey_world_fact(jid,state['revision'],access)
        state=s.journey_acquire_source(jid,state['revision'],A,PARENT,{'access_scope':'native-access'})
        assert any(e['kind']=='SOUL_CONTRACT_SOURCE_ACQUIRED' for e in state['events'])
        assert not any(mid.startswith(PARENT+'.feature.') for mid in docs['creditor']['path_and_subpath']['path_feature_record_ids'])
    def cold():return CombatService(ROOT,tmp_path)
    def act(kind,payload=None,actor=A):
        service=cold();before=service.journey_state(jid)
        after=service.journey_act(jid,before['revision'],actor,kind,payload)
        assert cold().journey_state(jid)==after
        return after
    def declare(actor,kind,scope,value,expiry=20000,readers=None):
        return act('declare_fact',{'source':PARENT,'subject':actor,'kind':kind,'scope':scope,'value':value,'expires_at':expiry,'readers':readers if readers is not None else [A,B]},actor)
    return cold,jid,act,declare

def offer(kind='qi',grade='minor'):
    pledge={'kind':kind,'name':'Current Qi','amount':4,'resource':QI,'procedure':'Remove only pledged current points'}
    return {**({'severe_breach_trigger':'Knowingly cross the courtyard gate and abandon the escort'} if grade=='major' else {}),'grade':grade,'parties':[A,B],'consideration':'One day of paid escort','terms':'Do not cross the courtyard gate','duration_seconds':28800 if grade=='minor' else 2592000,'completion':'Escort delivered','collateral':{A:[dict(pledge)],B:[dict(pledge)]},'breach_trigger':'Knowingly cross the courtyard gate','foreclosure_right':'Collect the named collateral after knowing breach','release_conditions':'Mutual release or fulfillment','acceptance':'voluntary','authorized_assignees':[B],'remote':0,'hidden_text_cl':0}

def signed(declare,doc,resisting=0,expiry=20000):
    declare(A,'offer','offer',doc,expiry)
    for p in (A,B):declare(p,'signature',digest(doc),{'knowing':1,'resisting':resisting if p==B else 0,'method':'spoken assent'},expiry)

def ledger(engine):
    return json.loads(next(c.data['contract'] for c in engine.state.actors[A].conditions.values() if c.condition_id==E))

def fight(cold,jid,tmp_path):
    service=cold();state=service.journey_state(jid)
    mid=service.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'})['match_id']
    service=cold();table=TabletopService(service,tmp_path);turn(table,mid,A)
    return service,table,mid

def finish_fight(cold,mid,rounds=20):
    """End the bound fight through the real table so a journey resume is legal."""
    for _ in range(rounds):
        fresh=cold()
        if fresh._load_session(mid).engine.state.terminal_result is not None:return
        table=TabletopService(fresh,fresh.userdata_root)
        menu=table.state(mid)['menu']
        table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],0)
    pytest.fail('Round-capped table did not finish')

def test_paid_minor_ritual_knowing_breach_native_foreclosure_reload_replay(tmp_path,monkeypatch):
    cold,jid,act,declare=game(tmp_path,monkeypatch)
    signed(declare,offer());before=cold().journey_state(jid)['actors'][A]['resources'][QI]
    state=act('soul_contract_create',{'offer_scope':'offer'})
    assert state['seconds']==60 and state['actors'][A]['resources'][QI]==before-2
    cid=next(iter(state['soul_contracts']))
    assert state['soul_contracts'][cid]['claims'][B]==0 and state['actors'][B]['resources'][QI]==30
    declare(B,'breach',cid,{'knowing':1,'severity':'meaningful','term':offer()['breach_trigger']})
    state=act('soul_contract_breach',{'contract_id':cid},B)
    assert state['soul_contracts'][cid]['claims'][B]==1
    with pytest.raises(ValueError,match='already produced'):act('soul_contract_breach',{'contract_id':cid},B)
    service,table,mid=fight(cold,jid,tmp_path)
    prompts=settle(table,mid,candidate(service,mid,'Foreclose Minor Collateral: Qi').candidate_id)
    assert prompts
    loaded=cold()._load_session(mid)
    assert loaded.mechanical.replay()['status']=='PASS'
    assert loaded.engine.state.actors[B].resources[QI]==26 and loaded.engine.state.actors[A].resources[QI]==30
    assert ledger(loaded.engine)['claims'][B]==0

@pytest.mark.parametrize('guard',['resistance','changed_terms','expiry','wrong_subject','unknown_source','no_owner','privacy','refusal_supersedes'])
def test_admission_and_ritual_guards_are_atomic(tmp_path,monkeypatch,guard):
    cold,jid,act,declare=game(tmp_path,monkeypatch,owner=guard!='no_owner');doc=offer()
    if guard in ('wrong_subject','unknown_source','no_owner'):
        payload={'source':'unknown' if guard=='unknown_source' else PARENT,'subject':B if guard=='wrong_subject' else A,'kind':'offer','scope':'offer','value':doc,'expires_at':1000,'readers':[A,B]}
        before=cold().journey_state(jid)
        with pytest.raises(ValueError):act('declare_fact',payload,A)
        assert cold().journey_state(jid)==before
        return
    signed(declare,doc,resisting=int(guard=='resistance'),expiry=60 if guard=='expiry' else 20000)
    if guard=='changed_terms':doc['terms']='Different obligation';declare(A,'offer','offer',doc)
    if guard=='privacy':declare(B,'signature',digest(doc),{'knowing':1,'resisting':0,'method':'written'},readers=[])
    if guard=='refusal_supersedes':declare(B,'signature',digest(doc),{'knowing':1,'resisting':1,'method':'refusal'})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('soul_contract_create',{'offer_scope':'offer'})
    assert cold().journey_state(jid)==before

def test_no_owner_has_no_contract_actions(tmp_path,monkeypatch):
    cold,jid,act,declare=game(tmp_path,monkeypatch,owner=False)
    assert not any(a['parameters'].get('soul_contract_operation') for a in cold().journey_state(jid)['actors'][A]['bundle']['action_catalog'])

def test_parent_variant_cannot_be_compiled_together():
    parent='tianxia.subpath.qi.oath_ledger_cultivator.feature.record_the_promise'
    with pytest.raises(ValueError,match='cannot coexist'):compile_character(sheet([FEATURES[0],parent],cl=6),actor_id=A)


@pytest.mark.parametrize('operation',['Foreclose Cultivation','Call the Contracted Party','Seize the Payment'])
def test_major_native_anchor_and_enforcement(tmp_path,monkeypatch,operation):
    cold,jid,act,declare=game(tmp_path,monkeypatch,cl=14)
    doc=offer('cultivation_points','major')
    if operation=='Call the Contracted Party':
        for rows in doc['collateral'].values():rows[0]['destination']={'x':9,'y':3}
    signed(declare,doc)
    state=act('soul_contract_create',{'offer_scope':'offer'})
    assert state['seconds']==600 and state['actors'][A]['resources'][QI]==24
    cid=next(iter(state['soul_contracts']))
    declare(B,'breach',cid,{'knowing':1,'severity':'severe','term':doc['severe_breach_trigger']})
    state=act('soul_contract_breach',{'contract_id':cid},B)
    assert state['soul_contracts'][cid]['claims'][B]==3
    service,table,mid=fight(cold,jid,tmp_path)
    engine=service._load_session(mid).engine
    anchors=[o for o in engine.state.objects.values() if (o.component or {}).get('soul_contract')==cid]
    assert len(anchors)==2
    assert all(o.current_hp==70 and o.ac==16 for o in anchors)
    assert all(set(o.damage_immunities)>={'POISON','PSYCHIC'} for o in anchors)
    settle(table,mid,candidate(service,mid,operation).candidate_id)
    loaded=cold()._load_session(mid)
    assert loaded.mechanical.replay()['status']=='PASS'
    c=ledger(loaded.engine)
    assert c['claims'][B]==(0 if operation=='Foreclose Cultivation' else 2)
    if operation=='Foreclose Cultivation':
        assert any(x.condition_id=='condition:typed.soul_contract_points_suppressed' and x.data['system']==QI for x in loaded.engine.state.actors[B].conditions.values())
    if operation=='Seize the Payment':
        assert loaded.engine.state.actors[B].resources[QI]==26


def test_committed_contracts_write_only_reload_safe_journal_events(tmp_path,monkeypatch):
    """Review finding 2: a fight this plug-in creates must still load cold on the next session.

    Item Foreclosure emits the possession relocation and the property foreclosure records;
    an event type the reducer/store do not know makes the whole saved fight unloadable.
    """
    from combat.gate3_reducer import GATE2_EVENT_TYPES
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.bi_shou','name':'Bi Shou (Dagger)','quantity':1}]}}
    cold,jid,act,declare=game(tmp_path,monkeypatch,debtor_kit=kit);doc=offer('item')
    item=cold().journey_state(jid)['actors'][B]['bundle']['carrying']['items'][0]
    doc['collateral'][A][0]['kind']='qi'
    doc['collateral'][B][0].update(resource=item['key'],name=item['name'],amount=1)
    signed(declare,doc)
    state=act('soul_contract_create',{'offer_scope':'offer'});cid=next(iter(state['soul_contracts']))
    declare(B,'breach',cid,{'knowing':1,'severity':'meaningful','term':doc['breach_trigger']})
    act('soul_contract_breach',{'contract_id':cid},B)
    service,table,mid=fight(cold,jid,tmp_path/'journal')
    settle(table,mid,candidate(service,mid,'Foreclose Minor Collateral: Item').candidate_id)
    unsupported=sorted({e.event_type for e in cold()._load_session(mid).engine.events}-GATE2_EVENT_TYPES)
    assert not unsupported, unsupported
    loaded=cold()._load_session(mid)
    assert loaded.mechanical.replay()['status']=='PASS'


@pytest.mark.parametrize('kind,button',[('blood','Blood — Psychic'),('movement','Movement'),('voice','Voice'),('item','Item')])
def test_minor_variants_native_expiry_and_replay(tmp_path,monkeypatch,kind,button):
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.bi_shou','name':'Bi Shou (Dagger)','quantity':1}]}}
    cold,jid,act,declare=game(tmp_path,monkeypatch,debtor_kit=kit);doc=offer(kind)
    if kind=='voice':
        declare(B,'secret','hidden-road','The hidden gate opens at dawn',readers=[B])
        recorded=act('soul_contract_record_secret',{'scope':'hidden-road','name':'The hidden road secret'},B)
        secret_id=next(iter(recorded['actors'][B]['soul_contract_secrets']))
        doc['collateral'][A][0]['kind']='qi'
        doc['collateral'][B][0].update(resource=secret_id,name='The hidden road secret')
    if kind=='item':
        state=cold().journey_state(jid)
        doc['collateral'][A][0].update(kind='qi')
        item=state['actors'][B]['bundle']['carrying']['items'][0]
        doc['collateral'][B][0].update(resource=item['key'],name=item['name'],amount=1)
    signed(declare,doc)
    state=act('soul_contract_create',{'offer_scope':'offer'});cid=next(iter(state['soul_contracts']))
    declare(B,'breach',cid,{'knowing':1,'severity':'meaningful','term':doc['breach_trigger']});act('soul_contract_breach',{'contract_id':cid},B)
    service,table,mid=fight(cold,jid,tmp_path)
    settle(table,mid,candidate(service,mid,'Foreclose Minor Collateral: '+button).candidate_id)
    loaded=cold()._load_session(mid);assert loaded.mechanical.replay()['status']=='PASS';target=loaded.engine.state.actors[B]
    assert ledger(loaded.engine)['claims'][B]==0
    if kind=='blood':
        packets=[e for e in loaded.engine.events if e.event_type=='DAMAGE_COMMITTED' and B in e.target_ids]
        assert packets and target.current_hp<60
        damage=sum(e.payload['hp_damage']+e.payload['temporary_hp_absorbed'] for e in packets)
        assert loaded.engine.state.actors[A].temporary_hp==damage//2
    elif kind=='movement':
        assert loaded.engine._effective_speed(target)==0
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,B)
        engine=cold()._load_session(mid).engine
        assert engine._effective_speed(engine.state.actors[B])==30
    elif kind=='voice':
        from combat.speech import silenced
        assert silenced(target)
        turn(table,mid,B)
        engine=cold()._load_session(mid).engine
        assert not silenced(engine.state.actors[B])
        assert any(c.display_name=='Communicate a known secret' for c in engine.legal_candidates())
    elif kind=='item':
        turn(table,mid,B);engine=cold()._load_session(mid).engine
        assert not any('Bi Shou' in c.display_name for c in engine.legal_candidates())


def test_mutual_release_and_whole_contract_claim_cap(tmp_path,monkeypatch):
    cold,jid,act,declare=game(tmp_path,monkeypatch);doc=offer();signed(declare,doc)
    state=act('soul_contract_create',{'offer_scope':'offer'});cid=next(iter(state['soul_contracts']))
    for actor in (A,B,A,B,A,B):
        declare(actor,'breach',cid,{'knowing':1,'severity':'meaningful','term':doc['breach_trigger']})
        state=act('soul_contract_breach',{'contract_id':cid},actor)
    assert sum(state['soul_contracts'][cid]['claims'].values())==4
    declare(A,'release',cid,1)
    with pytest.raises(ValueError):act('soul_contract_release',{'contract_id':cid})
    declare(B,'release',cid,1);state=act('soul_contract_release',{'contract_id':cid})
    assert state['soul_contracts'][cid]['ended']==1 and not any(state['soul_contracts'][cid]['claims'].values())


def test_major_surrender_native_save_and_scene_retry_guard(tmp_path,monkeypatch):
    cold,jid,act,declare=game(tmp_path,monkeypatch,cl=10,owner_dc=1);doc=offer('cultivation_points','major')
    declare(A,'offer','offer',doc)
    declare(A,'signature',digest(doc),{'knowing':1,'resisting':0,'method':'written name'})
    declare(B,'binding_basis',digest(doc),{'basis':'formally_surrendered','source_rule':'Release from custody under the stated escort terms','anti_contract':0})
    state=act('soul_contract_create',{'offer_scope':'offer'})
    assert state['seconds']==600 and state['actors'][A]['resources'][QI]==24 and not state.get('soul_contracts')
    assert any(e['kind']=='SOUL_CONTRACT_BINDING_ROLLED' for e in state['events'])
    with pytest.raises(ValueError,match='cannot be targeted again'):act('soul_contract_create',{'offer_scope':'offer'})


def test_recorded_blueprint_source_chooses_variant_progression(catalog_environment):
    """Native restricted entry provenance; play acceptance still uses installed sheets."""
    from character_builder import CharacterBuilderService
    from non_sphere_authority import NonSphereAuthorityService
    created=CharacterBuilderService(catalog_environment['db']).create_project(
        working_name='Soul Contract source acquisition',concept='A direct-entry forbidden contract cultivator',
        target_cl=18,power_band='standard',source_reference=None,creation_mode='detailed',ability_scores={},
        selections={'path_choice':['tianxia.path.qi_cultivation'],'subpath_choice':[PARENT],'method_choice':['METHOD-001']})
    state=NonSphereAuthorityService(catalog_environment['db']).get_state(created['project_id'])
    assert state['initial_creation_subpath_ids']==[PARENT]
    path=next(p for p in state['paths'] if p['path_id']=='tianxia.path.qi_cultivation')
    assert path['subpath_or_tradition_id']==PARENT
    profile=NonSphereAuthorityService(catalog_environment['db']).subpaths[PARENT]
    assert [p['canonical_id'] for p in profile['feature_progression']]==FEATURES
    assert all('oath_ledger' not in p['canonical_id'] for p in profile['feature_progression'])


def test_native_qi_recovery_and_cold_scene_boundary(tmp_path,monkeypatch):
    cold,jid,act,declare=game(tmp_path,monkeypatch);signed(declare,offer())
    state=act('soul_contract_create',{'offer_scope':'offer'})
    assert state['actors'][A]['resources'][QI]==28
    state=act('soul_contract_short_rest')
    assert state['actors'][A]['resources'][QI]==30 and state['seconds']==3660
    with pytest.raises(ValueError,match='already used'):act('soul_contract_short_rest')
    service=cold();before=service.journey_state(jid)
    state=service.journey_end_scene(jid,before['revision'],'The escort encounter ends at the road gate.')
    assert cold().journey_state(jid)==state
    assert state['scene_id']!=jid
    event=next(e for e in reversed(state['events']) if e['kind']=='SCENE_ENDED')
    receipt=next(r for r in state['fact_consent_admission'] if r['receipt_id']==event['declaration_receipt'])
    assert receipt['source']=='system:journey.scene' and receipt['authority']=='table_owner'


def test_sovereign_native_ritual_anchor_breach_penalty_and_court(tmp_path,monkeypatch):
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.bi_shou','name':'Bi Shou (Dagger)','quantity':1}]}}
    # A Sovereign Anchor is an actual acquired object, never a declared name.
    # Reopen this game with a real carried object on its party.
    cold,jid,act,declare=game(tmp_path/'sovereign',monkeypatch,cl=18,debtor_kit=kit)
    doc=offer('resource','sovereign');doc['duration_seconds']=0
    for pledges in doc['collateral'].values():pledges[0]['amount']=30
    item=cold().journey_state(jid)['actors'][B]['bundle']['carrying']['items'][0]
    doc['anchor']={'holder':B,'item_key':item['key']}
    signed(declare,doc)
    state=act('soul_contract_create',{'offer_scope':'offer'})
    assert state['seconds']==3600 and state['actors'][A]['resources'][QI]==20
    cid=next(iter(state['soul_contracts']))
    declare(B,'breach',cid,{'knowing':1,'severity':'meaningful','term':doc['breach_trigger']})
    state=act('soul_contract_breach',{'contract_id':cid},B)
    assert state['soul_contracts'][cid]['claims'][B]==4
    service,table,mid=fight(cold,jid,tmp_path/'sovereign')
    anchor=next(o for o in service._load_session(mid).engine.state.objects.values() if (o.component or {}).get('soul_contract')==cid)
    assert anchor.ac==18 and anchor.current_hp==216
    settle(table,mid,candidate(service,mid,'Sovereign Breach: Enforce the Pledged Penalty').candidate_id)
    loaded=cold()._load_session(mid)
    assert loaded.mechanical.replay()['status']=='PASS'
    assert not ledger(loaded.engine)['pending_penalties']
    settle(table,mid,candidate(service,mid,'Contract Court').candidate_id)
    loaded=cold()._load_session(mid)
    assert loaded.mechanical.replay()['status']=='PASS'
    assert loaded.engine.state.actors[A].resources[QI]==12
    assert ledger(loaded.engine)['court_used']==1
    assert any(z.active and z.owner_id==A for z in loaded.engine.state.zones.values())


def test_finished_journey_continues_paid_claims_and_clocks_without_reacquisition(tmp_path,monkeypatch):
    cold,jid,act,declare=game(tmp_path,monkeypatch);signed(declare,offer())
    state=act('soul_contract_create',{'offer_scope':'offer'});cid=next(iter(state['soul_contracts']))
    declare(B,'breach',cid,{'knowing':1,'severity':'meaningful','term':offer()['breach_trigger']})
    act('soul_contract_breach',{'contract_id':cid},B)
    before=act('wait',{'seconds':500});act('finish')
    service=cold()
    after=service.create_journey(project_ids=['creditor','debtor'],arena_id='scene',
        positions={A:{'x':3,'y':3},B:{'x':4,'y':3}},base_paces={A:100,B:100})
    assert after['soul_contracts'][cid]['claims'][B]==1
    assert after['soul_contracts'][cid]['expires_at']==before['soul_contracts'][cid]['expires_at']-before['seconds']
    assert after['actors'][A]['resources'][QI]==28
    assert cold().journey_state(after['journey_id'])==after
    service,table,mid=fight(cold,after['journey_id'],tmp_path)
    settle(table,mid,candidate(service,mid,'Foreclose Minor Collateral: Qi').candidate_id)
    assert cold()._load_session(mid).mechanical.replay()['status']=='PASS'



def test_native_known_secret_collection_and_private_communication(tmp_path,monkeypatch):
    cold,jid,act,declare=game(tmp_path,monkeypatch)
    declare(B,'secret','hidden-road','The hidden gate opens at dawn',readers=[B])
    state=act('soul_contract_record_secret',{'scope':'hidden-road','name':'The hidden road secret'},B)
    assert 'hidden-road' not in state['actors'][A].get('soul_contract_secrets',{})
    service,table,mid=fight(cold,jid,tmp_path)
    turn(table,mid,B)
    settle(table,mid,candidate(service,mid,'Communicate a known secret').candidate_id)
    loaded=cold()._load_session(mid)
    assert loaded.mechanical.replay()['status']=='PASS'
    secrets=[json.loads(c.data['secret']) for c in loaded.engine.state.actors[A].conditions.values() if c.condition_id=='condition:typed.soul_contract_secret']
    assert len(secrets)==1 and secrets[0]['value']=='The hidden gate opens at dawn'
    assert secrets[0]['learned_from']==B


@pytest.mark.parametrize('guard',['missing_access','actor_cannot_grant_access','unknown_source','unattained_grade'])
def test_native_source_acquisition_guards_and_attainment(tmp_path,monkeypatch,guard):
    cold,jid,act,declare=game(tmp_path,monkeypatch,cl=18,owner=False,path_level=3)
    access={'source':PARENT,'subject':A,'kind':'source_access','scope':'access',
        'value':{'variant':PARENT,'route':'direct','source_rule':'Native world-owner grant under the printed R17 Direct Entry rule'},
        'expires_at':2592000,'readers':[A]}
    before=cold().journey_state(jid)
    if guard=='actor_cannot_grant_access':
        with pytest.raises(ValueError,match='table-owner'):act('declare_fact',access)
        assert cold().journey_state(jid)==before;return
    if guard not in ('missing_access','unknown_source'):
        before=cold().journey_world_fact(jid,before['revision'],access)
    if guard in ('missing_access','unknown_source'):
        with pytest.raises(ValueError):cold().journey_acquire_source(jid,before['revision'],A,'unknown' if guard=='unknown_source' else PARENT,{'access_scope':'access'})
        assert cold().journey_state(jid)==before;return
    after=cold().journey_acquire_source(jid,before['revision'],A,PARENT,{'access_scope':'access'})
    actions=after['actors'][A]['bundle']['action_catalog']
    assert any(a['parameters'].get('soul_contract_feature')=='sign_in_living_qi' for a in actions)
    assert not any(a['parameters'].get('soul_contract_feature') in ('major_soul_covenant','soul_foreclosure','sovereign_soul_contract') for a in actions)
    with pytest.raises(ValueError,match='already acquired'):
        cold().journey_acquire_source(jid,after['revision'],A,PARENT,{'access_scope':'access'})
    assert cold().journey_state(jid)==after


def test_journey_encounter_settled_takes_the_service_signature(tmp_path,monkeypatch):
    """Review finding 1: CombatService.journey_resume calls
    run_strict('journey_encounter_settled', session, aid, fight.engine, creature).

    Registering the narrower two-argument journey_hearing_view helper on that point raised
    TypeError for EVERY creature on EVERY resume, including characters owning no contract,
    before travel was ever saved. Calling through the real dispatcher is what reproduces it:
    calling settle_contract_journey directly cannot catch a registration/arity fault.
    """
    from combat import ext
    from combat.ext.mgr_reserve_soul_collateral_contract_cultivator_sign_in_living_qi import STATE
    cold,jid,act,declare=game(tmp_path,monkeypatch)
    signed(declare,offer())
    act('soul_contract_create',{'offer_scope':'offer'})
    cid=next(iter(cold().journey_state(jid)['soul_contracts']))
    service,table,mid=fight(cold,jid,tmp_path/'settled-owner')
    engine=service._load_session(mid).engine
    session=cold().journeys.load(jid)
    ext.run_strict('journey_encounter_settled',session,A,engine,engine.state.actors[A])
    assert STATE in session.state and session.state[STATE]
    assert cid in session.state[STATE]


def test_journey_encounter_settled_is_inert_without_any_contract(tmp_path,monkeypatch):
    """Review finding 1: settlement with no contract owner must succeed and change nothing."""
    from combat import ext
    cold,jid,act,declare=game(tmp_path,monkeypatch)
    service,table,mid=fight(cold,jid,tmp_path/'settled-inert')
    engine=service._load_session(mid).engine
    session=cold().journeys.load(jid)
    ext.run_strict('journey_encounter_settled',session,B,engine,engine.state.actors[B])
    assert not session.state.get('soul_contracts')
    assert not session.state['actors'][B].get('soul_contract_effects')


def parent_retained(bundle, old):
    """A failed Conversion must leave the attained parent progression exactly as it was.

    The parent row has no native action provider of its own: the compiler records it in
    diagnostics.skipped, so that is the representation that proves the parent survived.
    """
    skipped=bundle['diagnostics']['skipped']
    assert old.rsplit('.',1)[-1].replace('_',' ').lower() in {row.lower() for row in skipped['reaction']}
    assert not any(a['parameters'].get('typed',{}).get('source','').startswith(PARENT) for a in bundle['action_catalog'])


def test_native_conversion_spends_actual_sessions_and_replaces_only_attained_parent(tmp_path,monkeypatch):
    old='tianxia.subpath.qi.oath_ledger_cultivator.feature.record_the_promise'
    cold,jid,act,declare=game(tmp_path,monkeypatch,cl=18,owner=False,parent_features=[old])
    initial=cold().journey_state(jid)
    access={'source':PARENT,'subject':A,'kind':'source_access','scope':'conversion',
        'value':{'variant':PARENT,'route':'conversion','source_rule':'R17 default Conversion Entry after a legal inheritance awakening'},
        'expires_at':2592000,'readers':[A]}
    state=cold().journey_world_fact(jid,initial['revision'],access)
    with pytest.raises(ValueError,match='one actual Cultivation Session'):
        cold().journey_acquire_source(jid,state['revision'],A,PARENT,{'access_scope':'conversion'})
    assert cold().journey_state(jid)==state
    # Actual sessions, native rolls and failures are retained; no ownership,
    # trigger or completed-training receipt is inserted into the saved state.
    for attempt in range(12):
        now=cold().journey_state(jid)['seconds']
        declare(A,'conversion_environment','calm',1,expiry=now+20000,readers=[A])
        before=cold().journey_state(jid)
        trained=cold().journey_acquire_source(jid,before['revision'],A,PARENT,
            {'access_scope':'conversion','procedure':'train','environment_scope':'calm'})
        assert trained['seconds']==before['seconds']+7200
        result=cold().journey_acquire_source(jid,trained['revision'],A,PARENT,{'access_scope':'conversion'})
        if any(e['kind']=='SOUL_CONTRACT_SOURCE_ACQUIRED' for e in result['events']):break
        assert result['actors'][A]['soul_contract_training'][PARENT]==0
        parent_retained(result['actors'][A]['bundle'],old)
    else:pytest.fail('The deterministic native conversion never succeeded within twelve paid attempts.')
    acquired=json.loads(result['actors'][A]['soul_contract_acquired_sheet'])['path_and_subpath']
    assert FEATURES[0] in acquired['path_feature_record_ids'] and old not in acquired['path_feature_record_ids']
    assert all(f not in acquired['path_feature_record_ids'] for f in FEATURES[1:])
    assert not any(a['parameters'].get('typed',{}).get('source','').startswith('tianxia.subpath.qi.oath_ledger_cultivator.feature.') for a in result['actors'][A]['bundle']['action_catalog'])
    assert cold().journey_state(jid)==result


def test_journey_secret_speech_requires_nearby_recipient(tmp_path, monkeypatch):
    """Journey speech cannot transfer a private secret to an out-of-range recipient."""
    cold, jid, act, declare = game(tmp_path, monkeypatch, positions={
        A: {'x': 3, 'y': 3}, B: {'x': 8, 'y': 3}})
    declare(A, 'secret', 'road', 'The hidden road opens at dawn', readers=[A])
    state = act('soul_contract_record_secret', {'scope': 'road', 'name': 'The hidden road'}, A)
    scope = next(iter(state['actors'][A]['soul_contract_secrets']))
    before = cold().journey_state(jid)
    with pytest.raises(ValueError, match='too far away'):
        act('soul_contract_share_secret', {'scope': scope, 'recipient': B, 'channel': 'speech'}, A)
    assert cold().journey_state(jid) == before
    assert not cold().journey_state(jid)['actors'][B].get('soul_contract_secrets')


def test_contract_breach_direction_reaches_native_perception(tmp_path, monkeypatch):
    """F2R #2: Contract Sight breach-direction facts must reach native perception.

    Before the observer_information hook was wired, for_observer dispatched a
    hook no provider registered, so perception returned no contract facts.
    Now the breach direction is projected to the owner's sight.
    """
    from combat.information_results import for_observer, describe
    cold, jid, act, declare = game(tmp_path, monkeypatch)
    doc = offer()
    signed(declare, doc)
    state = act('soul_contract_create', {'offer_scope': 'offer'})
    cid = next(iter(state['soul_contracts']))
    declare(B, 'breach', cid, {'knowing': 1, 'severity': 'meaningful', 'term': doc['breach_trigger']})
    act('soul_contract_breach', {'contract_id': cid}, B)
    service, table, mid = fight(cold, jid, tmp_path)
    engine = service._load_session(mid).engine
    facts = for_observer(engine, engine.state.actors[A])
    lines = describe(engine, engine.state.actors[A], facts)
    assert any(f.get('kind') == 'breach_direction' and f.get('ability') == 'Contract Sight' for f in facts)
    assert any('breached party' in line for line in lines)


def test_settle_contract_journey_with_active_ledger(tmp_path, monkeypatch):
    """F2R #1: encounter settlement crashes unpacking ledgers() into 3 from 2-tuples.

    journey_resume fires journey_encounter_settled; settle_contract_journey must
    unpack the (holder, condition) pairs ledgers() returns. Exercise the handler
    with a real combat engine that imported an active contract ledger.
    """
    from combat.ext.mgr_reserve_soul_collateral_contract_cultivator_sign_in_living_qi import settle_contract_journey, STATE
    cold, jid, act, declare = game(tmp_path, monkeypatch)
    signed(declare, offer())
    act('soul_contract_create', {'offer_scope': 'offer'})
    service, table, mid = fight(cold, jid, tmp_path)
    engine = service._load_session(mid).engine
    session = cold().journeys.load(jid)
    settle_contract_journey(session, A, engine, engine.state.actors[A])
    assert STATE in session.state and session.state[STATE]


def test_minor_contract_rejects_artifact_pledge(tmp_path, monkeypatch):
    """F2R #4: a Minor Contract cannot pledge an artifact item."""
    kit = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.bi_shou', 'name': 'Bi Shou (Dagger)', 'quantity': 1}]}}
    cold, jid, act, declare = game(tmp_path, monkeypatch, debtor_kit=kit)
    doc = offer('item', 'minor')
    item = cold().journey_state(jid)['actors'][B]['bundle']['carrying']['items'][0]
    doc['collateral'][A][0].update(kind='qi')
    doc['collateral'][B][0].update(resource=item['key'], name=item['name'], amount=1)
    with cold().journeys.locked(jid):
        session = cold().journeys.load(jid)
        session.state['actors'][B]['bundle'].setdefault('acquisition_inventory', {})['artifact:1'] = {
            'inventory_key': item['key'], 'profile': {'facts': {'artifact': 1}}}
        cold().journeys.save(session)
    signed(declare, doc)
    with pytest.raises(ValueError, match='artifact'):
        act('soul_contract_create', {'offer_scope': 'offer'})


def test_minor_voice_action_text_names_target_turn():
    """F2R #3: the Minor Voice rule text now reads the breaching party's next turn."""
    from combat.ext.mgr_reserve_soul_collateral_contract_cultivator_sign_in_living_qi import contract_action_text
    text = contract_action_text('minor_voice')
    assert 'until its next turn starts' in text
    assert 'until your next turn starts' not in text


def test_free_declaration_and_secret_share_pass_the_primary_gate(tmp_path, monkeypatch):
    """Review finding 1: NONE-economy declaration and share actions must be free_primary to be offered."""
    from combat.ext.mgr_reserve_soul_collateral_contract_cultivator_sign_in_living_qi import DECLARATION, SECRET_SHARE_ACTION
    from combat.primary_intents import allows_primary
    cold, jid, act, declare = game(tmp_path, monkeypatch)
    # Both NONE-economy actions install at match start only when their source (contract ledger, known secret) exists.
    declare(B, 'secret', 'hidden-road', 'The hidden gate opens at dawn', readers=[B])
    act('soul_contract_record_secret', {'scope': 'hidden-road', 'name': 'The hidden road secret'}, B)
    signed(declare, offer())
    act('soul_contract_create', {'offer_scope': 'offer'})
    service, table, mid = fight(cold, jid, tmp_path)
    catalog = service._load_session(mid).engine.action_catalog
    for aid in (DECLARATION, SECRET_SHARE_ACTION):
        assert allows_primary(catalog[aid]), aid


def test_pledge_rejects_stamina_for_minor_qi_collateral(tmp_path, monkeypatch):
    """Review finding 3: minor current-Qi collateral must name the Qi pool, not another cultivation pool."""
    cold, jid, act, declare = game(tmp_path, monkeypatch)
    doc = offer()
    doc['collateral'][B][0]['resource'] = 'resource:core.stamina'
    signed(declare, doc)
    with pytest.raises(ValueError, match='Qi|does not own'):
        act('soul_contract_create', {'offer_scope': 'offer'})


def test_pledges_are_independent_per_party():
    """Review finding 4: each party's pledge is its own dict; mutating one never changes the other."""
    doc = offer()
    assert doc['collateral'][A][0] is not doc['collateral'][B][0]
    doc['collateral'][A][0]['amount'] = 1
    assert doc['collateral'][B][0]['amount'] == 4


def test_journey_hearing_view_reports_silenced_and_deafened_from_snapshot():
    """Review finding 5: journey secret speech reads the persisted encounter conditions through the native speech predicates."""
    from combat.speech import silenced
    from combat.typed_executor import cant_hear
    from combat.ext.mgr_reserve_soul_collateral_contract_cultivator_sign_in_living_qi import journey_hearing_view
    from combat.gate2_runtime_models import ConditionInstance
    def row(cid):
        return ConditionInstance(instance_id=cid, condition_id=cid, source_definition_id='test', source_actor_id=A,
            target_id=A, stacks=1, applied_sequence=1, expires_on='UNTIL_REMOVED', data={}).model_dump_json()
    silent = {'encounter_snapshot': {'conditions': {'s': row('condition:typed.silenced')}}}
    deaf = {'encounter_snapshot': {'conditions': {'d': row('condition:typed.deafened')}}}
    plain = {'encounter_snapshot': {'conditions': {}}}
    assert silenced(journey_hearing_view(A, silent))
    assert cant_hear(journey_hearing_view(A, deaf))
    assert not silenced(journey_hearing_view(A, plain)) and not cant_hear(journey_hearing_view(A, plain))


def test_sovereign_penalty_is_a_free_primary_offer():
    """The Sovereign penalty is a NONE-economy action; the compiler's declare_free seam must let it be offered.

    Owner rule: every legal option stays reachable for human and AI seats.
    """
    from combat.ext.mgr_reserve_soul_collateral_contract_cultivator_sign_in_living_qi import compile_contracts, PREFIX, FEATURES
    from combat.primary_intents import allows_primary, declare_free
    info={'owned_ids':{PREFIX+f for f in FEATURES},'numbers':{'cl':18},'short':'regtest','actor_id':B}
    made=compile_contracts(info)
    sealed=declare_free(made)
    penalty=[a for a in sealed if a.parameters.get('soul_contract_operation')=='penalty']
    assert penalty, 'The Sovereign penalty action was not built at CL18.'
    assert allows_primary(penalty[0]), 'The Sovereign penalty must be offered as a free primary action.'


def test_plugin_records_use_non_mutating_rider_with_kind_in_payload():
    """Plug-in combat records must not add reducer-unknown event types (saved journals would fail to reload)."""
    from combat.ext.mgr_reserve_soul_collateral_contract_cultivator_sign_in_living_qi import _contract_event
    from combat.gate3_reducer import NON_MUTATING_EVENT_TYPES, GATE2_EVENT_TYPES
    class Engine:
        def __init__(self):
            self.calls=[]
        def _append_event(self,event_type,source,**kw):
            self.calls.append((event_type,source,kw))
    engine=Engine()
    _contract_event(engine,'SOUL_PROPERTY_FORECLOSED','src',actor_id=A,target_ids=(B,),payload={'quantity':2})
    event_type,source,kw=engine.calls[0]
    assert event_type=='GM_RIDER' and event_type in NON_MUTATING_EVENT_TYPES and event_type in GATE2_EVENT_TYPES
    assert kw['payload']=={'quantity':2,'plugin_event':'SOUL_PROPERTY_FORECLOSED'}
    assert kw['actor_id']==A and kw['target_ids']==(B,)

def test_unknown_source_acquisition_needs_exactly_one_provider_and_leaves_state(tmp_path,monkeypatch):
    cold,jid,act,declare=game(tmp_path,monkeypatch)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='Exactly one source provider'):
        cold().journey_acquire_source(jid,before['revision'],A,'unknown',{'access_scope':'native-access'})
    assert cold().journey_state(jid)==before


def contract_context(engine,owner):
    """The real typed Context the plug-in's own import path builds for one owner."""
    from combat.typed_executor import Context
    from combat.ext.mgr_reserve_soul_collateral_contract_cultivator_sign_in_living_qi import FEATURES,PREFIX
    action=next(a for a in engine.action_catalog.values()
                if a.owner_id==owner.entity_id and a.parameters.get('soul_contract_feature'))
    source=PREFIX+FEATURES[2]
    return Context(engine,owner,action,None,{'source':source,'numbers':{'cl':10,'pb':3,'save_dc':16}},[],None,{},effect_source=source)


def test_timed_contract_effect_keeps_its_duration_through_journey_settle(tmp_path,monkeypatch):
    """Review finding 1 / Ino 2026-10-21: a timed contract effect keeps its real remaining time.

    The old settle wrote six seconds for any timed row without ``rounds``, so a
    one-hour foreclosure ended after six seconds of travel. The row is applied
    through the plug-in's own helper (which now stores the stated seconds), the
    real fight is finished and the journey resumed, and a cold reload must still
    show the printed hour.
    """
    from combat.ext.mgr_reserve_soul_collateral_contract_cultivator_sign_in_living_qi import condition as contract_condition
    cold,jid,act,declare=game(tmp_path,monkeypatch)
    signed(declare,offer());act('soul_contract_create',{'offer_scope':'offer'})
    state=cold().journey_state(jid)
    # One hour is the shared rules standard of 600 rounds; this row states its
    # counted duration as a name and carries no ``rounds`` field. It is applied
    # at match creation so the fight that the journey later settles for real
    # holds it, exactly like any other condition the plug-in applies.
    from combat import ext
    seeded=[]
    def apply_timed(engine):
        if seeded:return
        seeded.append(1)
        contract_condition(contract_context(engine,engine.state.actors[A]),engine.state.actors[A],
            'movement',{},f'START_OF_SLOT_AT:{engine.state.round_number+600}:0',
            'Movement Foreclosure: Speed 0 for one hour')
    monkeypatch.setitem(ext._HOOKS,'match_start',[*ext._HOOKS.get('match_start',[]),apply_timed])
    mid=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},maximum_rounds=1)['match_id']
    engine=cold()._load_session(mid).engine
    applied=next(c for c in engine.state.actors[A].conditions.values()
                 if c.condition_id=='condition:typed.soul_contract_movement')
    assert applied.data['expires_seconds']==3600
    assert applied.data['applied_round']==engine.state.round_number
    finish_fight(cold,mid)
    bound=cold().journey_state(jid)
    resumed=cold().journey_resume(jid,bound['revision'])
    stored=[e for e in resumed['actors'][A]['soul_contract_effects']
            if e['condition']=='condition:typed.soul_contract_movement']
    assert len(stored)==1
    remaining=stored[0]['expires_at']-resumed['seconds']
    assert 3400<remaining<=3600,remaining
    # Commit + reload: the journey on disk keeps the same remaining time.
    loaded=cold().journey_state(jid)
    assert loaded==resumed
    assert next(e for e in loaded['actors'][A]['soul_contract_effects']
                if e['condition']=='condition:typed.soul_contract_movement')['expires_at']-loaded['seconds']==remaining


def test_held_anchor_moves_with_its_holder_and_never_independently(tmp_path,monkeypatch):
    """Review finding 2 / Ino 2026-10-21: a held Anchor follows its holder only.

    CL18 names a real item as the Sovereign Anchor. While another creature holds
    that item, the Anchor object travels with that holder, and the Anchor's own
    party moving must not drag it away (CL10 keeps the Anchor on its party).
    """
    from combat.ext.scoundrel_riders import DISARMED, object_id, possessions
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.bi_shou','name':'Bi Shou (Dagger)','quantity':1}]}}
    cold,jid,act,declare=game(tmp_path/'held-anchor',monkeypatch,cl=18,debtor_kit=kit,
        positions={A:{'x':2,'y':2},B:{'x':6,'y':6}})
    doc=offer('resource','sovereign');doc['duration_seconds']=0
    for pledges in doc['collateral'].values():pledges[0]['amount']=30
    item=cold().journey_state(jid)['actors'][B]['bundle']['carrying']['items'][0]
    doc['anchor']={'holder':B,'item_key':item['key']}
    signed(declare,doc)
    act('soul_contract_create',{'offer_scope':'offer'})
    cid=next(iter(cold().journey_state(jid)['soul_contracts']))
    # The real handover record (the row a Steal or plant writes): the item's own
    # bundle owner is B, and it is now in A's hand, committed with the match.
    from combat import ext
    seeded=[]
    def handover(engine):
        if seeded:return
        seeded.append(1)
        engine._apply_condition(engine.state.actors[B],DISARMED,FEATURES[4],A,expires_on='UNTIL_REMOVED',
            data={'item_key':item['key'],'item_name':item['name'],'owner':B,'held_by':A,'hand':'main'})
    monkeypatch.setitem(ext._HOOKS,'match_start',[*ext._HOOKS.get('match_start',[]),handover])
    service,table,mid=fight(cold,jid,tmp_path/'held-anchor')
    engine=cold()._load_session(mid).engine
    identity=object_id(B,item['key'])
    assert any(str(row.get('object'))==identity for row in possessions(engine,engine.state.actors[A]))
    assert not any(str(row.get('object'))==identity for row in possessions(engine,engine.state.actors[B]))
    anchor=next(o for o in engine.state.objects.values() if (o.component or {}).get('soul_contract')==cid)
    from combat.movement_routes import explicit_candidate,parse_waypoints
    def move(actor,destination):
        current=cold()._load_session(mid).engine
        path=[current.state.actors[actor].position.model_dump(mode='json'),destination]
        route=explicit_candidate(current,actor,parse_waypoints(path))
        menu=table.state(mid)['menu']
        result=table.commit_move_path(mid,route.candidate_id,menu['decision_id'],menu['state_version'],actor,path)
        assert result['status']=='COMMITTED',result
    # The holder's own movement carries the Anchor with it.
    move(A,{'x':3,'y':2})
    loaded=cold()._load_session(mid)
    assert loaded.engine.state.objects[anchor.object_id].position==loaded.engine.state.actors[A].position
    held_at=loaded.engine.state.objects[anchor.object_id].position
    # Its own party moving must not relocate an Anchor its holder is carrying.
    turn(table,mid,B)
    move(B,{'x':6,'y':7})
    loaded=cold()._load_session(mid)
    assert loaded.engine.state.objects[anchor.object_id].position==held_at
    assert loaded.engine.state.actors[B].position!=held_at
