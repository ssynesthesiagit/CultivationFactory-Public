"""Thousand-Fold native acquisition, committed choices and cold mechanical replay."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from app.api import create_app
from combat.ext import steel_forms
from combat.gate5_service import CombatService
import zipfile
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests import test_riders_c7 as c7

PARENT='tianxia.subpath.body.thousand_fold_steel_body'
FEATURES=dict(zip((3,6,10,14,18),('body_forged_in_three_forms','quench_the_impact','folded_edge_hidden_spine','ten_thousand_reforgings','body_beyond_the_hammer')))
OWNER='actor:factory.11111111-1111-4111-8111-111111111111'
FOE='actor:factory.22222222-2222-4222-8222-222222222222'
EVIDENCE=Path(__import__('os').environ['STEEL_EVIDENCE_DIR']) if __import__('os').environ.get('STEEL_EVIDENCE_DIR') else None


def test_anatomical_labels_hide_internal_target_keys():
    from combat.ext.source_consequences import anatomical_label
    assert anatomical_label('limb','hand:left') == 'left hand'
    assert anatomical_label('limb','hand:right') == 'right hand'


def test_custom_extension_choice_is_a_discovery_boundary():
    from types import SimpleNamespace
    from combat.reaction_menu import ReactionMenuProbe,MenuBoundary
    context=SimpleNamespace(checkpoint='custom:mode:1',reactor_id=OWNER,
        reaction_source_id='choice:contract.mode',extension_choice=SimpleNamespace(allow_decline=True))
    with pytest.raises(MenuBoundary):ReactionMenuProbe(context).answer(context)


def acquire(environment,monkeypatch,cl):
    cache=environment.setdefault('_steel_native_acquisitions',{})
    if cl in cache:return copy.deepcopy(cache[cl])
    monkeypatch.setenv('TIANXIA_BROWSER_EXECUTABLE','/var/tmp/auto-audit/NO_BROWSER_ALLOWED')
    app=create_app(environment['settings']);builder=app.state.character_builder
    project=builder.create_project(working_name='Steel disciple',concept='Restricted scripture Body Refiner',
        source_reference=None,target_cl=cl,power_band='rival/boss',creation_mode='detailed',
        generation_route='ai_bootstrap',ability_scores={},autogen_seed='STEEL-NATIVE',
        selections={'path_choice':['tianxia.path.body_refining'],'subpath_choice':[PARENT]},method_planning_mode='AUTO')
    builder.commit_normal_first_cycle_catalog_choices(project['project_id'])
    run=app.state.character_creation.start(project['project_id'],execution_mode='STANDARD_API',
        idempotency_key='steel-native-'+str(cl),controller_route='DETERMINISTIC_CREATIVE_CONTROLLER')
    assert run['status'] in ('READY_FOR_REVIEW','NEEDS_REVIEW'),run
    if run['status']=='NEEDS_REVIEW':
        assert [b['code'] for b in run['blockers']]==['COMMAND6_CHARACTER_GM_CONSUMER_FAILED'],run['blockers']
        harness=run['blockers'][0]['details']['consumer_report']['harness_run']
        assert harness['skipped'] is True and harness['exit_code'] is None
        assert 'Explicit TIANXIA_BROWSER_EXECUTABLE is missing' in harness['stderr']
    doc=app.state.character_creation.load_candidate_gm_context(run['run_id'])['owner_character_sheet']
    earned=[r for r in doc['path_and_subpath']['earned_feature_occurrences'] if r.get('parent_record_id')==PARENT]
    assert {r['feature_id'] for r in earned}=={PARENT+'.feature.'+n for level,n in FEATURES.items() if level<=cl}
    assert all(r['source_backed'] and r['source_packet_ids'] and r['acquisition_event_hash'] and r['attainment_event_hash'] for r in earned)
    if EVIDENCE is not None:
        EVIDENCE.mkdir(parents=True,exist_ok=True)
    runtime={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
        'combat/ext/steel_forms.py','combat/ext/integrated_weapons.py','combat/ext/source_consequences.py',
        'combat/ext/journey_activities.py','tests/test_mgr_t14_thousand_fold_steel_body_floor58.py')}
    runtime_key=hashlib.sha256(json.dumps(runtime,sort_keys=True).encode()).hexdigest()[:16]
    if EVIDENCE is not None:
        (EVIDENCE/('runtime-'+runtime_key+'.json')).write_text(json.dumps(runtime,sort_keys=True))
        (EVIDENCE/f'acquisition-cl{cl}-{hashlib.sha256(json.dumps(doc,sort_keys=True).encode()).hexdigest()[:16]}.json').write_text(json.dumps({'document':doc,'run_id':run['run_id'],'blockers':run.get('blockers',[])},sort_keys=True))
    cache[cl]=copy.deepcopy(doc)
    return doc


def loaded(service,mid):
    session=CombatService(service.source_root,service.userdata_root)._load_session(mid)
    replay=session.mechanical.replay()
    assert replay['status']=='PASS',replay
    engine=session.engine
    state=engine.state.model_dump(mode='json')
    digest=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest()
    if EVIDENCE is not None:
        (EVIDENCE/('reload-'+digest[:16]+'.json')).write_text(json.dumps({'state':state,'replay':replay},sort_keys=True))
    return engine


@pytest.mark.parametrize('cl,count',[(3,1),(6,1),(10,1),(14,2),(18,3)])
def test_native_acquired_progression_and_form_state(catalog_environment,monkeypatch,tmp_path,cl,count):
    doc=acquire(catalog_environment,monkeypatch,cl)
    service,table,mid=game(tmp_path,doc,seed='STEEL-'+str(cl))
    advance(service,table,mid,picks={'choice:needle.tempering_forms':['edge','spine'][:count]})
    engine=loaded(service,mid);actor=engine.state.actors[OWNER]
    scene=[c for c in actor.conditions.values() if c.condition_id=='condition:typed.body_scene' and c.data.get('source')==PARENT]
    assert len(scene)==1
    assert scene[0].data['source_cl']==cl
    # No printed integration procedure has completed: no implicit first weapon.
    assert not any('integrated_con' in str(c.source_definition_id) for c in engine.legal_candidates())
    assert len(steel_forms.forms(actor))==count


def test_native_beyond_keeps_reforged_edge_value(catalog_environment,monkeypatch,tmp_path):
    doc=acquire(catalog_environment,monkeypatch,18)
    service,table,mid=game(tmp_path,doc,seed='STEEL-EDGE')
    advance(service,table,mid)
    engine=loaded(service,mid);pb=engine.state.actors[OWNER].proficiency_bonus
    strike=strike_name(engine,OWNER)
    play(service,table,mid,strike,{'choice:needle.folded_edge':None,'choice:needle.body_beyond_the_hammer':None,
        'choice:needle.reed_form_move':None},target=FOE)
    engine=loaded(service,mid)
    packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==OWNER]
    assert any(e.payload.get('hp_damage')==2*pb for e in packets)


def test_native_declining_form_choice_retains_previous_legal_pair(catalog_environment,monkeypatch,tmp_path):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,14),seed='STEEL-RETAIN')
    picks={'choice:needle.tempering_forms':['spine','reed']}
    advance(service,table,mid,picks=picks)
    play(service,table,mid,'Dodge',picks)
    assert steel_forms.forms(loaded(service,mid).state.actors[OWNER])==['spine','reed']
    state=table.state(mid);settle(table,mid,state['menu']['end_turn'],picks)
    advance(service,table,mid,picks={'choice:needle.tempering_forms':None})
    assert steel_forms.forms(loaded(service,mid).state.actors[OWNER])==['spine','reed']


def test_shared_integration_keeps_an_independent_choose_limit(catalog_environment,monkeypatch,tmp_path):
    """Supplemental compiler-contract control; native family proof is separate."""
    from combat.ext.integrated_weapons import constitution_typed,integrated_bases,chosen_items
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,3),seed='STEEL-INTEGRATION-UNION')
    engine=loaded(service,mid)
    actions=[a for a in engine.action_catalog.values() if a.owner_id==OWNER]
    # Two independent generic provider declarations, one runtime-selected,
    # one using the historical choose-one contract. No extra source is granted
    # to the actor, and this pure contract test makes no whole-row claim.
    info={'actions':actions,'owned_ids':[steel_forms.TEMPER,'contract:choose_one'],
        'mechanics':{steel_forms.TEMPER:{'effects':[{'type':'path_passive','kind':'integrated_weapon','group':'melee','choose':1,'selection_required':True}]},
            'contract:choose_one':{'effects':[{'type':'path_passive','kind':'integrated_weapon','group':'melee','choose':1}]}},
        'numbers':{'attack_bonus':5},'mods':{'CON':2}}
    bases=integrated_bases(info);chosen=chosen_items(actions,'melee',1)
    assert len(bases)>=2
    for base in bases:
        typed=base.parameters['typed'];variant=constitution_typed(info,typed)
        selected=str(typed['source']).rsplit('.',1)[-1] in chosen
        assert (steel_forms.TEMPER in variant.get('integration_sources',())) is not selected


def settle(table,mid,cid,picks=None):
    answers=[];prompts=[]
    for _ in range(40):
        state=table.state(mid); menu=state['menu']
        result=table.act(mid,cid,menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
        if result['status']=='COMMITTED':
            pass
            return prompts
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];prompts.append(p);rid=p['context']['reaction_source_id']
        options=[o['id'] for o in p.get('choice',{}).get('options',[])]
        minimum=int(p.get('choice',{}).get('minimum',p['context'].get('minimum',1)))
        value=(picks or {}).get(rid,options[:minimum] if options and rid.startswith('choice:') else None)
        answer={**p['context'],'selection':'USE' if value is not None else 'DECLINE'}
        if value is not None and options:answer['option_ids']=value if isinstance(value,list) else [value]
        answers.append(answer)
    raise AssertionError('Unsettled native choices')


def play(service,table,mid,name,picks=None,target=None):
    candidates=service._load_session(mid).engine.legal_candidates()
    found=[c for c in candidates if (c.display_name==name or c.display_name.startswith(name+' at ')) and (not target or target in c.target_ids)]
    assert found,(name,[c.display_name for c in candidates])
    c=found[0]
    return settle(table,mid,c.candidate_id,picks)


def advance(service,table,mid,aid=OWNER,picks=None):
    for _ in range(30):
        state=table.state(mid);menu=state['menu']
        if menu.get('actor_id')==aid and not menu.get('fight_setup') and menu.get('end_turn'):return
        if menu.get('end_turn'):cid=menu['end_turn']
        else:
            cid=next(o['candidate_id'] for group in menu['actions'] for o in group['options'])
        settle(table,mid,cid,picks)
    raise AssertionError('No owner turn')


def installed(root,aid,doc):
    folder=root/'portable_characters'/aid.removeprefix('actor:factory.')
    folder.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))

def game(root,doc,seed='BODY-MODES',ask=True,modes=None,foe_doc=None,positions=None,extra_foe_doc=None,maximum_rounds=20,objects=(),foe_hp=1000):
    installed(root,OWNER,doc)
    foe=copy.deepcopy(foe_doc) if foe_doc is not None else c7.sheet([],cl=18,name='Sparring opponent')
    foe['ability_scores_and_statistics']['hit_points']['maximum']=foe_hp
    installed(root,FOE,foe)
    extra='actor:factory.33333333-3333-4333-8333-333333333333'
    if extra_foe_doc is not None:installed(root,extra,extra_foe_doc)
    service=CombatService(ROOT,root)
    if ask:TabletopService(service,root).save_reactions('11111111-1111-4111-8111-111111111111',{'mode':'ask'})
    saved=service.tabletop_maps.save({'display_name':'Body modes native yard','width_squares':14,'height_squares':14,
        'walls':[],'objects':list(objects),'starts':positions or {'team1':[[3,6]],'team2':[[4,6]]}})
    mid=service.create_factory_match(project_ids=['11111111-1111-4111-8111-111111111111'],opponent_actor_ids=[FOE]+([extra] if extra_foe_doc is not None else []),
        control_modes=modes or {OWNER:'MANUAL',FOE:'MANUAL',**({extra:'MANUAL'} if extra_foe_doc is not None else {})},arena_id='battlefield:map.'+saved['map_id'],match_seed=seed,maximum_rounds=maximum_rounds)['match_id']
    return service,TabletopService(service,root),mid

def strike_name(engine,aid):
    return next(a.display_name for a in engine.action_catalog.values() if a.owner_id==aid and a.economy.value=='ACTION'
                and any(e.get('type')=='attack' and e.get('attack_kind')=='unarmed' for e in (a.parameters.get('typed') or {}).get('effects',())))


def record_source_result(table,service,mid,*,subject=OWNER,operation='destroy_limb',kind='limb',key='hand:left',authority='ordinary',source_cl=1,explicit=0,apply=True,nonce='one',nature='physical'):
    from combat.combat_world_facts import clock
    engine=loaded(service,mid)
    payload={'source':'system:source_consequences','subject':subject,'kind':'apply_result','scope':operation+':'+key,
        'value':{'source_rule':'Table-owner external Source Rule: '+('conceptually erase' if nature=='conceptual_erasure' else operation.replace('_',' '))+' the identified structure; resolve other consequences separately.',
            'source_cl':source_cl,'explicit_source_cl':explicit,'authority':authority,'source_actor_id':FOE,
            'operation':operation,'target_kind':kind,'target_key':key,'reconstructable':1,'result_nature':nature},
        'expires_at':int(clock(engine))+60,'readers':[OWNER,FOE]}
    result=table.world_fact(mid,engine.state.state_version,payload,'source-'+operation+'-'+subject+'-'+key+'-'+nonce)
    assert result['status']=='COMMITTED'
    # Recording external facts is not applying the result.
    after=loaded(service,mid)
    assert after.state.actors[subject].current_hp==engine.state.actors[subject].current_hp
    if not apply:return after
    play(service,table,mid,'Apply a recorded source consequence')
    return loaded(service,mid)


@pytest.mark.parametrize('cl,protected',[(14,False),(18,True)])
def test_native_anatomy_source_application_and_wrong_tier(catalog_environment,monkeypatch,tmp_path,cl,protected):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,cl),seed='STEEL-ANATOMY-'+str(cl))
    advance(service,table,mid)
    before=loaded(service,mid).state.actors[OWNER].current_hp
    engine=record_source_result(table,service,mid)
    actor=engine.state.actors[OWNER]
    injury=any(c.condition_id=='condition:source.anatomy_loss' for c in actor.conditions.values())
    assert injury is not protected
    from combat.ext.hand_occupancy import hand_parts
    assert ('hand:left' in hand_parts(engine,actor)) is protected
    assert 'hand:right' in hand_parts(engine,actor)
    rolls=[r for r in engine.rolls if r.reason=='DAMAGE:'+PARENT+'.feature.body_beyond_the_hammer']
    assert bool(rolls) is protected
    if protected:
        assert before-actor.current_hp==rolls[-1].total
        assert rolls[-1].expression.startswith('4d10')
        assert not any(e.event_type=='RESOURCE_SPENT' and e.source_definition_id==PARENT+'.feature.quench_the_impact' for e in engine.events)


def test_native_source_protection_keeps_authority_exceptions(catalog_environment,monkeypatch,tmp_path):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,18),seed='STEEL-AUTHORITY')
    advance(service,table,mid)
    engine=record_source_result(table,service,mid,operation='rust',kind='body',key='body')
    assert not any(c.condition_id=='condition:source.implement_damage' for c in engine.state.actors[OWNER].conditions.values())
    for operation in ('break','rust','warp','corrode','dull'):
        engine=record_source_result(table,service,mid,operation=operation,kind='limb',key='hand:left')
        assert not any(c.condition_id=='condition:source.implement_damage' for c in engine.state.actors[OWNER].conditions.values())
    engine=record_source_result(table,service,mid,operation='warp',kind='body',key='body',authority='artifact')
    assert any(c.condition_id=='condition:source.implement_damage' and c.data['operation']=='warp'
        for c in engine.state.actors[OWNER].conditions.values())
    # The same generic producer remains ordinary for a creature without the family.
    engine=record_source_result(table,service,mid,subject=FOE,operation='corrode',kind='body',key='body')
    assert any(c.condition_id=='condition:source.implement_damage' for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('nature,kept',[('physical',True),('conceptual_erasure',False)])
def test_native_anatomical_result_is_distinct_from_source_authority(catalog_environment,monkeypatch,tmp_path,nature,kept):
    from combat.ext.hand_occupancy import hand_parts
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,18),seed='STEEL-RESULT-'+nature)
    advance(service,table,mid)
    engine=record_source_result(table,service,mid,authority='secret',source_cl=18,explicit=1,nature=nature)
    assert ('hand:left' in hand_parts(engine,engine.state.actors[OWNER])) is kept
    assert bool([e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and e.payload.get('display_source_id')==PARENT+'.feature.body_beyond_the_hammer']) is kept


def test_native_source_request_uses_current_authority_after_supersession(catalog_environment,monkeypatch,tmp_path):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,18),seed='STEEL-SOURCE-SUPERSESSION')
    advance(service,table,mid)
    record_source_result(table,service,mid,operation='rust',kind='body',key='body',apply=False,nonce='prior')
    record_source_result(table,service,mid,operation='rust',kind='body',key='body',authority='artifact',apply=False,nonce='new')
    prompts=play(service,table,mid,'Apply a recorded source consequence')
    assert not any(p['context']['reaction_source_id']=='choice:needle.source_consequence' for p in prompts)
    engine=loaded(service,mid)
    assert any(c.condition_id=='condition:source.implement_damage' and c.data['operation']=='rust'
               for c in engine.state.actors[OWNER].conditions.values())


def journey(service,arena_id=None):
    if arena_id is None:
        maps=service.tabletop_maps.arenas()
        arena_id=next(k for k,v in maps.items() if v['display_name']=='Body modes native yard')
    return service.create_journey(project_ids=[OWNER.removeprefix('actor:factory.'),FOE.removeprefix('actor:factory.')],
        arena_id=arena_id,positions={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6}},
        base_paces={OWNER:12000,FOE:12000})


def journey_act(service,state,kind,payload):
    result=service.journey_act(state['journey_id'],state['revision'],OWNER,kind,payload)
    return CombatService(service.source_root,service.userdata_root).journey_state(state['journey_id'])


def ready_weapon(service,table,mid,weapon):
    """Real Draw/Stow transactions; tempering itself grants no extra hand."""
    advance(service,table,mid)
    for _ in range(10):
        engine=loaded(service,mid)
        stow=next((c for c in engine.legal_candidates()
            if ((engine.action_catalog.get(c.source_definition_id).parameters if engine.action_catalog.get(c.source_definition_id) else {}).get('equipment_grip') or {}).get('held')==0
            and ((engine.action_catalog.get(c.source_definition_id).parameters if engine.action_catalog.get(c.source_definition_id) else {}).get('equipment_grip') or {}).get('weapon')!=weapon),None)
        if stow is None:break
        settle(table,mid,stow.candidate_id)
    engine=loaded(service,mid)
    if not steel_forms.tempered_weapon(engine,engine.state.actors[OWNER]):
        draw=next(c for c in engine.legal_candidates()
            if ((engine.action_catalog.get(c.source_definition_id).parameters if engine.action_catalog.get(c.source_definition_id) else {}).get('equipment_grip') or {}).get('held')==1
            and ((engine.action_catalog.get(c.source_definition_id).parameters if engine.action_catalog.get(c.source_definition_id) else {}).get('equipment_grip') or {}).get('weapon')==weapon)
        settle(table,mid,draw.candidate_id)
    return loaded(service,mid)


def test_native_temper_work_is_required_and_survives_combat_entry(catalog_environment,monkeypatch,tmp_path):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,18),seed='STEEL-TEMPER')
    state=journey(service)
    # Native acquired inventory, cold journey state, public tool-object contract.
    from combat.ext.journey_activities import available_tool_objects
    session=service.journeys.load(state['journey_id'])
    armor=next(r['key'] for r in session.state['actors'][OWNER]['bundle']['carrying']['items'] if r['kind']=='armor')
    task={'operation':'repair','owner':OWNER,'item':armor,'context':'downtime'}
    assert available_tool_objects(session,OWNER,task)==['smithing']
    assert not available_tool_objects(session,OWNER,{**task,'owner':FOE})
    assert not available_tool_objects(session,OWNER,{**task,'operation':'craft'})
    assert not available_tool_objects(session,FOE,{**task,'owner':FOE})
    native_weapon=next(r for r in session.state['actors'][OWNER]['bundle']['carrying']['items'] if r.get('weapon_action'))
    assert available_tool_objects(session,OWNER,{**task,'item':native_weapon['key']})==['smithing']
    natural=next(a['source_definition_id'] for a in session.state['actors'][OWNER]['bundle']['action_catalog']
        if any(e.get('type')=='attack' and e.get('attack_kind')=='unarmed' for e in (a.get('parameters',{}).get('typed') or {}).get('effects',())))
    assert not available_tool_objects(session,OWNER,{**task,'item':natural})
    options=service.journey_menu(state['journey_id'],OWNER)['options']
    temper=next(o for o in options if o['id'].startswith('steel:temper:'))
    weapon=temper['payload']['parameters']['weapon']
    state=journey_act(service,state,temper['kind'],temper['payload'])
    row=state['actors'][OWNER]['source_states']['journey:activity']
    assert row['tool_objects']==['smithing'] and row['required_seconds']==600
    state=journey_act(service,state,'activity_work',{'seconds':599})
    assert 'tempered_weapon' not in state['actors'][OWNER]['source_states'].get(PARENT,{})
    state=journey_act(service,state,'activity_work',{'seconds':1})
    assert state['actors'][OWNER]['source_states'][PARENT]['tempered_weapon']==weapon
    result=service.journey_start_combat(state['journey_id'],state['revision'],{OWNER:'team:a',FOE:'team:b'})
    mid=result['match_id'];engine=ready_weapon(service,table,mid,weapon)
    assert steel_forms.tempered_weapon(engine,engine.state.actors[OWNER])==weapon
    from combat.weapon_delivery import attack_materials
    action=engine.action_catalog[weapon]
    assert attack_materials(engine,engine.state.actors[OWNER],action,'weapon')==('adamantine',)
    advance(service,table,mid)
    engine=loaded(service,mid)
    variants=[c for c in engine.legal_candidates() if 'integrated_con' in str(c.source_definition_id)]
    assert variants and all(c.source_definition_id.split('#')[0]==weapon for c in variants)
    attack=next(c for c in variants if FOE in c.target_ids)
    settle(table,mid,attack.candidate_id,{'choice:needle.folded_edge':None,
        'choice:needle.body_beyond_the_hammer':None,'choice:needle.reed_form_move':None})
    engine=loaded(service,mid)
    assert any(e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER
               and e.source_definition_id==attack.source_definition_id for e in engine.events)
    held=engine.action_catalog[attack.source_definition_id].parameters['typed']['weapon']
    con=next(a['modifier'] for a in acquire(catalog_environment,monkeypatch,18)['ability_scores_and_statistics']['abilities'] if a['ability']=='CON')
    assert held['ability']=='CON' and held['damage']['modifier']==con
    stow=next(c for c in engine.legal_candidates()
              if ((engine.action_catalog.get(c.source_definition_id).parameters if engine.action_catalog.get(c.source_definition_id) else {}).get('equipment_grip') or {}).get('weapon')==weapon
              and ((engine.action_catalog.get(c.source_definition_id).parameters if engine.action_catalog.get(c.source_definition_id) else {}).get('equipment_grip') or {}).get('held')==0)
    settle(table,mid,stow.candidate_id)
    engine=loaded(service,mid)
    assert not steel_forms.tempered_weapon(engine,engine.state.actors[OWNER])
    assert not attack_materials(engine,engine.state.actors[OWNER],engine.action_catalog[weapon],'weapon')
    assert not any('integrated_con' in c.source_definition_id for c in engine.legal_candidates())


@pytest.mark.parametrize('pair',[['edge','spine'],['edge','reed'],['spine','reed']])
def test_native_quench_can_retain_or_replace_both_forms(catalog_environment,monkeypatch,tmp_path,pair):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,14),seed='STEEL-QUENCH-'+','.join(pair))
    picks={'choice:needle.tempering_forms':['edge','spine'],'choice:needle.quench_the_impact':['spine'],
        'choice:needle.quench_forms':['_'.join(pair)],'choice:needle.reed_form_move':None}
    advance(service,table,mid,FOE,picks=picks)
    for _ in range(5):
        engine=loaded(service,mid)
        play(service,table,mid,strike_name(engine,FOE),picks,target=OWNER)
        engine=loaded(service,mid)
        reactions=[e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==PARENT+'.feature.quench_the_impact']
        if reactions:break
        advance(service,table,mid,OWNER,picks=picks)
        # Let the round pass through a real end-turn intent.
        state=table.state(mid);settle(table,mid,state['menu']['end_turn'],picks)
        advance(service,table,mid,FOE,picks=picks)
    assert reactions
    assert steel_forms.forms(engine.state.actors[OWNER])==pair
    paid=[e for e in engine.events if e.event_type=='RESOURCE_SPENT' and e.source_definition_id==PARENT+'.feature.quench_the_impact']
    assert len(paid)==1 and paid[0].payload['amount']==1


@pytest.mark.parametrize('finish',['attack','expire'])
def test_native_edge_quench_charge_uses_the_next_melee_attack_or_expires(catalog_environment,monkeypatch,tmp_path,finish):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,6),seed='STEEL-NATIVE-CHARGE-'+finish)
    picks={'choice:needle.tempering_forms':['edge'],'choice:needle.quench_the_impact':['edge'],
        'choice:needle.reed_form_move':None}
    advance(service,table,mid,FOE,picks=picks)
    for _ in range(10):
        engine=loaded(service,mid)
        play(service,table,mid,strike_name(engine,FOE),picks,target=OWNER)
        engine=loaded(service,mid)
        if '_round_edge_quench_charge' in engine.state.actors[OWNER].turn_flags:break
        advance(service,table,mid,OWNER,picks=picks)
        state=table.state(mid);settle(table,mid,state['menu']['end_turn'],picks)
        advance(service,table,mid,FOE,picks=picks)
    assert '_round_edge_quench_charge' in engine.state.actors[OWNER].turn_flags
    assert engine.state.actors[OWNER].turn_flags['_round_edge_quench_charge']['source_cl']==6
    advance(service,table,mid,OWNER,picks=picks)
    engine=loaded(service,mid);event_start=len(engine.events);roll_start=len(engine.rolls)
    if finish=='expire':
        state=table.state(mid);settle(table,mid,state['menu']['end_turn'],picks)
    else:
        play(service,table,mid,strike_name(engine,OWNER),picks,target=FOE)
    engine=loaded(service,mid)
    assert '_round_edge_quench_charge' not in engine.state.actors[OWNER].turn_flags
    bonus=[e for e in engine.events[event_start:] if e.event_type=='DAMAGE_ROLLED' and e.payload.get('display_source_id')==PARENT+'.feature.quench_the_impact']
    if finish=='expire':assert not bonus
    else:
        first=next(e for e in engine.events[event_start:] if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER)
        assert len(bonus)==int(bool(first.payload['provisional_hit']))
        if bonus:assert bonus[0].payload.get('display_source_id')==PARENT+'.feature.quench_the_impact'
    assert len([e for e in engine.events if e.event_type=='RESOURCE_SPENT'
        and e.source_definition_id==PARENT+'.feature.quench_the_impact'])==1


# Explicit dependencies of the real catalog source-inventory hash. The loader
# assembles these filenames dynamically; CI must retain the real authority.
NATIVE_SOURCE_DEPENDENCIES = (
    'catalog_authority/cat3/source/INSIGHT_TYPE_MAPPING.json',
    'catalog_authority/cat3/source/INSIGHT_GROUPING_INVENTORY.json',
    'catalog_authority/cat3/source/SUPERSESSION_AND_COLLISION_LEDGER.json',
    'catalog_authority/cat3/source/SPHERE_BASE_ABILITY_MATRIX.csv',
    'catalog_authority/cat3/source/Tianxia_Central_Cultivation_Insights_AI_Reference_R5_Legacy_Restored.json',
)


def test_native_suppression_retains_a_player_chosen_legal_form(catalog_environment,monkeypatch,tmp_path):
    from combat.combat_world_facts import clock
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,18),seed='STEEL-SUPPRESSION')
    advance(service,table,mid)
    engine=loaded(service,mid)
    result=table.world_fact(mid,engine.state.state_version,{'source':'system:body_modes_scene_resources',
        'subject':OWNER,'kind':'cultivation_suppression','scope':'suppression-source',
        'value':{'source_rule':'External equal-authority Realm suppression to effective Body CL13.',
            'source_cl':18,'system':'body','effective_cl':13},'expires_at':int(clock(engine))+60,'readers':[OWNER,FOE]},'steel-suppression')
    assert result['status']=='COMMITTED'
    engine=loaded(service,mid)
    assert len(steel_forms.active_forms(engine,engine.state.actors[OWNER]))==1
    play(service,table,mid,'Dodge',{'choice:needle.steel_suppressed_forms':['reed']})
    engine=loaded(service,mid)
    assert steel_forms.active_forms(engine,engine.state.actors[OWNER])==['reed']
    assert set(steel_forms.forms(engine.state.actors[OWNER]))=={'edge','spine','reed'}


def test_native_quench_keeps_the_other_dormant_form_during_suppression(catalog_environment,monkeypatch,tmp_path):
    from combat.combat_world_facts import clock
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,14),seed='STEEL-DORMANT-QUENCH')
    picks={'choice:needle.steel_suppressed_forms':['edge'],
        'choice:needle.quench_the_impact':['reed'],'choice:needle.reed_quench_move':None}
    advance(service,table,mid,picks=picks)
    def suppress(level,nonce):
        engine=loaded(service,mid)
        result=table.world_fact(mid,engine.state.state_version,{'source':'system:body_modes_scene_resources',
            'subject':OWNER,'kind':'cultivation_suppression','scope':'steel-dormancy',
            'value':{'source_rule':'A sourced Realm seal sets effective Body CL to '+str(level)+'.',
                'source_cl':18,'system':'body','effective_cl':level},'expires_at':int(clock(engine))+60,'readers':[OWNER,FOE]},nonce)
        assert result['status']=='COMMITTED'
    suppress(13,'steel-seal-13')
    play(service,table,mid,'Dodge',picks)
    advance(service,table,mid,FOE,picks=picks)
    engine=loaded(service,mid)
    play(service,table,mid,strike_name(engine,FOE),picks,target=OWNER)
    engine=loaded(service,mid)
    assert any(e.event_type=='REACTION_RESOLVED' and e.source_definition_id==PARENT+'.feature.quench_the_impact'
               for e in engine.events)
    actor=engine.state.actors[OWNER]
    assert steel_forms.forms(actor)==['reed','spine']
    assert steel_forms.active_forms(engine,actor)==['reed']
    condition=next(c for c in actor.conditions.values() if c.condition_id==steel_forms.FORMS)
    assert condition.data['form_source_cls']['spine']==14
    suppress(14,'steel-seal-14')
    engine=loaded(service,mid)
    assert steel_forms.active_forms(engine,engine.state.actors[OWNER])==['reed','spine']


def test_native_full_session_completion_offers_every_tempered_weapon(catalog_environment,monkeypatch,tmp_path):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,3),seed='STEEL-SESSION')
    state=journey(service)
    resource='resource:core.stamina';before=state['actors'][OWNER]['resources'][resource]
    maximum=next(r['maximum'] for r in state['actors'][OWNER]['bundle']['actor_template']['resources'] if r['resource_id']==resource)
    option=next(o for o in service.journey_menu(state['journey_id'],OWNER)['options'] if o['id']=='cultivation:full_session')
    state=journey_act(service,state,option['kind'],option['payload'])
    state=journey_act(service,state,'activity_work',{'seconds':7199})
    assert not any(e['kind']=='FULL_CULTIVATION_SESSION_FINISHED' for e in state['events'])
    state=journey_act(service,state,'activity_work',{'seconds':1})
    choices=service.journey_menu(state['journey_id'],OWNER)['options']
    assert any(o['payload']['choice']=='retain' for o in choices)
    weapon=next(o for o in choices if o['payload']['choice']!='retain')
    state=journey_act(service,state,weapon['kind'],weapon['payload'])
    assert state['actors'][OWNER]['source_states'][PARENT]['tempered_weapon']==weapon['payload']['choice']
    assert any(e['kind']=='FULL_CULTIVATION_SESSION_FINISHED' and e['worked_seconds']==7200 for e in state['events'])
    held=state['actors'][OWNER]['source_states']['system:cultivation.full_session']
    assert state['actors'][OWNER]['resources'][resource]==max(before,maximum)
    assert ('rest' in held) is (before<maximum)


from tests.test_save_reload_equivalence import STOCK_SEEDS


def test_native_full_session_cannot_complete_across_unworked_elapsed_time(catalog_environment,monkeypatch,tmp_path):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,3),seed='STEEL-SESSION-GAP')
    state=journey(service)
    option=next(o for o in service.journey_menu(state['journey_id'],OWNER)['options'] if o['id']=='cultivation:full_session')
    state=journey_act(service,state,option['kind'],option['payload'])
    state=journey_act(service,state,'activity_work',{'seconds':3600})
    service.journey_act(state['journey_id'],state['revision'],FOE,'wait',{'seconds':60})
    state=CombatService(service.source_root,service.userdata_root).journey_state(state['journey_id'])
    with pytest.raises(ValueError,match='interrupted'):
        journey_act(service,state,'activity_work',{'seconds':3600})
    cold=service.journey_state(state['journey_id'])
    assert not any(e['kind']=='FULL_CULTIVATION_SESSION_FINISHED' for e in cold['events'])
    state=journey_act(service,cold,'activity_cancel',{})
    assert 'journey:activity' not in state['actors'][OWNER]['source_states']




def test_native_folded_object_doubling_is_one_hit_only(catalog_environment,monkeypatch,tmp_path):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,10),seed='STEEL-OBJECT',
        objects=[{'id':1,'kind':'crate','x':3,'y':5,'hp':999,'ac':1,'blocks':False,'source_cl':1,
                  'resist':['BLUDGEONING','PIERCING','SLASHING']}])
    advance(service,table,mid)
    engine=loaded(service,mid)
    candidate=next(c for c in engine.legal_candidates() if 'object:map.1' in c.target_ids
        and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('object_weapon_group')=='unarmed')
    settle(table,mid,candidate.candidate_id,{'choice:needle.folded_edge':['double'],'choice:needle.reed_form_move':None})
    engine=loaded(service,mid)
    damage=[e.payload['damage'] for e in engine.events if e.event_type=='OBJECT_UPDATED' and 'damage' in e.payload]
    assert sum('double damage' in r['notes'] for r in damage)==1
    assert not any('resists ' in note for row in damage for note in row['notes'])
    assert engine.state.objects['object:map.1'].current_hp<999


@pytest.mark.parametrize('protection',[None,'immortal_protection','void_protection','physical_force_protected'])
def test_native_tempered_heavenly_interface_preserves_object_protections(catalog_environment,monkeypatch,tmp_path,protection):
    obj={'id':1,'kind':'crate','x':3,'y':5,'hp':999,'ac':1,'blocks':False,'source_cl':1,
         'threshold':1,'resist':['BLUDGEONING','PIERCING','SLASHING','FORCE']}
    if protection:obj[protection]=True
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,18),seed='STEEL-HEAVENLY-'+str(protection),objects=[obj])
    arena=loaded(service,mid).battlefield_document['stable_id']
    state=journey(service,arena)
    option=next(o for o in service.journey_menu(state['journey_id'],OWNER)['options'] if o['id'].startswith('steel:temper:'))
    weapon=option['payload']['parameters']['weapon']
    state=journey_act(service,state,option['kind'],option['payload'])
    state=journey_act(service,state,'activity_work',{'seconds':600})
    mid=service.journey_start_combat(state['journey_id'],state['revision'],{OWNER:'team:a',FOE:'team:b'})['match_id']
    engine=ready_weapon(service,table,mid,weapon)
    candidate=next(c for c in engine.legal_candidates() if 'object:map.1' in c.target_ids
        and engine.action_catalog[c.source_definition_id].parameters.get('weapon_source_id')==weapon+'#integrated_con')
    settle(table,mid,candidate.candidate_id,{'choice:needle.folded_edge':None,
        'choice:needle.body_beyond_the_hammer':None,'choice:needle.reed_form_move':None})
    engine=loaded(service,mid)
    results=[e.payload['damage'] for e in engine.events if e.event_type=='OBJECT_UPDATED' and 'damage' in e.payload]
    assert results
    notes='; '.join(results[-1]['notes'])
    assert ('resists ' in notes) is bool(protection)
    assert ('ignored its Damage Threshold' in notes) is (not bool(protection))
    # The printed attack multiplier remains; protected Resistance/Threshold
    # still resolve normally rather than being bypassed.
    assert 'double damage' in notes
    if protection:assert engine.state.objects['object:map.1'].component[protection]==1


@pytest.mark.parametrize('perfect',['edge','spine'])
def test_native_perfect_choices_and_shared_ac_refresh(catalog_environment,monkeypatch,tmp_path,perfect):
    doc=acquire(catalog_environment,monkeypatch,18)
    service,table,mid=game(tmp_path,doc,seed='STEEL-PERFECT-'+perfect)
    advance(service,table,mid)
    engine=loaded(service,mid)
    play(service,table,mid,strike_name(engine,OWNER),{'choice:needle.folded_edge':['ac'],
        'choice:needle.body_beyond_the_hammer':[perfect],'choice:needle.reed_form_move':None},target=FOE)
    engine=loaded(service,mid)
    reductions=[m for m in engine.state.actors[FOE].modifiers.values() if m.source_definition_id==steel_forms.AC_SOURCE]
    assert len(reductions)==1 and reductions[0].value==-1
    assert reductions[0].source_actor_id==OWNER
    assert reductions[0].data['source_cl']==18
    assert reductions[0].data['feature']==PARENT+'.feature.'+('folded_edge_hidden_spine' if perfect=='spine' else 'body_beyond_the_hammer')
    if perfect=='spine':
        assert engine.state.actors[OWNER].turn_flags['_round_perfect_spine']['source_cl']==18
        con=next(a['modifier'] for a in doc['ability_scores_and_statistics']['abilities'] if a['ability']=='CON')
        assert engine.state.actors[OWNER].temporary_hp==2*engine.state.actors[OWNER].proficiency_bonus+con
    else:
        assert any(r.expression.startswith(('4d8','8d8')) for r in engine.rolls)


def test_native_killing_hit_still_grants_perfect_spine(catalog_environment,monkeypatch,tmp_path):
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,18),seed='STEEL-KILL',foe_hp=1)
    advance(service,table,mid)
    engine=loaded(service,mid)
    play(service,table,mid,strike_name(engine,OWNER),{'choice:needle.folded_edge':None,
        'choice:needle.body_beyond_the_hammer':['spine'],'choice:needle.reed_form_move':None},target=FOE)
    engine=loaded(service,mid)
    assert engine.state.actors[FOE].current_hp==0
    assert engine.state.actors[OWNER].temporary_hp>0


def test_native_perfect_reed_crosses_hostile_space_without_ending_there(catalog_environment,monkeypatch,tmp_path):
    # A real blocked corridor makes passing the hostile creature necessary.
    objects=[{'id':100+y*14+x,'kind':'crate','x':x,'y':y,'hp':999,'ac':20,'blocks':True}
             for y in (5,7) for x in range(14)]
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,18),seed='STEEL-REED-PASS',objects=objects)
    advance(service,table,mid)
    engine=loaded(service,mid)
    # Supplemental wrong-source query controls on the same real acquired actor
    # and native geometry. These contexts are not claimed as movement receipts.
    from combat.ext.rider_movement import routes
    with steel_forms.perfect_reed_scope(engine,engine.state.actors[OWNER]):
        assert 'cell:5,6' in routes(engine,engine.state.actors[OWNER],20,native=True,
                                   source=PARENT+'.feature.body_beyond_the_hammer')
        assert 'cell:5,6' not in routes(engine,engine.state.actors[OWNER],20,native=True,
                                       source=PARENT+'.feature.quench_the_impact')
        assert 'cell:5,6' not in routes(engine,engine.state.actors[OWNER],20,native=True)
    prompts=play(service,table,mid,strike_name(engine,OWNER),{'choice:needle.folded_edge':None,
        'choice:needle.body_beyond_the_hammer':['reed'],'choice:needle.perfect_reed_move':['cell:5,6'],
        'choice:needle.reed_form_move':None},target=FOE)
    route=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.perfect_reed_move')
    offered={o['id'] for o in route['choice']['options']}
    assert 'cell:4,6' not in offered and 'cell:5,6' in offered
    assert 'cell:7,6' not in offered  # 10ft hostile entry + three more steps exceeds20.
    assert not any(k.startswith('cell:') and k.split(',')[1] in ('5','7') for k in offered)
    engine=loaded(service,mid)
    assert (engine.state.actors[OWNER].position.x,engine.state.actors[OWNER].position.y)==(5,6)
    movements=[e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==OWNER
               and e.source_definition_id==PARENT+'.feature.body_beyond_the_hammer']
    assert movements and any(p['x']==4 and p['y']==6 for e in movements for p in e.payload['path'])
    assert not any(e.event_type=='REACTION_RESOLVED' and e.payload.get('checkpoint')=='OPPORTUNITY_ATTACK' for e in engine.events)


@pytest.mark.parametrize('result',['damage','reactions','ac'])
def test_native_folded_results_and_ac_dormancy(catalog_environment,monkeypatch,tmp_path,result):
    from combat.combat_world_facts import clock
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,10),seed='STEEL-FOLDED-'+result)
    picks={'choice:needle.tempering_forms':['edge'],'choice:needle.folded_edge':[result],
        'choice:needle.reed_form_move':None}
    for _ in range(5):
        advance(service,table,mid,picks=picks)
        engine=loaded(service,mid)
        play(service,table,mid,strike_name(engine,OWNER),picks,target=FOE)
        engine=loaded(service,mid)
        if engine.state.actors[OWNER].turn_flags.get('_round_folded_edge'):break
        state=table.state(mid);settle(table,mid,state['menu']['end_turn'],picks)
    owner,target=engine.state.actors[OWNER],engine.state.actors[FOE]
    assert owner.turn_flags.get('_round_folded_edge')
    if result=='damage':
        rolls=[e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and e.payload.get('display_source_id')==PARENT+'.feature.folded_edge_hidden_spine']
        assert len(rolls)==1
    elif result=='reactions':
        from combat.typed_executor import condition_rules
        assert any(r.get('no_reactions') for r in condition_rules(target))
        held=next(c for c in target.conditions.values() if c.source_definition_id==PARENT+'.feature.folded_edge_hidden_spine')
        assert held.data['source_cl']==10 and not target.reaction_available
        def suppression(level,nonce):
            nonlocal engine
            reply=table.world_fact(mid,engine.state.state_version,{'source':'system:body_modes_scene_resources',
                'subject':OWNER,'kind':'cultivation_suppression','scope':'steel-reaction-dormancy',
                'value':{'source_rule':'A sourced Realm seal sets effective Body CL to '+str(level)+'.',
                    'source_cl':18,'system':'body','effective_cl':level},'expires_at':int(clock(engine))+60,
                'readers':[OWNER,FOE]},nonce)
            assert reply['status']=='COMMITTED'
            engine=loaded(service,mid)
        suppression(6,'steel-reactions-6')
        assert not any(r.get('no_reactions') for r in condition_rules(engine.state.actors[FOE]))
        assert engine.state.actors[FOE].reaction_available
        move=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination.x==2 and c.destination.y==6)
        settle(table,mid,move.candidate_id,picks)
        engine=loaded(service,mid)
        assert not engine.state.actors[FOE].reaction_available
        assert all(not c.data.get('reaction_suppression_restore') for c in engine.state.actors[FOE].conditions.values()
                   if c.source_definition_id==PARENT+'.feature.folded_edge_hidden_spine')
        suppression(10,'steel-reactions-10')
        assert any(r.get('no_reactions') for r in condition_rules(engine.state.actors[FOE]))
        suppression(6,'steel-reactions-6-again')
        assert not engine.state.actors[FOE].reaction_available
        advance(service,table,mid,FOE,picks=picks)
        engine=loaded(service,mid)
        assert not any(r.get('no_reactions') for r in condition_rules(engine.state.actors[FOE]))
    else:
        mod=next(m for m in target.modifiers.values() if m.source_definition_id==steel_forms.AC_SOURCE)
        assert mod.data=={'feature':PARENT+'.feature.folded_edge_hidden_spine','source_cl':10}
        assert steel_forms.steel_ac_available(engine,target,mod.model_copy(update={'source_actor_id':FOE})) is False
        assert engine._ac_modifier(target)==-1
        for level,expected in [(6,0),(10,-1)]:
            reply=table.world_fact(mid,engine.state.state_version,{'source':'system:body_modes_scene_resources',
                'subject':OWNER,'kind':'cultivation_suppression','scope':'steel-ac-dormancy',
                'value':{'source_rule':'A sourced Realm seal sets effective Body CL to '+str(level)+'.',
                    'source_cl':18,'system':'body','effective_cl':level},'expires_at':int(clock(engine))+60,
                'readers':[OWNER,FOE]},'steel-ac-'+str(level))
            assert reply['status']=='COMMITTED'
            engine=loaded(service,mid)
            assert engine._ac_modifier(engine.state.actors[FOE])==expected
        # A normal unrelated modifier keeps its old behavior (default inert).
        unrelated=mod.model_copy(update={'source_definition_id':'contract:unrelated','value':3,'data':{}})
        assert steel_forms.steel_ac_available(engine,target,unrelated) is None


def test_native_object_ac_keeps_source_and_dormancy(catalog_environment,monkeypatch,tmp_path):
    from combat.combat_world_facts import clock
    service,table,mid=game(tmp_path,acquire(catalog_environment,monkeypatch,10),seed='STEEL-OBJECT',
        objects=[{'id':1,'kind':'crate','x':3,'y':5,'hp':999,'ac':1,'blocks':False,'source_cl':1}])
    advance(service,table,mid)
    engine=loaded(service,mid)
    assert steel_forms.steel_object_ac_dormancy(engine,engine.state.objects['object:map.1']) is None
    candidate=next(c for c in engine.legal_candidates() if 'object:map.1' in c.target_ids
        and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('object_weapon_group')=='unarmed')
    settle(table,mid,candidate.candidate_id,{'choice:needle.folded_edge':['ac']})
    engine=loaded(service,mid);obj=engine.state.objects['object:map.1']
    assert obj.ac==0 and obj.component['steel_ac_reduction']['source_cl']==10
    assert steel_forms.steel_object_ac_dormancy(engine,obj) is None
    reply=table.world_fact(mid,engine.state.state_version,{'source':'system:body_modes_scene_resources',
        'subject':OWNER,'kind':'cultivation_suppression','scope':'steel-object-ac-dormancy',
        'value':{'source_rule':'A sourced Realm seal sets effective Body CL6.','source_cl':18,'system':'body','effective_cl':6},
        'expires_at':int(clock(engine))+60,'readers':[OWNER,FOE]},'steel-object-ac-6')
    assert reply['status']=='COMMITTED'
    engine=loaded(service,mid);obj=engine.state.objects['object:map.1']
    assert obj.ac==0 and steel_forms.steel_object_ac_dormancy(engine,obj)==1
