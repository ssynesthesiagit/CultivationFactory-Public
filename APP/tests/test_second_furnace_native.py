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

OWNER=FACTORY_ACTOR_PREFIX+'f00ace01'
FOE=FACTORY_ACTOR_PREFIX+'f00ace02'
SHOCK='TAL_FORCE_SHOCKWAVE'
MANTLE='TAL_FORCE_FORCE_MANTLE'


def installed(tmp_path,aid,doc):
    folder=tmp_path/'portable_characters'/aid.removeprefix(FACTORY_ACTOR_PREFIX)
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))


def game(tmp_path,monkeypatch,*,cl=18,seed='furnace-native',foe_cl=18,extras=(),ask=False,objects=(),arts=()):
    monkeypatch.setattr('combat.journey.secrets.token_hex',lambda count:hashlib.sha256(seed.encode()).hexdigest()[:count*2])
    for aid,level,dc in ((OWNER,cl,50),(FOE,foe_cl,14)):
        doc=sheet([SHOCK,MANTLE,*extras] if aid==OWNER else [SHOCK,MANTLE],cl=level,dc=dc,name='Furnace owner' if aid==OWNER else 'Hostile cultivator')
        doc['path_and_subpath']={**doc.get('path_and_subpath',{}),'path_record_ids':['tianxia.path.qi_cultivation']}
        doc['ability_scores_and_statistics']['hit_points']['maximum']=500
        if aid==OWNER and arts:doc['immortal_arts']=list(arts)
        installed(tmp_path,aid,doc)
    combat=CombatService(ROOT,tmp_path)
    if ask:TabletopService(combat,tmp_path).save_reactions('f00ace01',{'mode':'ask'})
    saved=combat.tabletop_maps.save({'display_name':'Second Furnace native arena','width_squares':16,'height_squares':16,
        'walls':[],'terrain':[],'objects':list(objects),'starts':{'team1':[[3,6]],'team2':[[4,6]]}})
    arena='battlefield:map.'+saved['map_id']
    state=combat.create_journey(project_ids=['f00ace01','f00ace02'],arena_id=arena,
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


def fight(cold,jid,*,maximum_rounds=30):
    service=cold();state=service.journey_state(jid)
    mid=service.journey_start_combat(jid,state['revision'],{OWNER:'team:a',FOE:'team:b'},maximum_rounds=maximum_rounds)['match_id']
    return mid


def engine(cold,mid):
    return cold()._load_session(mid).engine


def play(cold,tmp_path,mid,label=None,*,target=None,select=None,end=False,destination=None,candidate_id=None):
    answers=[];prompts=[];service=cold();table=TabletopService(service,tmp_path)
    menu=table.state(mid)['menu']
    destinations={c.candidate_id for c in engine(cold,mid).legal_candidates() if c.destination is not None
        and destination is not None and (c.destination.x,c.destination.y)==tuple(destination)} if destination is not None else None
    cid=candidate_id or (menu['end_turn'] if end else next(o['candidate_id'] for g in menu['actions'] if label in g['label']
        for o in g['options'] if (destinations is None or o['candidate_id'] in destinations)
        and (target is None or not o.get('target_ids') or target in o.get('target_ids',[]))))
    for _ in range(35):
        service=cold();table=TabletopService(service,tmp_path);menu=table.state(mid)['menu']
        try:
            result=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers)
        except Exception as exc:
            raise AssertionError({'error':str(exc),'answers':answers,
                'prompts':[{'context':p.get('context'),'reaction':p.get('reaction'),
                    'options':(p.get('choice') or {}).get('options')} for p in prompts]}) from exc
        if result['status']=='COMMITTED':return prompts
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];prompts.append(p);choice=p.get('choice');answer={**p['context'],'selection':'DECLINE'}
        wanted=select(p) if select else None
        if choice:
            options=choice['options']
            row=next((r for r in options if wanted and wanted.lower() in r.get('label','').lower()),None)
            if row is None and 'area_recipients' in p['context']['checkpoint'] and target is not None:
                name=engine(cold,mid).state.actors[target].display_name
                row=next((r for r in options if r['id']==target or r.get('label')==name),None)
                assert row is not None,{'requested_target':target,'options':options}
            if wanted and row is None:raise AssertionError({'wanted':wanted,'context':p['context'],'options':options})
            if row is None and 'PAYMENT_SHORTFALL' in p['context']['checkpoint'] and wanted is None:
                row=next((r for r in options if 'ordinary cost' in r.get('label','').lower()),None)
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
    organ=f.condition(a,f.ORGAN)
    assert organ is not None, {'passives':engine(cold,mid).typed_passive_rows.get(OWNER),
        'native':[(b['actor_id'],bool(b.get('second_furnace_native'))) for b in engine(cold,mid).typed_bundle_documents]}
    assert organ.data['nature']=='A demon seed beside the heart'
    assert a.resource_maximums[f.DEVIL]==4 and a.resources[f.DEVIL]==0
    if cl>=14:
        row=next(r for r in engine(cold,mid).typed_passive_rows[OWNER] if r.get('feature_id')==f.PREFIX+'heart_devil_counterflow')
        assert row['cl']==cl and row['pb']==4
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
        if 'PAYMENT_SHORTFALL' in key:return 'Second Furnace Core: pay 2'
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


@pytest.mark.parametrize('overdraws,exhaustion',[(1,0),(2,1)])
def test_engine_end_counts_actual_subpath_corruption_only(tmp_path,monkeypatch,overdraws,exhaustion):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=18,seed='engine-cost-'+str(overdraws))
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    play(cold,tmp_path,mid,'Demon Emperor',select=lambda p:'ordinary cost' if 'PAYMENT_SHORTFALL' in p['context']['checkpoint'] else None)
    hp=engine(cold,mid).state.actors[OWNER].current_hp
    def emperor(p):
        key=p['context']['checkpoint']
        if 'PAYMENT_SHORTFALL' in key:return 'Emperor'
        if 'engine_end_damage' in key:return 'Necrotic'
        if 'overflow' in key:return 'Temporary Hit Points'
        return None
    # Force Mantle and the Engine both use a Bonus Action. Advance to the
    # next real owner turn before paying for another Bonus Action.
    next_owner(cold,tmp_path,mid)
    for i in range(overdraws):
        if i:next_owner(cold,tmp_path,mid)
        play(cold,tmp_path,mid,'Force Mantle',select=emperor)
    assert engine(cold,mid).state.actors[OWNER].resources[f.CORRUPTION]==overdraws*2
    for _ in range(24):
        if not f.engine_form(engine(cold,mid).state.actors[OWNER]):break
        play(cold,tmp_path,mid,end=True,select=emperor)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    rolls=[x for x in e.events if x.event_type=='DAMAGE_ROLLED' and x.source_definition_id==f.PREFIX+'demon_emperor_s_second_engine']
    assert len(rolls)==1 and rolls[0].payload['expression'].startswith('4d10')
    assert a.current_hp+a.temporary_hp<hp+8
    levels=[c.data['level'] for c in a.conditions.values() if c.condition_id=='condition:typed.exhaustion']
    assert (levels[0] if levels else 0)==exhaustion
    verify(cold,mid)


def test_scene_boundary_consumes_native_owner_input_and_does_not_bank_devil_qi(tmp_path,monkeypatch):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=6,seed='scene-boundary')
    state=cold().journey_state(jid)
    updated=cold().journey_end_scene(jid,state['revision'],'The expedition has reached a safe destination and this scene ends.')
    assert updated['scene_id']!=state.get('scene_id')
    assert updated['actors'][OWNER]['resources'][f.DEVIL]==0
    mid=fight(cold,jid)
    assert engine(cold,mid).state.actors[OWNER].resources[f.DEVIL]==0
    verify(cold,mid)


def test_engine_native_journey_activation_elapsed_deadline_and_combat_binding(tmp_path,monkeypatch):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=18,seed='engine-journey')
    menu=cold().journey_menu(jid,OWNER)
    option=next(o for o in menu['options'] if o['kind']=='furnace_engine')
    state=cold().journey_state(jid)
    state=cold().journey_act(jid,state['revision'],OWNER,option['kind'],option['payload'])
    assert state['actors'][OWNER]['resources'][f.QI]==22
    assert state['actors'][OWNER]['source_states'][f.PARENT]['scene_engine_used']==1
    state=cold().journey_act(jid,state['revision'],OWNER,'wait',{'seconds':30})
    assert state['actors'][OWNER]['source_states'][f.PARENT]['engine']['expires_num']==60
    mid=fight(cold,jid);e=engine(cold,mid);a=e.state.actors[OWNER]
    assert flight_profile(e,a).speed_ft==40 and a.resource_maximums[f.DEVIL]==7
    for _ in range(13):
        if not f.engine_form(engine(cold,mid).state.actors[OWNER]):break
        play(cold,tmp_path,mid,end=True)
    assert not f.engine_form(engine(cold,mid).state.actors[OWNER])
    verify(cold,mid)


def test_engine_expiry_is_not_restarted_by_cold_journey_reload(tmp_path,monkeypatch):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=18,seed='engine-journey-expire')
    state=cold().journey_state(jid)
    state=cold().journey_act(jid,state['revision'],OWNER,'furnace_engine',{})
    state=cold().journey_act(jid,state['revision'],OWNER,'wait',{'seconds':59})
    assert state['actors'][OWNER]['source_states'][f.PARENT].get('engine')
    state=cold().journey_act(jid,state['revision'],OWNER,'wait',{'seconds':1})
    assert not state['actors'][OWNER]['source_states'][f.PARENT].get('engine')
    with pytest.raises(ValueError):cold().journey_act(jid,state['revision'],OWNER,'furnace_engine',{})
    assert cold().journey_state(jid)==state
    mid=fight(cold,jid)
    assert flight_profile(engine(cold,mid),engine(cold,mid).state.actors[OWNER]).speed_ft==0
    verify(cold,mid)
