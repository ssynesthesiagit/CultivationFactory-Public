"""Native acquisition -> elapsed journey intent -> disk reload -> combat replay.

All abilities are acquired through the public Tabletop advancement API. GM facts
use the world-owner path; consent uses the target's own actor command.
"""
import copy
import json
import zipfile
from pathlib import Path

import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
LEARN='SECT_STEWARDSHIP_BASE_LEARNING_SECT_STEWARDSHIP'
PLACE='SECT_STEWARDSHIP_BASE_TAKING_A_PLACE'
PETITION='SECT_STEWARDSHIP_BASE_PETITIONING_THE_HALL'
DUTY='SECT_STEWARDSHIP_BASE_ACCEPTING_A_DUTY'
RECOVER='SECT_STEWARDSHIP_BASE_MERIT_DICE'
SECT='sect_stewardship:journey'
DREAM='DREAMS_BASE_RESTFUL_DREAM'
DREAM_KEY='dreams:restful_dream'
CP='resource:core.qi'
CHECK='journey:noncombat_check'
PENDING='journey:check'
EFFECT='journey:external_effect'
EFFECTS='journey:effects'
from combat.ext.sect_stewardship import MERIT, SECT_KEY, BASE_REQUESTS
from tests.h1_support import ROOT, sheet

PIDS = ['0badc0de-0000-4000-8000-000000000071','0badc0de-0000-4000-8000-000000000072']
A,B = [FACTORY_ACTOR_PREFIX+p for p in PIDS]
ARENA='battlefield:map.journey-activities-test'


@pytest.fixture(scope='module', autouse=True)
def controlling_source_base():
    """Verify the exact controlling printed records in the admitted source tree.

    The exact-prose hashes prove provenance in the private source tree. A public
    test snapshot ships transformed catalogue prose (PUBLIC_TEST_FILES.json at
    its root), so there the fixture verifies that each controlling record is
    present and non-empty instead of hashing prose the snapshot may rewrite.
    """
    import hashlib
    records=json.loads((ROOT/'authority/typed_mechanics/rules_text.json').read_text())
    expected={
        'SHIELD_BASE_ACTIVE_DEFENSE':'3b60b1da497158b81f4691413bbe138f0167c85162ed8272f77f4445c4c937af',
        'DREAMS_BASE_RESTFUL_DREAM':'8c95ba8002ea6c4de0c798921319c70a726cfecf015f22d643d8aff228bdd93d',
        LEARN:'434f5d8a4d5702df93ea64059bf00fe506d2b137ae68e86684b119f4a32fc4f2',
        PLACE:'e9b17c4e63468acd81a8dbed6e5b2d0efa1c4587679ed9f5ed41cabe063c0a90',
        PETITION:'ea515ccfaea57c65017d6fb2c378adb02974de2975dc2d13b8a789cee134475c',
        DUTY:'df2e834ae1e2493db3343c2b0ec6c27df0b4793c5f64891c5cfba0d3de9fb9ca'}
    assert all(type(records.get(key)) is str and records[key].strip() for key in expected)
    if (ROOT.parent/'PUBLIC_TEST_FILES.json').exists():
        return  # transformed public prose is not the private controlling text
    assert {key:hashlib.sha256(records[key].encode()).hexdigest() for key in expected}==expected


@pytest.fixture(scope='module')
def catalog(): return CanonicalCatalogAuthorityService(ROOT)


def game(tmp_path, monkeypatch, catalog, *, sphere='sect_stewardship', duplicate=False, auto=False, primary='Qi', cp=30, definitions=(), party_size=2, wield_shield=True, extra_learners=(), native_tools=(), ask=False):
    pids=[*PIDS,*['0badc0de-0000-4000-8000-'+str(i).zfill(12) for i in range(73,71+party_size)]]
    ids=[FACTORY_ACTOR_PREFIX+pid for pid in pids]
    spots={A:{'x':2,'y':2},B:{'x':2,'y':3}}
    for index,aid in enumerate(ids[2:]):spots[aid]={'x':3+index//2,'y':2+index%2}
    for i,pid in enumerate(pids):
        doc=sheet([],name='Steward' if i==0 else 'Companion',primary=primary)
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=cp
        if definitions:doc['ability_scores_and_statistics']['primary_resource']['definitions']=list(definitions)
        doc['identity']['path_ids']=['tianxia.path.qi_cultivation','tianxia.path.spirit_awakening','tianxia.path.body_refining']
        doc['path_and_subpath']={'path_record_ids':doc['identity']['path_ids']}
        if sphere=='shield':
            from tests.test_auto55_shield import ARMOR, SHIELD_ITEM, DAGGER
            doc['equipment']=[{'starting_kit':{'items':[ARMOR,*([SHIELD_ITEM] if wield_shield else []),DAGGER] if i==0 else [DAGGER]}}]
        if native_tools and i==0:
            doc['ability_scores_and_statistics']['tool_proficiencies']=list(native_tools)
        if duplicate and i==0:
            doc['ability_scores_and_statistics']['skills']=[{'skill':'History','bonus':6,'proficient':True,'proficiency':'Proficient'}]
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    def cold():return CombatService(ROOT,tmp_path)
    table=TabletopService(cold(),tmp_path);table.canonical_catalog=catalog
    table.add_advancement(PIDS[0],'sphere','tianxia.sphere.'+sphere)
    for i in extra_learners:table.add_advancement(pids[i],'sphere','tianxia.sphere.'+sphere)
    if ask:table.save_reactions(PIDS[0],{'mode':'ask'})
    if sphere=='shield':table.save_reactions(PIDS[0],{'mode':'ask'})
    # Cold source admission proves ownership comes from the native ledger.
    acquired=cold()._factory_owner_sheet(PIDS[0])
    assert 'tianxia.sphere.'+sphere in acquired['spheres_and_talents']['sphere_record_ids']
    cold().tabletop_maps.save({'map_id':'journey-activities-test','display_name':'Journey activity tests',
        'width_squares':10,'height_squares':10,'square_size_ft':5,'walls':[],
        'starts':{'team1':[[2,2]],'team2':[[2,3]]}})
    state=cold().create_journey(project_ids=pids,arena_id=ARENA,positions=spots,
        base_paces={aid:1800 for aid in ids},control_modes={A:'LOCAL_AUTO' if auto else 'MANUAL'})
    jid=state['journey_id']
    def act(kind,payload=None,aid=A):
        s=cold().journey_state(jid)
        result=cold().journey_act(jid,s['revision'],aid,kind,payload)
        assert cold().journey_state(jid)==result
        assert cold().journey_verify(jid)['status']=='PASS'
        return result
    def world(source,kind,scope,value,aid=A):
        s=cold().journey_state(jid)
        result=cold().journey_world_fact(jid,s['revision'],{
            'source':source,'subject':aid,'kind':kind,'scope':scope,'value':value,
            'expires_at':s['seconds']+31536000,'readers':[aid]})
        assert cold().journey_state(jid)==result
        assert cold().journey_verify(jid)['status']=='PASS'
        return result
    return cold,jid,act,world


def inst(world, *, present=1,good=1):
    result=world(LEARN,'institution','hall',{'name':'Records Hall','authority':'Hall steward',
        'standing':2,'good_standing':good,'present':present,'ordinary_support':[r.text for r in BASE_REQUESTS]})
    package={'description':'A bowl of plain rice and a safe sleeping mat in the common room',
             'items':[],'entitlements':['meal','safe_sleeping_space']}
    world(LEARN,'support_terms','hall:'+BASE_REQUESTS[0].text,{'request':BASE_REQUESTS[0].text,'standing':2,'ordinary':1,
        'minimum':package,'useful':{**package,'description':'A hot meal and a clean private sleeping corner'},
        'exceptional':{**package,'description':'Prompt discreet hospitality with a generous meal and quiet sleeping room'}})
    world(LEARN,'recovery_context','travel',{'away_from_all_institutions':int(not present),
          'evidence':'The party is outside every institution' if not present else 'The party is at the Records Hall'})
    return result



def request(world,scope,**kw):
    return world(CHECK,'request',scope,{'purpose':'copy the sect ledger','ability':'INT','skill':'History','dc':12,
        'sect_context':1,'role':'','duty':'','institution':'hall','recovery':'',**kw})


def work(act,source,parameters,seconds):
    act('activity_start',{'source':source,'parameters':parameters})
    return act('activity_work',{'seconds':seconds})


def ledger(state,aid=A,key=SECT):return state['actors'][aid]['source_states'][key]


@pytest.mark.parametrize('ability',['INT','WIS','CHA'])
@pytest.mark.parametrize('duplicate',[False,True])
def test_learning_and_role_exact_check_arithmetic(tmp_path,monkeypatch,catalog,ability,duplicate):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,duplicate=duplicate)
    state=act('sect_learn',{'ability':ability,'proficiency':'History','approval':''})
    assert state['actors'][A]['resources'][SECT_KEY]==('INT','WIS','CHA').index(ability)+1
    with pytest.raises(ValueError):act('sect_learn',{'ability':'CHA','proficiency':'Religion','approval':''})
    with pytest.raises(ValueError):act('sect_role',{'role':'Lecture Scribe','duty':'copy records'})
    state=act('long_rest');assert state['seconds']==28800
    act('sect_role',{'role':'Lecture Scribe','duty':'copy records'})
    with pytest.raises(ValueError):act('sect_role',{'role':'Storehouse Aide','duty':'inspect stores'})
    request(world,'role',role='Lecture Scribe')
    state=act('check_start',{'scope':'role','merit':0})
    pending=state['actors'][A]['source_states'][PENDING]
    assert pending['total']-pending['natural']==(8 if duplicate else 6)
    before=state['actors'][A]['resources'][MERIT]
    state=act('check_settle',{'merit':1})
    assert state['actors'][A]['resources'][MERIT]==before-1
    event=state['events'][-1]; assert event['total']>=pending['total']+1
    request(world,'unrelated',sect_context=0)
    state=act('check_start',{'scope':'unrelated','merit':0})
    p=state['actors'][A]['source_states'][PENDING]
    assert p['total']-p['natural']==(6 if duplicate else 6)
    before=copy.deepcopy(state)
    with pytest.raises(ValueError):act('check_settle',{'merit':1})
    assert cold().journey_state(jid)==before
    act('check_settle',{'merit':0})


def test_wrong_owner_custom_tool_and_default_inert(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    state=cold().journey_state(jid)
    for kind,payload in [('sect_learn',{'ability':'INT','proficiency':'History','approval':''}),
                         ('sect_duty',{'scope':'duty'}),('sect_petition',{'institution':'hall','request':BASE_REQUESTS[0].text})]:
        with pytest.raises(ValueError):act(kind,payload,B)
        assert cold().journey_state(jid)==state
    with pytest.raises(ValueError):act('sect_learn',{'ability':'STR','proficiency':'History','approval':''})
    with pytest.raises(ValueError):act('sect_learn',{'ability':'INT','proficiency':'Spirit Lamp Tools','approval':'lamps'})
    world(LEARN,'tool_approval','lamps',{'tool':'Spirit Lamp Tools','duty':'inspect dormitory lamps'})
    state=act('sect_learn',{'ability':'INT','proficiency':'Spirit Lamp Tools','approval':'lamps'})
    assert ledger(state)['training']['proficiency']=='Spirit Lamp Tools'


@pytest.mark.parametrize('reward',['merit','standing','favor','rumor','supplies','sect_check'])
def test_duty_clock_verification_and_all_six_reward_choices(tmp_path,monkeypatch,catalog,reward):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    inst(world)
    world(LEARN,'duty_plan','duty',{'obligation':'copy outer gate roster','institution':'hall',
          'steps':[{'task':'copy the new roster','seconds':120},{'task':'report the roster to clerk','seconds':60}]})
    declared=act('sect_duty',{'scope':'duty'})
    instance=ledger(declared)['duty']['instance_id']
    request(world,'advance-duty',duty=instance,sect_context=0,skill='Survival',ability='WIS')
    state=act('check_start',{'scope':'advance-duty','merit':1})
    assert state['actors'][A]['resources'][MERIT]==3
    act('check_settle',{'merit':0})
    with pytest.raises(ValueError):act('sect_duty',{'scope':'duty'})
    with pytest.raises(ValueError):act('sect_reward',{'reward':reward,'companions':[]})
    act('activity_start',{'source':DUTY,'parameters':{'step':0}})
    state=act('activity_work',{'seconds':119});assert ledger(state)['duty']['completed']==[]
    state=act('wait',{'seconds':1});assert ledger(state)['duty']['completed']==[]
    work(act,DUTY,{'step':0},120)
    work(act,DUTY,{'step':1},60)
    with pytest.raises(ValueError):act('sect_reward',{'reward':reward,'companions':[]})
    # Actual observer verification is independent of the already completed clock.
    world(LEARN,'duty_verification',instance,{'witness':'Roster clerk','record':'signed roster #1',
         'approved_rewards':[reward],'detail':'Clerk saw the clean roster and approves this benefit',**({'standing_grade':3} if reward=='standing' else {}),**({'supplies':{'description':'food and safe common-room sleeping space','items':[],'entitlements':['food','shelter']}} if reward=='supplies' else {})})
    state=act('sect_reward',{'reward':reward,'companions':[B] if reward=='supplies' else []})
    assert ledger(state)['duty']['rewarded']==1
    with pytest.raises(ValueError):act('sect_reward',{'reward':reward,'companions':[]})
    if reward=='standing':
        assert ledger(state)['standing_reward']['scene']==jid
        state=cold().journey_end_scene(jid,state['revision'],'The work audience departs')
        assert 'standing_reward' not in ledger(state)
    if reward=='sect_check':
        act('sect_learn',{'ability':'INT','proficiency':'History','approval':''})
        request(world,'later',check_kind='sect',skill='');state=act('check_start',{'scope':'later','merit':0})
        assert state['actors'][A]['source_states'][PENDING]['mode']=='ADVANTAGE'
        assert not ledger(state)['check_rewards']


@pytest.mark.parametrize('present,good,expected',[(1,1,4),(0,0,1),(1,0,0)])
def test_merit_recovery_requires_real_role_work_and_standing(tmp_path,monkeypatch,catalog,present,good,expected):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    inst(world)
    for _ in range(4):act('sect_petition',{'institution':'hall','request':BASE_REQUESTS[0].text})
    state=act('long_rest');assert state['actors'][A]['resources'][MERIT]==0
    inst(world,present=present,good=good)
    if present and not good:
        with pytest.raises(ValueError):work(act,RECOVER,{'institution':'hall','activity':'check the ledger'},600)
    else:work(act,RECOVER,{'institution':'hall','activity':'check the ledger'},600)
    state=act('long_rest');assert state['actors'][A]['resources'][MERIT]==expected


def test_petition_real_institution_and_bands_no_combat_admission(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('sect_petition',{'institution':'hall','request':BASE_REQUESTS[0].text})
    assert cold().journey_state(jid)==before
    inst(world)
    with pytest.raises(ValueError):act('sect_petition',{'institution':'hall','request':'secret manual'})
    state=act('sect_petition',{'institution':'hall','request':BASE_REQUESTS[0].text})
    receipt=ledger(state)['support'][-1]
    assert 1<=receipt['die']<=4 and receipt['authority']=='Hall steward'
    assert state['actors'][A]['resources'][MERIT]==3
    act('enter_combat')
    with pytest.raises(ValueError):act('sect_petition',{'institution':'hall','request':BASE_REQUESTS[0].text})


def consent(act,cold,jid):
    state=cold().journey_state(jid)
    return act('declare_fact',{'source':DREAM,'subject':B,'kind':'willing','scope':A,'value':1,
        'expires_at':state['seconds']+3600,'readers':[A]},B)


@pytest.mark.parametrize('auto',[False,True])
def test_restful_ritual_rest_optional_effects_and_recovery_check(tmp_path,monkeypatch,catalog,auto):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='dreams',auto=auto)
    state=cold().journey_state(jid);initial=state['actors'][A]['resources'][CP]
    with pytest.raises(ValueError):work(act,DREAM,{'target':B},600)
    consent(act,cold,jid)
    act('activity_start',{'source':DREAM,'parameters':{'target':B}})
    state=act('activity_work',{'seconds':599})
    assert state['actors'][A]['resources'][CP]==initial-1
    assert DREAM_KEY not in state['actors'][B].get('source_states',{})
    state=act('activity_work',{'seconds':1});assert state['seconds']==600
    assert 'pending' in ledger(state,B,DREAM_KEY)
    for iid,category,dc in [('fear','frightened',1),('nightmare','ordinary_nightmare',0),('severe','other',0)]:
        world(EFFECT,'effect',iid,{'id':iid,'label':iid,'category':category,'source':'external:'+iid,
            'save_ability':'WIS' if dc else '', 'save_dc':dc},B)
    state=act('short_rest',aid=B)
    assert state['seconds']==4200 and ledger(state,B,DREAM_KEY)['temporary_hp']==8
    state=act('restful_choice',{'choice':'fear','effect_id':'fear'},B)
    assert 'fear' not in state['actors'][B]['source_states'][EFFECTS]
    with pytest.raises(ValueError):act('restful_choice',{'choice':'minor','effect_id':'severe'},B)
    state=act('restful_choice',{'choice':'minor','effect_id':'nightmare'},B)
    assert 'nightmare' not in state['actors'][B]['source_states'][EFFECTS]
    world(CHECK,'request','recover',{'purpose':'recover from ordinary stress','ability':'WIS','skill':'',
        'dc':10,'sect_context':0,'role':'','duty':'','institution':'','recovery':'stress'},B)
    state=act('check_start',{'scope':'recover','merit':0},B)
    assert state['actors'][B]['source_states'][PENDING]['mode']=='ADVANTAGE'
    state=act('check_settle',{'merit':0},B)
    assert ledger(state,B,DREAM_KEY)['recovery_advantage']==0
    # A second ritual ends on this next rest without granting a second benefit.
    consent(act,cold,jid);work(act,DREAM,{'target':B},600)
    state=act('short_rest',aid=B)
    assert state['events'][-2]['kind']=='RESTFUL_DREAM_LIMIT'
    state=act('long_rest',aid=B)
    consent(act,cold,jid);work(act,DREAM,{'target':B},600)
    state=act('short_rest',aid=B)
    assert ledger(state,B,DREAM_KEY)['benefit_rest']==1


def test_restful_interruption_range_owner_and_combat_cold_replay(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='dreams')
    consent(act,cold,jid)
    with pytest.raises(ValueError):work(act,DREAM,{'target':A},600) # no self consent
    with pytest.raises(ValueError):work(lambda k,p:act(k,p,B),DREAM,{'target':A},600)
    act('activity_start',{'source':DREAM,'parameters':{'target':B}})
    state=act('wait',{'seconds':600})
    assert DREAM_KEY not in state['actors'][B].get('source_states',{})
    work(act,DREAM,{'target':B},600);state=act('short_rest',aid=B)
    result=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},maximum_rounds=1)
    mid=result['match_id'];engine=cold()._load_session(mid).engine
    assert engine.state.actors[B].temporary_hp==8 and engine.state.actors[A].temporary_hp==0
    table=TabletopService(cold(),tmp_path)
    for _ in range(10):
        state=table.state(mid)
        if cold()._load_session(mid).engine.state.terminal_result:break
        assert table.act(mid,state['menu']['end_turn'],state['menu']['decision_id'],state['menu']['state_version'],state['last_sequence'])['status']=='COMMITTED'
        table=TabletopService(cold(),tmp_path)
    engine=cold()._load_session(mid).engine
    assert engine.state.terminal_result
    assert cold().verify(mid)['status']=='PASS'


@pytest.mark.parametrize('payment',['reaction','focus',None])
@pytest.mark.parametrize('auto',[False,True])
def test_active_defense_real_acquisition_after_roll_and_attack_lifetime(tmp_path,monkeypatch,catalog,payment,auto):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='shield')
    state=cold().journey_state(jid)
    result=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},maximum_rounds=2)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    from tests.test_shield_fix_r1 import table_action
    from tests.test_shield_fix_r2 import advance,finish
    advance(table,mid,B)
    if auto:
        cold().set_controller_mode(mid,actor_id=B,controller_mode='LOCAL_AUTO')
        original=table.combat.controller.choose_primary_action
        def dagger_choice(context):
            # This tests off-turn reaction ownership, not AI action ranking.
            # Pin a legal attack while retaining all scored alternatives.
            choice=original(context)
            candidate=next(c for c in context.legal_candidates
                if c.display_name=='Bi Shou (Dagger) attack' and c.target_ids==(A,))
            return choice.model_copy(update={
                'intent':choice.intent.model_copy(update={'candidate_id':candidate.candidate_id,
                    'target_ids':candidate.target_ids,'option_ids':candidate.option_ids,
                    'destination':candidate.destination}),
                'record':choice.record.model_copy(update={'selected_candidate_id':candidate.candidate_id,
                    'selected_option_ids':candidate.option_ids})})
        monkeypatch.setattr(table.combat.controller,'choose_primary_action',dagger_choice)
    base=cold()._load_session(mid).engine.state.actors[A].armor_class
    def choose(p):
        source=p['context']['reaction_source_id']
        if 'fact_admission.shield_readiness' in source:return ['ready']
        if 'active_defense_payment' in source or source=='reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE':
            return [payment] if payment else None
        return None
    prompts=finish(table,mid,'Bi Shou (Dagger) attack',choose,auto=auto,target=None if auto else A)
    engine=cold()._load_session(mid).engine
    windows=[e for e in engine.events if e.event_type=='REACTION_WINDOW_OPENED' and e.source_definition_id=='SHIELD_BASE_ACTIVE_DEFENSE']
    attacks=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==B]
    assert attacks
    if payment:
        assert windows and windows[-1].sequence>attacks[-1].sequence
        assert windows[-1].payload['checkpoint']=='ATTACK_ROLLED_BEFORE_DAMAGE'
        rechecks=[e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.payload.get('checkpoint')=='AFTER_ATTACK_ROLL_DEFENSES']
        assert rechecks and rechecks[-1].payload['ac_bonus']==2
        assert rechecks[-1].payload['new_ac']==attacks[-1].payload['target_ac']+2
        natural=attacks[-1].payload['natural_result']
        total=attacks[-1].payload.get('modified_total',attacks[-1].payload['total'])
        assert rechecks[-1].payload['hit_after_recheck']==(natural!=1 and (natural==20 or total>=rechecks[-1].payload['new_ac']))
    assert not any(m.source_definition_id=='SHIELD_BASE_ACTIVE_DEFENSE' for m in engine.state.actors[A].modifiers.values())
    assert engine.state.actors[A].armor_class+engine._ac_modifier(engine.state.actors[A])==base
    assert engine.state.actors[A].reaction_available==(payment!='reaction')
    assert engine.state.actors[A].resources['resource:core.martial_focus']==(0 if payment=='focus' else 1)
    assert cold().verify(mid)['status']=='PASS'
    assert cold().replay(mid)['status']=='PASS'
    if auto:
        # The off-turn reaction was tested under LOCAL_AUTO above; restore the
        # ordinary manual end-turn menu for the deterministic terminal replay.
        cold().set_controller_mode(mid, actor_id=B, controller_mode='MANUAL')
        table=TabletopService(cold(),tmp_path)
    for _ in range(10):
        if cold()._load_session(mid).engine.state.terminal_result:break
        view=table.state(mid)
        assert table.act(mid,view['menu']['end_turn'],view['menu']['decision_id'],view['menu']['state_version'],view['last_sequence'])['status']=='COMMITTED'
        table=TabletopService(cold(),tmp_path)
    assert cold()._load_session(mid).engine.state.terminal_result
    assert cold().verify(mid)['status']=='PASS' and cold().replay(mid)['status']=='PASS'


@pytest.mark.parametrize('primary,pool',[('Qi','resource:core.qi'),('Stamina','resource:core.stamina'),('Resonance','resource:core.resonance')])
def test_ritual_native_cp_pool_and_insufficient_cost_guard(tmp_path,monkeypatch,catalog,primary,pool):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='dreams',primary=primary,cp=1)
    consent(act,cold,jid)
    state=work(act,DREAM,{'target':B,'pool':pool},600)
    assert state['actors'][A]['resources'][pool]==0
    assert state['actors'][A]['exhaustion']==int(primary=='Stamina')
    before=copy.deepcopy(state)
    with pytest.raises(ValueError):act('activity_start',{'source':DREAM,'parameters':{'target':B,'pool':pool}})
    assert cold().journey_state(jid)==before


def test_petition_ordinary_goods_use_native_builder_inventory_and_combat_replay(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    inst(world)
    catalogue=json.loads((ROOT/'authority/Tianxia_Mundane_Equipment_Catalog_R1.json').read_text())['items']
    tool=next(row for row in catalogue if row['category']=='tool')
    request_text=BASE_REQUESTS[2].text
    package={'description':'The hall lends its ordinary '+tool['name']+' for the declared duty',
             'items':[{'item_id':tool['item_id'],'quantity':1}],'entitlements':['ordinary_duty_tools']}
    world(LEARN,'support_terms','hall:'+request_text,{'request':request_text,'standing':2,'ordinary':1,
          'minimum':package,'useful':package,'exceptional':package})
    state=act('sect_petition',{'institution':'hall','request':request_text})
    granted=ledger(state)['granted_items']
    assert len(granted)==1 and granted[0]['item_id']==tool['item_id']
    result=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},maximum_rounds=1)
    mid=result['match_id'];engine=cold()._load_session(mid).engine
    from combat.carry import carrying_of
    item=next(row for row in carrying_of(engine,A)['items'] if row['key']==granted[0]['key'])
    assert item['name']==tool['name'] and item['quantity']==1
    table=TabletopService(cold(),tmp_path)
    from tests.test_shield_fix_r1 import table_action
    from tests.test_shield_fix_r2 import advance
    advance(table,mid,A)
    assert table_action(table,mid,'Drop '+tool['name'])['status']=='COMMITTED'
    engine=cold()._load_session(mid).engine
    from combat.carry import lost_to_another_hand
    assert lost_to_another_hand(engine.state.actors[A],item['key'])
    assert cold().verify(mid)['status']=='PASS' and cold().replay(mid)['status']=='PASS'
    for _ in range(10):
        if cold()._load_session(mid).engine.state.terminal_result:break
        view=table.state(mid)
        assert table.act(mid,view['menu']['end_turn'],view['menu']['decision_id'],view['menu']['state_version'],view['last_sequence'])['status']=='COMMITTED'
        table=TabletopService(cold(),tmp_path)
    assert cold()._load_session(mid).engine.state.terminal_result
    state=cold().journey_state(jid)
    state=cold().journey_resume(jid,state['revision'])
    assert not ledger(state).get('granted_items')
    assert cold().journey_state(jid)==state
    state=act('wait',{'seconds':1})
    proof=cold().journey_verify(jid)
    assert proof['previous_segments']==1 and proof['bound_matches']==[mid]
    # Starting another native encounter cannot recreate the dropped grant.
    result=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},maximum_rounds=1)
    engine=cold()._load_session(result['match_id']).engine
    assert not any(row['key']==item['key'] for row in carrying_of(engine,A)['items'])
    assert cold().verify(result['match_id'])['status']=='PASS'


def test_learning_persists_into_new_native_sheet_and_journey_without_double_proficiency(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    act('sect_learn',{'ability':'WIS','proficiency':'History','approval':''})
    projected=cold()._factory_owner_sheet(PIDS[0])
    skill=next(r for r in projected['ability_scores_and_statistics']['skills'] if r['skill']=='History')
    assert skill['bonus']==6 and skill['proficiency']=='Proficient'
    act('finish')
    state=cold().create_journey(project_ids=PIDS,arena_id=ARENA,positions={A:{'x':2,'y':2},B:{'x':2,'y':3}},base_paces={A:1800,B:1800})
    new=state['journey_id'];assert new!=jid
    assert state['actors'][A]['resources'][SECT_KEY]==2
    actions=state['actors'][A]['bundle']['action_catalog']
    assert not any(a.get('parameters',{}).get('sect_key_choice') for a in actions)
    assert not any(a.get('parameters',{}).get('typed',{}).get('source')==PETITION for a in actions)
    state=cold().journey_world_fact(new,state['revision'],{'source':CHECK,'subject':A,'kind':'request','scope':'history',
        'value':{'purpose':'read old records','ability':'INT','skill':'History','dc':10,'sect_context':0,'role':'','duty':'','institution':'','recovery':''},
        'expires_at':100,'readers':[A]})
    state=cold().journey_act(new,state['revision'],A,'check_start',{'scope':'history','merit':0})
    pending=state['actors'][A]['source_states'][PENDING]
    assert pending['total']-pending['natural']==6
    assert cold().journey_verify(new)['status']=='PASS'


def test_recovery_does_not_infer_away_from_one_absent_hall_or_block_unknown_rest(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    world(LEARN,'institution','hall',{'name':'Records Hall','authority':'Hall steward','standing':2,
        'good_standing':0,'present':0,'ordinary_support':[]})
    with pytest.raises(ValueError):
        act('activity_start',{'source':RECOVER,'parameters':{'institution':'hall','activity':'maintain travel records'}})
    # Being absent from that hall supplies no global away-from-all-institutions fact.
    world(LEARN,'recovery_context','travel',{'away_from_all_institutions':0,'evidence':'The party is visiting a different institution'})
    with pytest.raises(ValueError):
        act('activity_start',{'source':RECOVER,'parameters':{'institution':'hall','activity':'maintain travel records'}})
    state=act('long_rest')
    assert state['seconds']==28800 and state['actors'][A]['long_rests']==1
    assert not any(e['kind']=='MERIT_RECOVERED' for e in state['events'])



def test_ritual_menu_keeps_every_affordable_actual_pool_and_rejects_zero_pool(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='dreams',cp=1,
        definitions=[{'name':'Resonance','maximum':1}])
    consent(act,cold,jid)
    def pools():
        return {o['payload']['parameters']['pool'] for o in cold().journey_menu(jid,A)['options']
                if o['kind']=='activity_start' and o['payload']['source']==DREAM}
    assert pools()=={'resource:core.qi','resource:core.resonance'}
    work(act,DREAM,{'target':B,'pool':'resource:core.qi'},600)
    assert pools()=={'resource:core.resonance'}
    work(act,DREAM,{'target':B,'pool':'resource:core.resonance'},600)
    assert not pools()



def test_duty_approval_binds_completed_native_instance_not_reused_name(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    inst(world)
    world(LEARN,'duty_plan','handover',{'obligation':'Hand the finished roster to the clerk','institution':'hall',
        'steps':[{'task':'hand over the roster','seconds':1}]})
    declared=act('sect_duty',{'scope':'handover'})
    first=ledger(declared)['duty']['instance_id']
    approval={'witness':'Receiving clerk','record':'receipt #1','approved_rewards':['favor'],'detail':'The clerk received this roster'}
    world(LEARN,'duty_verification',first,approval)
    work(act,DUTY,{'step':0},1)
    with pytest.raises(ValueError):act('sect_reward',{'reward':'favor','companions':[]})
    world(LEARN,'duty_verification',first,approval)
    act('sect_reward',{'reward':'favor','companions':[]})
    act('long_rest')
    declared=act('sect_duty',{'scope':'handover'})
    second=ledger(declared)['duty']['instance_id']
    assert second!=first
    work(act,DUTY,{'step':0},1)
    # Refreshing an old instance's input cannot verify this new performance.
    world(LEARN,'duty_verification',first,{**approval,'record':'old instance receipt'})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('sect_reward',{'reward':'favor','companions':[]})
    assert cold().journey_state(jid)==before
    world(LEARN,'duty_verification',second,{**approval,'record':'receipt #2'})
    state=act('sect_reward',{'reward':'favor','companions':[]})
    assert ledger(state)['duty']['rewarded']==1
    assert cold().journey_verify(jid)['status']=='PASS'



def test_duty_supplies_deliver_to_self_and_five_actual_companions_only(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,party_size=7)
    inst(world)
    world(LEARN,'duty_plan','roster',{'obligation':'Deliver the roster to the clerk','institution':'hall',
        'steps':[{'task':'hand over the roster','seconds':1}]})
    declared=act('sect_duty',{'scope':'roster'})
    instance=ledger(declared)['duty']['instance_id']
    work(act,DUTY,{'step':0},1)
    catalogue=json.loads((ROOT/'authority/Tianxia_Mundane_Equipment_Catalog_R1.json').read_text())['items']
    ration=next(row for row in catalogue if row['category']=='gear' and 'ration' in row['name'].lower())
    package={'description':'Ordinary travel rations for the duty party','items':[{'item_id':ration['item_id'],'quantity':1}],
             'entitlements':['basic_supplies']}
    world(LEARN,'duty_verification',instance,{'witness':'Receiving clerk','record':'party receipt',
        'approved_rewards':['supplies'],'detail':'The clerk received this roster and supplied the party','supplies':package})
    before=cold().journey_state(jid)
    others=[aid for aid in before['actors'] if aid!=A]
    assert len(others)==6
    with pytest.raises(ValueError):act('sect_reward',{'reward':'supplies','companions':others})
    assert cold().journey_state(jid)==before
    selected=others[:5]
    state=act('sect_reward',{'reward':'supplies','companions':selected})
    for aid in [A,*selected]:
        items=ledger(state,aid)['granted_items']
        assert len(items)==1 and items[0]['item_id']==ration['item_id'] and items[0]['quantity']==1
    assert 'granted_items' not in state['actors'][others[-1]].get('source_states',{}).get(SECT,{})
    assert cold().journey_verify(jid)['status']=='PASS'


def test_real_external_effect_can_receive_later_minor_classification(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='dreams')
    world(EFFECT,'effect','stress',{'id':'stress','label':'Unclassified sleep distress','category':'other',
        'source':'external:night-watch','save_ability':'','save_dc':0},B)
    consent(act,cold,jid)
    work(act,DREAM,{'target':B},600)
    with pytest.raises(ValueError):
        world(EFFECT,'classification','missing',{'effect_id':'missing','minor_category':'minor_mental_stress','evidence':'observed'},B)
    world(EFFECT,'classification','stress',{'effect_id':'stress','minor_category':'minor_mental_stress',
        'evidence':'The GM observed a minor sleep disturbance from the interrupted watch'},B)
    state=act('short_rest',aid=B)
    assert ledger(state,B,DREAM_KEY)['minor_effects']==['stress']
    state=act('restful_choice',{'choice':'minor','effect_id':'stress'},B)
    assert 'stress' not in state['actors'][B]['source_states'][EFFECTS]
    assert cold().journey_verify(jid)['status']=='PASS'


def test_corrupt_durable_journey_data_gets_explanation_without_deletion(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    act('sect_learn',{'ability':'INT','proficiency':'History','approval':''})
    service=cold();path=service.journeys.path(jid)
    path.write_text('{')
    with pytest.raises(ValueError,match='cannot be read safely'):
        service._factory_owner_sheet(PIDS[0])
    assert path.read_bytes()==b'{'


def test_admitted_native_intents_are_visible_without_exposing_other_subjects(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    inst(world)
    world(LEARN,'duty_plan','native-menu',{'obligation':'copy the public roster','institution':'hall',
        'steps':[{'task':'copy roster','seconds':60}]})
    request(world,'menu-check')
    menu=cold().journey_menu(jid,A)
    kinds={o['kind'] for o in menu['options']}
    assert {'sect_petition','sect_duty','check_start'}<=kinds
    other=cold().journey_menu(jid,B)
    assert not {'sect_petition','sect_duty','check_start'}.intersection(o['kind'] for o in other['options'])
    check=next(o for o in menu['options'] if o['kind']=='check_start')
    act(check['kind'],check['payload']);act('check_settle',{'merit':0})
    assert not any(o['kind']=='check_start' for o in cold().journey_menu(jid,A)['options'])
    act('sect_duty',{'scope':'native-menu'})
    assert any(o['kind']=='activity_start' and o['payload']['source']==DUTY for o in cold().journey_menu(jid,A)['options'])


def test_persistent_learning_preserves_later_native_expertise(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    act('sect_learn',{'ability':'INT','proficiency':'History','approval':''})
    act('finish')
    path=tmp_path/'portable_characters'/PIDS[0]/'current.zip'
    with zipfile.ZipFile(path) as z:files={name:z.read(name) for name in z.namelist()}
    name='Tianxia_Owner_Character_Sheet_v1.json'
    doc=json.loads(files[name])
    doc['ability_scores_and_statistics']['skills']=[{'skill':'History','bonus':10,'proficiency':'Expertise','proficiency_multiplier':2}]
    files[name]=json.dumps(doc).encode()
    with zipfile.ZipFile(path,'w') as z:
        for name,body in files.items():z.writestr(name,body)
    sourced=cold()._factory_owner_sheet(PIDS[0])
    skill=next(r for r in sourced['ability_scores_and_statistics']['skills'] if r['skill']=='History')
    assert skill['bonus']==10 and skill['proficiency']=='Expertise' and skill['proficiency_multiplier']==2


def test_merit_recovery_honors_good_standing_elsewhere_and_rejects_conflicting_away_facts(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    inst(world,present=1,good=1)
    act('sect_petition',{'institution':'hall','request':BASE_REQUESTS[0].text})
    inst(world,present=0,good=1)
    world(LEARN,'recovery_context','travel',{'away_from_all_institutions':0,'evidence':'We are at a different institution and retain good standing with Records Hall'})
    work(act,RECOVER,{'institution':'hall','activity':'checking a ledger','seconds':600},600)
    state=act('long_rest')
    assert state['actors'][A]['resources'][MERIT]==4
    world(LEARN,'institution','hall',{'name':'Records Hall','authority':'Hall steward','standing':2,
        'good_standing':1,'present':1,'ordinary_support':[r.text for r in BASE_REQUESTS]})
    world(LEARN,'recovery_context','travel',{'away_from_all_institutions':1,'evidence':'Conflicting input claiming we are away from every institution'})
    with pytest.raises(ValueError):act('activity_start',{'source':RECOVER,'parameters':{'institution':'hall','activity':'honor role','seconds':600}})


def test_duty_merit_permission_ends_at_actual_completion_before_reward_collection(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    inst(world)
    world(LEARN,'duty_plan','clock-boundary',{'obligation':'copy the roster','institution':'hall','steps':[{'task':'copy roster','seconds':60}]})
    state=act('sect_duty',{'scope':'clock-boundary'});instance=ledger(state)['duty']['instance_id']
    work(act,DUTY,{'step':0},60)
    request(world,'already-complete',duty=instance,sect_context=0)
    state=act('check_start',{'scope':'already-complete','merit':0})
    assert state['actors'][A]['source_states'][PENDING]['merit_allowed']==0
    before=copy.deepcopy(state)
    with pytest.raises(ValueError):act('check_settle',{'merit':1})
    assert cold().journey_state(jid)==before
    act('check_settle',{'merit':0})


@pytest.mark.parametrize('circumstance',['cannot_present','not_wielding'])
def test_native_shield_presentation_and_wielding_block_defense_before_payment(tmp_path,monkeypatch,catalog,circumstance):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='shield',wield_shield=circumstance!='not_wielding')
    state=cold().journey_state(jid)
    mid=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},maximum_rounds=3)['match_id']
    table=TabletopService(cold(),tmp_path)
    from tests.test_shield_fix_r2 import advance,finish
    if circumstance=='cannot_present':
        advance(table,mid,A)
        finish(table,mid,'Record Shield presentation circumstances',lambda p:['cannot_present'])
    advance(table,mid,B)
    finish(table,mid,'Bi Shou (Dagger) attack',lambda p:['reaction'],target=A)
    engine=cold()._load_session(mid).engine
    assert not any(e.event_type=='REACTION_WINDOW_OPENED' and e.source_definition_id=='SHIELD_BASE_ACTIVE_DEFENSE' for e in engine.events)
    assert engine.state.actors[A].reaction_available
    assert engine.state.actors[A].resources['resource:core.martial_focus']==1
    assert cold().verify(mid)['status']=='PASS' and cold().replay(mid)['status']=='PASS'


def test_restful_once_per_recipient_long_rest_includes_different_native_casters(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='dreams',party_size=3,extra_learners=(2,))
    caster=next(aid for aid in cold().journey_state(jid)['actors'] if aid not in (A,B))
    consent(act,cold,jid);work(act,DREAM,{'target':B},600);act('short_rest',aid=B)
    world(CHECK,'request','spend-recovery',{'purpose':'recover from ordinary stress','ability':'WIS','skill':'',
        'dc':10,'sect_context':0,'role':'','duty':'','institution':'','recovery':'stress'},B)
    act('check_start',{'scope':'spend-recovery','merit':0},B);act('check_settle',{'merit':0},B)
    state=cold().journey_state(jid)
    act('declare_fact',{'source':DREAM,'subject':B,'kind':'willing','scope':caster,'value':1,
        'expires_at':state['seconds']+3600,'readers':[caster]},B)
    work(lambda k,p:act(k,p,caster),DREAM,{'target':B},600)
    state=act('short_rest',aid=B)
    assert ledger(state,B,DREAM_KEY)['recovery_advantage']==0
    assert state['actors'][caster]['resources'][CP]==29
    act('long_rest',aid=B)
    state=cold().journey_state(jid)
    act('declare_fact',{'source':DREAM,'subject':B,'kind':'willing','scope':caster,'value':1,
        'expires_at':state['seconds']+3600,'readers':[caster]},B)
    work(lambda k,p:act(k,p,caster),DREAM,{'target':B},600)
    state=act('short_rest',aid=B)
    assert ledger(state,B,DREAM_KEY)['recovery_advantage']==1
    assert ledger(state,B,DREAM_KEY)['benefit_rest']==1


def test_scene_standing_does_not_appear_as_current_in_a_new_journey(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    inst(world)
    world(LEARN,'duty_plan','scene-duty',{'obligation':'copy roster','institution':'hall','steps':[{'task':'copy roster','seconds':60}]})
    state=act('sect_duty',{'scope':'scene-duty'});instance=ledger(state)['duty']['instance_id']
    work(act,DUTY,{'step':0},60)
    world(LEARN,'duty_verification',instance,{'witness':'Hall clerk','record':'signed roster','approved_rewards':['standing'],
        'detail':'Clerk verifies completed roster and temporarily improves Standing','standing_grade':3})
    act('sect_reward',{'reward':'standing','companions':[]})
    assert cold().journey_menu(jid,A)['properties']['scene_standing']['standing_grade']==3
    act('finish')
    state=cold().create_journey(project_ids=PIDS,arena_id=ARENA,positions={A:{'x':2,'y':2},B:{'x':2,'y':3}},
        base_paces={A:1800,B:1800})
    assert 'scene_standing' not in cold().journey_menu(state['journey_id'],A)['properties']


def test_corrupt_journey_data_does_not_block_an_unowned_native_character(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    registry=cold().journeys.root/'State.json'
    registry.write_text('{broken saved journey')
    sourced=cold()._factory_owner_sheet(PIDS[1])
    assert 'tianxia.sphere.sect_stewardship' not in sourced.get('spheres_and_talents',{}).get('sphere_record_ids',[])
    with pytest.raises(ValueError,match='Restore a known good copy'):
        cold()._factory_owner_sheet(PIDS[0])
    assert registry.read_text()=='{broken saved journey'


def test_taking_a_place_independent_native_long_rest_and_current_role(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    before=cold().journey_state(jid)
    state=cold().journey_act(jid,before['revision'],A,'long_rest',{})
    assert state['seconds']==28800 and state['actors'][A]['long_rests']==1
    assert cold().journey_state(jid)==state
    state=act('sect_role',{'role':'Water Channel Keeper','duty':'maintain the sect irrigation channels'})
    assert ledger(state)['role']=='Water Channel Keeper' and ledger(state)['role_rest']==1
    assert cold().journey_menu(jid,A)['properties']['sect_role']['duty']=='maintain the sect irrigation channels'
    with pytest.raises(ValueError):act('sect_role',{'role':'Lecture Scribe','duty':'copy lecture notes'})
    state=act('long_rest')
    assert 'sect_role' not in cold().journey_menu(jid,A)['properties']
    state=act('sect_role',{'role':'Lecture Scribe','duty':'copy lecture notes'})
    assert ledger(state)['role']=='Lecture Scribe' and ledger(state)['role_rest']==2
