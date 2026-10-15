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


@pytest.fixture(scope='module')
def catalog(): return CanonicalCatalogAuthorityService(ROOT)


def game(tmp_path, monkeypatch, catalog, *, sphere='sect_stewardship', duplicate=False, auto=False):
    for i,pid in enumerate(PIDS):
        doc=sheet([],name='Steward' if i==0 else 'Companion')
        doc['identity']['path_ids']=['tianxia.path.qi_cultivation','tianxia.path.spirit_awakening','tianxia.path.body_refining']
        doc['path_and_subpath']={'path_record_ids':doc['identity']['path_ids']}
        if sphere=='shield':
            from tests.test_auto55_shield import ARMOR, SHIELD_ITEM, DAGGER
            doc['equipment']=[{'starting_kit':{'items':[ARMOR,SHIELD_ITEM,DAGGER] if i==0 else [DAGGER]}}]
        if duplicate and i==0:
            doc['ability_scores_and_statistics']['skills']=[{'skill':'History','bonus':6,'proficient':True,'proficiency':'Proficient'}]
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    def cold():return CombatService(ROOT,tmp_path)
    table=TabletopService(cold(),tmp_path);table.canonical_catalog=catalog
    table.add_advancement(PIDS[0],'sphere','tianxia.sphere.'+sphere)
    if sphere=='shield':table.save_reactions(PIDS[0],{'mode':'ask'})
    # Cold source admission proves ownership comes from the native ledger.
    acquired=cold()._factory_owner_sheet(PIDS[0])
    assert 'tianxia.sphere.'+sphere in acquired['spheres_and_talents']['sphere_record_ids']
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'test':{
        'stable_id':'journey:activities-test','width_squares':10,'height_squares':10,
        'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}})
    state=cold().create_journey(project_ids=PIDS,arena_id='test',positions={A:{'x':2,'y':2},B:{'x':2,'y':3}},
        base_paces={A:1800,B:1800},control_modes={A:'LOCAL_AUTO' if auto else 'MANUAL'})
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
    return world(LEARN,'institution','hall',{'name':'Records Hall','authority':'Hall steward',
        'standing':2,'good_standing':good,'present':present,'ordinary_support':[r.text for r in BASE_REQUESTS]})


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
    act('sect_duty',{'scope':'duty'})
    request(world,'advance-duty',duty='duty',sect_context=0,skill='Survival',ability='WIS')
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
    world(LEARN,'duty_verification','duty',{'witness':'Roster clerk','record':'signed roster #1',
         'approved_rewards':[reward],'detail':'Clerk saw the clean roster and approves this benefit',**({'standing_grade':3} if reward=='standing' else {})})
    state=act('sect_reward',{'reward':reward,'companions':[B] if reward=='supplies' else []})
    assert ledger(state)['duty']['rewarded']==1
    with pytest.raises(ValueError):act('sect_reward',{'reward':reward,'companions':[]})
    if reward=='standing':
        assert ledger(state)['standing_reward']['scene']==jid
        state=cold().journey_end_scene(jid,state['revision'],'The work audience departs')
        assert 'standing_reward' not in ledger(state)
    if reward=='sect_check':
        request(world,'later');state=act('check_start',{'scope':'later','merit':0})
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
    if auto:cold().set_controller_mode(mid,actor_id=B,controller_mode='LOCAL_AUTO')
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
    assert not any(m.source_definition_id=='SHIELD_BASE_ACTIVE_DEFENSE' for m in engine.state.actors[A].modifiers.values())
    assert engine.state.actors[A].armor_class+engine._ac_modifier(engine.state.actors[A])==base
    assert engine.state.actors[A].reaction_available==(payment!='reaction')
    assert engine.state.actors[A].resources['resource:core.martial_focus']==(0 if payment=='focus' else 1)
    assert cold().verify(mid)['status']=='PASS'
    assert cold().replay(mid)['status']=='PASS'
