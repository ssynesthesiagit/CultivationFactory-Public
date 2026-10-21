"""Native acquired Vermilion Gate continuation and shared-contract checks."""
import json
import pytest
from tests.test_mgr_vermilion_gate_native import (
    game,commit,turn,move,A,B,C,PARENT,PREFIX,STAMINA,ROOT,candidate,reload,act,
    CombatService,TabletopService,stable_native_journey_identity,
)


def publish_body_build(combat, level, *, remove_iron_fist=False):
    """Install an updated portable character; never install family ownership."""
    import zipfile
    path=combat.combatant_library.install_root/'guardian'/'current.zip'
    with zipfile.ZipFile(path) as z:
        doc=json.loads(z.read('Tianxia_Owner_Character_Sheet_v1.json'))
    doc['identity']['cultivation_level']=level
    doc['path_and_subpath']['paths'][0]['effective_cl']=level
    doc['ability_scores_and_statistics']['primary_resource']['maximum']=level*5
    features=doc['path_and_subpath']['path_feature_record_ids']
    assert not any(f.startswith(PREFIX) for f in features)
    if remove_iron_fist:features.remove('tianxia.path.body_refining.feature.iron_fist')
    if level>=5:features.append('tianxia.path.body_refining.feature.extra_attack')
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))


def test_native_updated_build_advances_only_earned_family_without_refill(tmp_path):
    combat,_,_,jid=game(tmp_path,cl=3,start_combat=False)
    before=combat.journey_state(jid)
    assert before['actors'][A]['resources'][STAMINA]==15
    publish_body_build(combat,6,remove_iron_fist=True)
    combat=CombatService(ROOT,tmp_path)
    assert combat.journey_source_choices(jid,A,PARENT)['options'][0]['id']=='advance'
    state=combat.journey_acquire_source(jid,before['revision'],A,PARENT,{'choice':'advance'})
    actor=state['actors'][A];source=actor['source_states'][PARENT]
    acquired=json.loads(source['acquired_sheet'])['path_and_subpath']['path_feature_record_ids']
    assert source['earned_level']==6 and actor['resources'][STAMINA]==15
    assert set(f for f in acquired if f.startswith(PREFIX))=={PREFIX+'guardian_at_the_gate',PREFIX+'shelter_behind_the_gate'}
    assert 'tianxia.path.body_refining.feature.iron_fist' not in acquired
    assert state['events'][-1]['kind']=='SUBPATH_ADVANCED'
    assert combat.journey_source_choices(jid,A,PARENT)['options']==[]
    with pytest.raises(ValueError):combat.journey_acquire_source(jid,state['revision'],A,PARENT,{'choice':'advance'})
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    mid=combat.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b',C:'team:a'})['match_id']
    table=TabletopService(combat,tmp_path)
    turn(table,mid,B);turn(table,mid,A);turn(table,mid,B)
    engine=reload(tmp_path,mid)
    assert len(engine.state.actors[A].turn_flags['_round_gate_thresholds'])==1
    assert engine.state.actors[A].resources[STAMINA]==15
    assert not any(a.owner_id==A and a.display_name=="Heaven's Closed Gate" for a in engine.action_catalog.values())


def test_native_reopened_journey_derives_progression_from_updated_build(tmp_path,monkeypatch):
    combat,_,_,jid=game(tmp_path,cl=3,start_combat=False)
    state=combat.journey_state(jid)
    state=combat.journey_act(jid,state['revision'],A,'finish',{})
    publish_body_build(combat,6)
    monkeypatch.setattr('combat.journey.secrets.token_hex',lambda n:'d'*24)
    combat=CombatService(ROOT,tmp_path)
    state=combat.create_journey(project_ids=['guardian','traveller','companion'],
        arena_id=state['battlefield']['stable_id'],positions={A:{'x':3,'y':6},B:{'x':6,'y':6},C:{'x':3,'y':5}},
        base_paces={A:100,B:100,C:100},control_modes={A:'MANUAL',B:'MANUAL',C:'MANUAL'})
    assert state['actors'][A]['resources'][STAMINA]==15
    assert state['actors'][A]['source_states'][PARENT]['earned_level']==6
    assert any(e['kind']=='SUBPATH_ADVANCED' and e['actor_id']==A for e in state['events'])
    assert CombatService(ROOT,tmp_path).journey_state(state['journey_id'])==state
    mid=combat.journey_start_combat(state['journey_id'],state['revision'],{A:'team:a',B:'team:b',C:'team:a'})['match_id']
    table=TabletopService(combat,tmp_path)
    turn(table,mid,B);turn(table,mid,A);turn(table,mid,B)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[A].resources[STAMINA]==15
    assert len(engine.state.actors[A].turn_flags['_round_gate_thresholds'])==1


def test_native_acquisition_preserves_saved_ask_reaction_preferences(tmp_path):
    from combat.tabletop import ButtonStore
    owner='actor:factory.a0000000'
    combat,_,_,jid=game(tmp_path,cl=3,acquire=False,start_combat=False,foe_at={'x':5,'y':6},owner_project_id='a0000000')
    ButtonStore(tmp_path/'tabletop_buttons').save_reactions('a0000000',{'mode':'ask'},{'opportunity_attack'})
    state=combat.journey_state(jid)
    state=combat.journey_acquire_source(jid,state['revision'],owner,PARENT,{'choice':'choose'})
    assert state['actors'][owner]['bundle']['reaction_plan']['mode']=='ask'
    combat=CombatService(ROOT,tmp_path)
    mid=combat.journey_start_combat(jid,state['revision'],{owner:'team:a',B:'team:b',C:'team:a'})['match_id']
    table=TabletopService(combat,tmp_path)
    turn(table,mid,B);turn(table,mid,owner);turn(table,mid,B)
    prompts=move(combat,table,mid,B,3,7)
    assert any(p['context']['reaction_source_id']=='choice:needle.guardian_at_the_gate' for p in prompts)
    engine=reload(tmp_path,mid)
    assert next(b for b in engine.typed_bundle_documents if b['actor_id']==owner)['reaction_plan']['mode']=='ask'


def test_native_retained_gate_is_dormant_then_restores_without_refund(tmp_path):
    combat,_,_,jid=game(tmp_path,start_combat=False,foe_at={'x':10,'y':6},foe_features=['TAL_SPACE_FOLD_STEP'])
    state=combat.journey_state(jid)
    state=combat.journey_act(jid,state['revision'],A,'gate_activate',{'allies':[]})
    balance=state['actors'][A]['resources'][STAMINA]
    state=combat.journey_world_fact(jid,state['revision'],{'source':'system:body_modes_scene_resources','subject':A,
        'kind':'cultivation_suppression','scope':'courtyard-realm','value':{'source_rule':'The table owner explicitly suppresses Body cultivation for six seconds.',
        'source_cl':20,'system':'body','effective_cl':3},'expires_at':6,'readers':[A]})
    state=combat.journey_act(jid,state['revision'],A,'body_source_state',{'kind':'cultivation_suppression','scope':'courtyard-realm'})
    mid=combat.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b',C:'team:a'})['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,B)
    first=len(reload(tmp_path,mid).events)
    commit(table,mid,candidate(combat,mid,'Fold Step',at=(8,6)).candidate_id,{'choice:needle.teleport_destination':['cell:8,6']})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[B].position.x==8
    assert not any(e.event_type=='CHECK_ROLLED' and e.source_definition_id==PREFIX+'heaven_s_closed_gate' for e in engine.events[first:])
    posts=list(engine.state.actors[A].turn_flags['_round_closed_gate']['posts'])
    commit(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,B)
    first=len(reload(tmp_path,mid).events)
    commit(table,mid,candidate(combat,mid,'Fold Step',at=(10,6)).candidate_id,{'choice:needle.teleport_destination':['cell:10,6']})
    engine=reload(tmp_path,mid)
    checks=[e for e in engine.events[first:] if e.event_type=='CHECK_ROLLED' and e.source_definition_id==PREFIX+'heaven_s_closed_gate']
    assert len(checks)==1 and checks[0].payload['success'] is False
    assert engine.state.actors[B].position.x==8
    assert engine.state.actors[A].turn_flags['_round_closed_gate']['posts']==posts
    assert engine.state.actors[A].resources[STAMINA]==balance


def test_native_http_source_menu_acquisition_and_protected_scene_input(tmp_path):
    import asyncio
    import httpx
    from app.api import create_app
    from app.core import Settings
    if not (ROOT/'migrations/010_optional_ai_provider.sql').is_file():
        pytest.skip('Public snapshot omits native SQL migrations; this exact HTTP test also runs in the local changed-guard batch.')
    combat,_,_,jid=game(tmp_path,acquire=False,start_combat=False)
    def no_transport(*args,**kwargs):raise AssertionError('No live AI transport belongs in this test')
    app=create_app(Settings.from_env(ROOT,tmp_path),ai_transport=no_transport)
    app.state.agent_seats.background=False
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            url=f'/api/combat/journeys/{jid}'
            menu=await client.get(url+f'/source-choices/{A}',params={'source':PARENT})
            assert menu.status_code==200 and menu.json()['options'][0]['id']=='choose'
            body={'revision':0,'actor_id':A,'source':PARENT,'payload':{'choice':'choose'}}
            assert (await client.post(url+'/acquire-source',json=body)).status_code==403
            headers={'x-foundry-token':(await client.get('/api/session')).json()['token']}
            result=await client.post(url+'/acquire-source',headers=headers,json=body)
            assert result.status_code==200,result.text
            state=result.json()
            assert CombatService(ROOT,tmp_path).journey_state(jid)==state
            result=await client.post(url+'/end-scene',headers=headers,json={'revision':state['revision'],'reason':'Courtyard defense ends.'})
            assert result.status_code==200 and result.json()['events'][-1]['kind']=='SCENE_ENDED'
            assert CombatService(ROOT,tmp_path).journey_state(jid)==result.json()
    asyncio.run(exercise())


def test_late_attack_ac_grant_suspends_and_unwinds_on_abort():
    # General seam guard, supplementary to the acquired native Shelter attack.
    from combat.ext.attack_defenses import grant,resolving_defenses
    from tests.test_forced_movement_reactions import _engine,REACTOR
    engine=_engine([]);actor=engine.state.actors[REACTOR];spec={}
    with resolving_defenses(engine,spec):
        assert engine._ac_modifier(actor)==0
        grant(spec,actor,'test:late_ac',1)
        assert engine._ac_modifier(actor)==1
        with pytest.raises(RuntimeError):
            with resolving_defenses(engine,{}):
                assert engine._ac_modifier(actor)==0
                raise RuntimeError('Abort nested attack')
        assert engine._ac_modifier(actor)==1
    assert not actor.modifiers


def test_native_body_recovery_consumes_time_without_refreshing_gate_scene(tmp_path):
    combat,_,_,jid=game(tmp_path,start_combat=False)
    state=combat.journey_state(jid);maximum=state['actors'][A]['resources'][STAMINA]
    state=combat.journey_act(jid,state['revision'],A,'gate_activate',{'allies':[]})
    pool=next(k for k,v in state['actors'][A]['resources'].items() if k.startswith('resource:uses.') and v==0)
    state=combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'start','mode':'short_rest'})
    with pytest.raises(ValueError):combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'finish'})
    state=combat.journey_act(jid,state['revision'],A,'wait',{'seconds':3600})
    state=combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'finish'})
    assert state['actors'][A]['resources'][STAMINA]==maximum
    assert state['actors'][A]['resources'][pool]==0 and state['seconds']==3600
    state=combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'start','mode':'short_rest'})
    state=combat.journey_act(jid,state['revision'],A,'wait',{'seconds':3600})
    state=combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'finish'})
    with pytest.raises(ValueError):combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'start','mode':'short_rest'})
    state=combat.journey_end_scene(jid,state['revision'],'The first two watch shifts end.')
    state=combat.journey_act(jid,state['revision'],A,'gate_activate',{'allies':[]})
    assert state['actors'][A]['resources'][STAMINA]==maximum-7
    state=combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'start','mode':'cultivation_session'})
    state=combat.journey_act(jid,state['revision'],A,'wait',{'seconds':7199})
    with pytest.raises(ValueError):combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'finish'})
    state=combat.journey_act(jid,state['revision'],A,'wait',{'seconds':1})
    state=combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'finish'})
    assert state['actors'][A]['resources'][STAMINA]==maximum
    with pytest.raises(ValueError):combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'start','mode':'cultivation_session'})
    state=combat.journey_act(jid,state['revision'],A,'long_rest',{})
    assert state['seconds']==43200 and state['actors'][A]['resources'][pool]==0
    state=combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'start','mode':'short_rest'})
    state=combat.journey_act(jid,state['revision'],A,'move',{'path':[{'x':2,'y':6}]})
    with pytest.raises(ValueError):combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'finish'})
    state=combat.journey_act(jid,state['revision'],A,'body_recover_stamina',{'phase':'cancel'})
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state


def test_native_world_suppression_governs_allied_table_scene_and_replay(tmp_path):
    combat,_,_,jid=game(tmp_path,start_combat=False)
    state=combat.journey_state(jid)
    state=combat.journey_world_fact(jid,state['revision'],{'source':'system:body_modes_scene_resources','subject':A,
        'kind':'cultivation_suppression','scope':'courtyard-realm','value':{'source_rule':'The table owner applies this explicit Body Realm suppression.',
        'source_cl':20,'system':'body','effective_cl':3},'expires_at':60,'readers':[A]})
    state=combat.journey_act(jid,state['revision'],A,'body_source_state',{'kind':'cultivation_suppression','scope':'courtyard-realm'})
    assert not any(o['kind']=='gate_activate' for o in combat.journey_menu(jid,A)['options'])
    mid=combat.journey_start_scene(jid,state['revision'],{A:'team:a',B:'team:a',C:'team:a'},maximum_rounds=2)['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,A);commit(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,A)
    engine=reload(tmp_path,mid)
    assert len(engine.state.actors[A].turn_flags['_round_gate_thresholds'])==1
    assert not any(c.display_name.startswith("Heaven's Closed Gate") for c in engine.legal_candidates())
    for _ in range(12):
        if combat._load_session(mid).engine.state.terminal_result is not None:break
        commit(table,mid,table.state(mid)['menu']['end_turn'])
    else:raise AssertionError('The bounded allied scene must end')
    state=combat.journey_state(jid)
    state=combat.journey_resume(jid,state['revision'])
    assert state['seconds']==12 and state['phase']=='travel'
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state


def test_gate_actual_payment_reaches_zero_once_and_imports_native_exhaustion(tmp_path):
    combat,_,_,jid=game(tmp_path,start_combat=False,owner_score=24)
    state=combat.journey_state(jid)
    assert state['actors'][A]['resources'][STAMINA]==126
    for index in range(18):
        state=combat.journey_act(jid,state['revision'],A,'gate_activate',{'allies':[]})
        state=combat.journey_act(jid,state['revision'],A,'wait',{'seconds':60})
        if index<17:state=combat.journey_end_scene(jid,state['revision'],f'The table owner ends defense scene {index+1}.')
    assert state['actors'][A]['resources'][STAMINA]==0 and state['actors'][A]['exhaustion']==1
    assert sum(e['kind']=='BODY_STAMINA_EXHAUSTION' for e in state['events'])==1
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    mid=combat.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b',C:'team:a'})['match_id']
    engine=reload(tmp_path,mid)
    from combat.ext.forged_exhaustion import level
    assert level(engine.state.actors[A])==1 and engine._effective_speed(engine.state.actors[A])==25


def test_native_guardian_only_suppression_keeps_common_threshold_producer(tmp_path):
    combat,_,_,jid=game(tmp_path,start_combat=False,foe_at={'x':5,'y':6})
    state=combat.journey_state(jid)
    state=combat.journey_world_fact(jid,state['revision'],{'source':'system:body_modes_scene_resources','subject':A,
        'kind':'cultivation_suppression','scope':'interception-only','value':{'source_rule':'The table owner expressly suppresses only Guardian at the Gate, not the common threshold or other features.',
        'source_cl':20,'system':'body','feature_id':PREFIX+'guardian_at_the_gate'},'expires_at':60,'readers':[A]})
    state=combat.journey_act(jid,state['revision'],A,'body_source_state',{'kind':'cultivation_suppression','scope':'interception-only'})
    mid=combat.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b',C:'team:a'})['match_id']
    table=TabletopService(combat,tmp_path)
    turn(table,mid,B);turn(table,mid,A);turn(table,mid,B)
    engine=reload(tmp_path,mid)
    assert len(engine.state.actors[A].turn_flags['_round_gate_thresholds'])==2
    first=len(engine.events);before=engine.state.actors[B].movement_remaining_ft
    prompts=move(combat,table,mid,B,3,7)
    engine=reload(tmp_path,mid)
    assert not any(p['context']['reaction_source_id']=='choice:needle.guardian_at_the_gate' for p in prompts)
    assert engine.state.actors[B].position.x==3
    assert engine.state.actors[B].movement_remaining_ft==before-15
    assert not any(e.event_type=='ATTACK_ROLLED' and e.actor_id==A for e in engine.events[first:])
