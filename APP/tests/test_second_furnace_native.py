"""Native acquired Second Furnace -> journey -> table intent -> cold replay.

No feature ownership, resource balance, trigger receipt, or plugin callback is
injected. Only ordinary installed character sheets and GM input use test data.
"""
import json
import hashlib
import zipfile
import pytest
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from types import SimpleNamespace
_PARENT='tianxia.subpath.qi.devil_heart_second_furnace'
_FEATURES=('demon_seed_overdraw','devil_qi_augment','second_furnace_core','heart_devil_counterflow','demon_emperor_s_second_engine')
def _condition(actor,key):return next((c for c in actor.conditions.values() if c.condition_id==key),None)
f=SimpleNamespace(PARENT=_PARENT,PREFIX=_PARENT+'.feature.',FEATURES=_FEATURES,
    DEVIL='resource:named.devil_qi',QI='resource:core.qi',CORRUPTION='resource:named.corruption',
    ORGAN='condition:typed.second_furnace_organ',CORE=_PARENT+'.feature.second_furnace_core',
    AUGMENT=_PARENT+'.feature.devil_qi_augment',condition=_condition,
    engine_form=lambda actor:_condition(actor,'condition:typed.second_furnace_engine'))
from combat.flight import profile as flight_profile
from tests.h1_support import ROOT, sheet

OWNER=FACTORY_ACTOR_PREFIX+'furnace-owner'
FOE=FACTORY_ACTOR_PREFIX+'furnace-foe'
SHOCK='TAL_FORCE_SHOCKWAVE'
MANTLE='TAL_FORCE_FORCE_MANTLE'


def installed(tmp_path,aid,doc):
    folder=tmp_path/'portable_characters'/aid.removeprefix(FACTORY_ACTOR_PREFIX)
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))


def game(tmp_path,monkeypatch,*,cl=18,seed='furnace-native',foe_cl=18):
    monkeypatch.setattr('combat.journey.secrets.token_hex',lambda count:hashlib.sha256(seed.encode()).hexdigest()[:count*2])
    for aid,level,dc in ((OWNER,cl,50),(FOE,foe_cl,14)):
        doc=sheet([SHOCK,MANTLE],cl=level,dc=dc,name='Furnace owner' if aid==OWNER else 'Hostile cultivator')
        doc['path_and_subpath']={'path_record_ids':['tianxia.path.qi_cultivation'],
            'paths':[{'path_id':'tianxia.path.qi_cultivation','attainment':level}]}
        doc['ability_scores_and_statistics']['hit_points']['maximum']=500
        installed(tmp_path,aid,doc)
    combat=CombatService(ROOT,tmp_path)
    arena='battlefield:factory_pillar_arena'
    state=combat.create_journey(project_ids=['furnace-owner','furnace-foe'],arena_id=arena,
        positions={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6}},base_paces={OWNER:30,FOE:30})
    jid=state['journey_id']
    def cold():return CombatService(ROOT,tmp_path)
    def declare(kind,value,scope,subject=OWNER,seconds=28800):
        service=cold();state=service.journey_state(jid)
        return service.journey_world_fact(jid,state['revision'],{'source':f.PARENT,'subject':subject,'kind':kind,
            'scope':scope,'value':value,'expires_at':state['seconds']+seconds,'readers':[OWNER,FOE]})
    declare('source_access',{'source_rule':'Native GM award: inherited devil-heart organ','nature':'A demon seed beside the heart'},'initiation')
    state=cold().journey_state(jid)
    state=cold().journey_acquire_source(jid,state['revision'],OWNER,f.PARENT,{'access_scope':'initiation'})
    return cold,jid,declare,state


def fight(cold,jid):
    service=cold();state=service.journey_state(jid)
    mid=service.journey_start_combat(jid,state['revision'],{OWNER:'team:a',FOE:'team:b'},maximum_rounds=30)['match_id']
    return mid


def engine(cold,mid):
    return cold()._load_session(mid).engine


def play(cold,tmp_path,mid,label=None,*,target=None,select=None,end=False):
    answers=[];prompts=[];service=cold();table=TabletopService(service,tmp_path)
    menu=table.state(mid)['menu']
    cid=menu['end_turn'] if end else next(o['candidate_id'] for g in menu['actions'] if label in g['label']
        for o in g['options'] if target is None or not o.get('target_ids') or target in o.get('target_ids',[]))
    for _ in range(35):
        service=cold();table=TabletopService(service,tmp_path);menu=table.state(mid)['menu']
        result=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers)
        if result['status']=='COMMITTED':return prompts
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];prompts.append(p);choice=p.get('choice');answer={**p['context'],'selection':'DECLINE'}
        wanted=select(p) if select else None
        if choice:
            options=choice['options']
            row=next((r for r in options if wanted and wanted.lower() in r.get('label','').lower()),None)
            if row is None and not choice.get('allow_decline'):row=options[0]
            if row:answer.update(selection='USE',option_ids=[row['id']])
        elif wanted=='USE':answer['selection']='USE'
        answers.append(answer)
    raise AssertionError(prompts)


def turn(cold,tmp_path,mid,actor):
    for _ in range(6):
        if engine(cold,mid).state.current_actor_id==actor:return
        play(cold,tmp_path,mid,end=True)
    raise AssertionError('turn did not reach actor')


def next_owner(cold,tmp_path,mid):
    play(cold,tmp_path,mid,end=True);turn(cold,tmp_path,mid,OWNER)


def choose_seed(p):
    key=p['context']['checkpoint']
    if 'PAYMENT_SHORTFALL' in key:return 'Demon Seed Overdraw'
    if 'seed_reinforcement' in key:return 'Temporary Hit Points'
    return None


def verify(cold,mid):
    service=cold()
    result=service.verify(mid)
    assert result['status']=='PASS',result
    assert service.replay(mid)['status']=='PASS'
    return result


@pytest.mark.parametrize('cl,count',[(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_acquisition_publishes_only_attained_progression_and_real_organ(tmp_path,monkeypatch,cl,count):
    cold,jid,declare,state=game(tmp_path,monkeypatch,cl=cl,seed='acquire-'+str(cl))
    actor=cold().journey_state(jid)['actors'][OWNER]
    bundle=actor['bundle'];source=actor['source_states'][f.PARENT]
    learned=json.loads(source['acquired_sheet'])['path_and_subpath']['source_granted_subpath_feature_record_ids']
    assert learned==[f.PREFIX+n for n in f.FEATURES[:count]]
    assert bundle['second_furnace_native']['access_receipt']==source['access_receipt']
    assert actor['resources'][f.DEVIL]==0
    mid=fight(cold,jid);a=engine(cold,mid).state.actors[OWNER]
    assert f.condition(a,f.ORGAN).data['nature']=='A demon seed beside the heart'
    assert a.resource_maximums[f.DEVIL]==4 and a.resources[f.DEVIL]==0
    verify(cold,mid)


def test_seed_is_opt_in_prepaid_and_native_gains_survive_reload(tmp_path,monkeypatch):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=3);mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    before=engine(cold,mid).state.actors[OWNER].resources[f.QI]
    prompts=play(cold,tmp_path,mid,'Force Mantle',select=choose_seed)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert a.resources[f.QI]==before # three Qi reduced by PB 4
    assert a.resources[f.CORRUPTION]==1 and a.resources[f.DEVIL]==2
    assert a.temporary_hp==4
    assert any('Demon Seed Overdraw' in str(p) for p in prompts)
    payment=next(x for x in e.events if x.event_type=='ALTERNATIVE_PAYMENT_COMMITTED')
    assert payment.payload['resources_paid'][f.QI]==0
    assert any(x.event_type=='ACTIVATION_PAYMENT_SETTLED' for x in e.events)
    verify(cold,mid)


def test_ordinary_payment_declines_overdraw_without_corruption(tmp_path,monkeypatch):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=3,seed='ordinary');mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    play(cold,tmp_path,mid,'Force Mantle',select=lambda p:'ordinary cost' if 'PAYMENT_SHORTFALL' in p['context']['checkpoint'] else None)
    a=engine(cold,mid).state.actors[OWNER]
    assert a.resources[f.QI]==27 and a.resources[f.DEVIL]==0 and a.resources[f.CORRUPTION]==0
    verify(cold,mid)


def test_augment_uses_native_earned_devil_qi_once_and_target_turn_expiry(tmp_path,monkeypatch):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=6,seed='augment');mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    play(cold,tmp_path,mid,'Force Mantle',select=choose_seed);next_owner(cold,tmp_path,mid)
    def select(p):
        key=p['context']['checkpoint']
        if 'PAYMENT_SHORTFALL' in key:return 'ordinary cost'
        if key.endswith(':offer'):return 'add damage'
        if key.endswith(':damage_type'):return 'Psychic'
        if key.endswith(':rider'):return 'Speed'
        return None
    prompts=play(cold,tmp_path,mid,'Shockwave',target=FOE,select=select)
    e=engine(cold,mid);a=e.state.actors[OWNER];foe=e.state.actors[FOE]
    assert a.resources[f.DEVIL]==1
    rolls=[x for x in e.events if x.event_type=='DAMAGE_ROLLED' and str(x.payload.get('display_source_id','')).startswith(f.AUGMENT)]
    assert len(rolls)==1 and str(rolls[0].payload['expression']).startswith('2d8')
    assert any(m.target_field=='speed_ft' and m.value==-10 for m in foe.modifiers.values())
    play(cold,tmp_path,mid,end=True);turn(cold,tmp_path,mid,FOE)
    assert not any(m.target_field=='speed_ft' and m.value==-10 for m in engine(cold,mid).state.actors[FOE].modifiers.values())
    verify(cold,mid)


def test_core_split_is_native_payment_not_refund_and_motion_is_saved(tmp_path,monkeypatch):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=10,seed='split');mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    play(cold,tmp_path,mid,'Force Mantle',select=choose_seed);next_owner(cold,tmp_path,mid)
    def select(p):
        key=p['context']['checkpoint']
        if 'PAYMENT_SHORTFALL' in key:return 'cover 2 Qi'
        if 'furnace_motion' in key:return 'Temporary Hit Points'
        return None
    play(cold,tmp_path,mid,'Shockwave',target=FOE,select=select)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert a.resources[f.DEVIL]==0 and a.resources[f.QI]==30
    assert any(x.event_type=='ALTERNATIVE_PAYMENT_COMMITTED' and x.source_definition_id==f.CORE and x.payload['costs'][f.DEVIL]==2 for x in e.events)
    assert a.temporary_hp==4
    verify(cold,mid)


def test_engine_opens_without_end_damage_and_free_augment_needs_no_devil_qi(tmp_path,monkeypatch):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=18,seed='engine');mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    before=engine(cold,mid).state.actors[OWNER].current_hp
    play(cold,tmp_path,mid,'Demon Emperor',select=lambda p:'ordinary cost' if 'PAYMENT_SHORTFALL' in p['context']['checkpoint'] else None)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert a.current_hp==before and a.resources[f.QI]==22 and a.resource_maximums[f.DEVIL]==7
    assert flight_profile(e,a).speed_ft==40 and flight_profile(e,a).hover
    assert f.engine_form(a)
    def select(p):
        key=p['context']['checkpoint']
        if 'PAYMENT_SHORTFALL' in key:return 'ordinary cost'
        if key.endswith(':offer'):return 'add damage'
        if key.endswith(':damage_type'):return 'Force'
        if key.endswith(':rider'):return 'Temporary Hit Points'
        return None
    play(cold,tmp_path,mid,'Shockwave',target=FOE,select=select)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert a.resources[f.DEVIL]==0 and a.temporary_hp==8
    assert not any(x.event_type=='RESOURCE_SPENT' and x.payload.get('resource_id')==f.DEVIL for x in e.events)
    verify(cold,mid)


def test_missing_access_wrong_subject_and_duplicate_acquisition_are_rejected(tmp_path,monkeypatch):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=3,seed='guards');state=cold().journey_state(jid)
    with pytest.raises(ValueError):cold().journey_acquire_source(jid,state['revision'],FOE,f.PARENT,{'access_scope':'initiation'})
    with pytest.raises(ValueError):cold().journey_acquire_source(jid,state['revision'],OWNER,f.PARENT,{'access_scope':'initiation'})
    assert cold().journey_state(jid)==state


def test_counterflow_uses_earned_qi_and_native_failed_save_and_reroll(tmp_path,monkeypatch):
    rewritten=backlashes=0
    for i in range(6):
        cold,jid,_,_=game(tmp_path/str(i),monkeypatch,cl=14,foe_cl=14,seed='counterflow-'+str(i))
        mid=fight(cold,jid);turn(cold,tmp_path/str(i),mid,OWNER)
        play(cold,tmp_path/str(i),mid,'Force Mantle',select=choose_seed)
        play(cold,tmp_path/str(i),mid,end=True);turn(cold,tmp_path/str(i),mid,FOE)
        def select(p):
            if p['context']['checkpoint']=='D20_REROLL_SAVE':return 'USE'
            if 'counterflow_damage_type' in p['context']['checkpoint']:return 'Necrotic'
            return None
        play(cold,tmp_path/str(i),mid,'Shockwave',target=OWNER,select=select)
        e=engine(cold,mid)
        rows=[x for x in e.events if x.event_type=='D20_REWRITTEN' and x.source_definition_id==f.PREFIX+'heart_devil_counterflow']
        if rows:
            rewritten+=1
            assert e.state.actors[OWNER].resources[f.DEVIL]==0
            assert not e.state.actors[OWNER].reaction_available
            result=rows[-1].payload['result']
            assert result['modifier']>=6
            if result['total']>=14:
                backlashes+=1
                assert any(x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==f.PREFIX+'heart_devil_counterflow' for x in e.events)
        verify(cold,mid)
    assert rewritten and backlashes


def test_consecration_comes_from_native_source_declaration_and_not_a_name(tmp_path,monkeypatch):
    cold,jid,declare,state=game(tmp_path,monkeypatch,cl=6,seed='consecrated')
    declare('furnace_environment',{'source_rule':'Native GM ward: consecrated sanctuary','source_cl':6,'subject':FOE,'consecrated':1},'ward')
    state=cold().journey_state(jid)
    cold().journey_act(jid,state['revision'],OWNER,'furnace_environment',{'scope':'ward'})
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    play(cold,tmp_path,mid,'Force Mantle',select=choose_seed);next_owner(cold,tmp_path,mid)
    def select(p):
        key=p['context']['checkpoint']
        if 'PAYMENT_SHORTFALL' in key:return 'ordinary cost'
        if key.endswith(':offer'):return 'add damage'
        if key.endswith(':damage_type'):return 'Force'
        if key.endswith(':rider'):return 'Reactions'
        if key.endswith(':consecrated'):return 'Make a Constitution save'
        return None
    prompts=play(cold,tmp_path,mid,'Shockwave',target=FOE,select=select)
    saves=[p for p in prompts if p['context']['checkpoint'].endswith(':consecrated')]
    assert saves and saves[0]['context']['reactor_id']==FOE
    verify(cold,mid)


def test_engine_slot_clock_ends_and_restores_capacity_without_unearned_damage(tmp_path,monkeypatch):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=18,seed='engine-expiry');mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    play(cold,tmp_path,mid,'Demon Emperor',select=lambda p:'ordinary cost' if 'PAYMENT_SHORTFALL' in p['context']['checkpoint'] else None)
    hp=engine(cold,mid).state.actors[OWNER].current_hp
    for _ in range(23):
        if not f.engine_form(engine(cold,mid).state.actors[OWNER]):break
        play(cold,tmp_path,mid,end=True)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert not f.engine_form(a) and a.resource_maximums[f.DEVIL]==4
    assert a.current_hp==hp and a.resources[f.DEVIL]<=4
    assert flight_profile(e,a).speed_ft==0
    verify(cold,mid)


@pytest.mark.parametrize('protected,remaining',[('artifact',1),('legendary',1),('secret_law',1),('immortal_art',1),
    ('permanent',1),('indefinite',1),('strategic_travel',1),('world_scale',1),('expensive_materials',1),('sacrifice',1)])
def test_source_scoped_printed_minimum_cost_is_paid_without_reducing_other_prices(tmp_path,monkeypatch,protected,remaining):
    cold,jid,declare,state=game(tmp_path,monkeypatch,cl=3,seed='floor-'+protected)
    actor=state['actors'][OWNER]
    action=next(a for a in actor['bundle']['action_catalog'] if a['display_name']=='Force Mantle')
    declare('cost_profile',{'source_rule':action['source_definition_id'],
        'quotation':'Native GM supplied Source Rule: this activation is '+protected+'.',
        'classification':{protected:1}},'printed-price')
    state=cold().journey_state(jid)
    cold().journey_act(jid,state['revision'],OWNER,'furnace_cost_profile',{'scope':'printed-price'})
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    play(cold,tmp_path,mid,'Force Mantle',select=choose_seed)
    a=engine(cold,mid).state.actors[OWNER]
    assert a.resources[f.QI]==30-remaining and a.resources[f.CORRUPTION]==1
    verify(cold,mid)


def test_hostile_expenditure_requires_native_qualifying_hostility_declaration(tmp_path,monkeypatch):
    for declared in (False,True):
        root=tmp_path/str(declared)
        cold,jid,declare,state=game(root,monkeypatch,cl=6,foe_cl=6,seed='hostile-'+str(declared))
        if declared:
            declare('furnace_environment',{'source_rule':'Native GM: actual non-farmed hostile cultivator',
                'source_cl':6,'subject':FOE,'beneficiary':OWNER,'qualifying_hostility':1},'hostility')
            state=cold().journey_state(jid)
            cold().journey_act(jid,state['revision'],OWNER,'furnace_environment',{'scope':'hostility'})
        mid=fight(cold,jid);turn(cold,root,mid,FOE)
        play(cold,root,mid,'Force Mantle')
        a=engine(cold,mid).state.actors[OWNER]
        assert a.resources[f.DEVIL]==int(declared)
        verify(cold,mid)


def test_native_anti_daemonic_interruption_has_no_overdraw_rewards_and_pays_unreduced_cost(tmp_path,monkeypatch):
    cold,jid,declare,state=game(tmp_path,monkeypatch,cl=3,seed='interruption')
    declare('furnace_environment',{'source_rule':'Native GM anti-daemonic suppression on activation',
        'source_cl':3,'subject':OWNER,'anti_daemonic':1,'second_suppressed':1,'interrupt_next_activation':1},'anti-daemonic')
    state=cold().journey_state(jid)
    cold().journey_act(jid,state['revision'],OWNER,'furnace_environment',{'scope':'anti-daemonic'})
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    play(cold,tmp_path,mid,'Force Mantle',select=choose_seed)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert a.resources[f.QI]==27 and a.resources[f.CORRUPTION]==0 and a.resources[f.DEVIL]==0
    assert any(x.event_type=='ACTIVATION_PAYMENT_SETTLED' and x.payload.get('interrupted')==1 for x in e.events)
    verify(cold,mid)
