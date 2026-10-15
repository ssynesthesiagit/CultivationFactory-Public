"""Source acquisition -> native table choices -> committed state -> cold replay.

No owner feature rows or trigger receipts are inserted in the engine. Scenario
opponents remain ordinary separately compiled creatures. All transport is local.
"""
import copy
import json
import zipfile
import pytest
from pathlib import Path
from combat.canonical import canonical_sha256
EVIDENCE=Path("/var/tmp/auto-audit/fix/MGR-T14-sol-reserve-nine-star-meridian-body-star-lit-acupoints-1-evidence")
from app.api import create_app
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests import test_riders_c7 as c7

NINE = "tianxia.subpath.body.nine_star_meridian_body"
FURNACE = "tianxia.subpath.body.five_viscera_immortal_furnace"
OWNER = "actor:factory.mode-owner"
FOE = "actor:factory.mode-foe"
MARKS = "resource:named.celestial_mark"


def acquire(environment, monkeypatch, parent, cl):
    cache=environment.setdefault('_body_mode_native_acquisitions',{})
    key=(parent,cl)
    if key in cache:return copy.deepcopy(cache[key])
    cached=EVIDENCE/(parent.rsplit('.',1)[-1]+'-cl'+str(cl)+'-acquisition.json')
    if cached.exists():
        proof=json.loads(cached.read_text())
        assert proof['document_sha256']==canonical_sha256(proof['document'])
        assert proof['validated_native_capsule']==1 and proof['parent']==parent and proof['cl']==cl
        return copy.deepcopy(proof['document'])
    monkeypatch.setenv('TIANXIA_BROWSER_EXECUTABLE','/var/tmp/auto-audit/NO_BROWSER_ALLOWED')
    app=create_app(environment['settings'])
    builder=app.state.character_builder
    project=builder.create_project(working_name='Body mode disciple',concept='Restricted scripture Body Refiner',
        source_reference=None,target_cl=cl,power_band='rival/boss',creation_mode='detailed',
        generation_route='ai_bootstrap',ability_scores={},autogen_seed='BODY-MODES-NATIVE',
        selections={'path_choice':['tianxia.path.body_refining'],'subpath_choice':[parent]},
        method_planning_mode='AUTO')
    builder.commit_normal_first_cycle_catalog_choices(project['project_id'])
    run=app.state.character_creation.start(project['project_id'],execution_mode='STANDARD_API',
        idempotency_key='body-mode-native-'+str(cl),controller_route='DETERMINISTIC_CREATIVE_CONTROLLER')
    assert run['status'] in ('READY_FOR_REVIEW','NEEDS_REVIEW'), run
    if run['status']=='NEEDS_REVIEW':
        codes=[b['code'] for b in run['blockers']]
        if codes==['CHARACTER_GM_COMMAND5_AUDIT_FAILED']:
            detail=run['blockers'][0]['details']
            assert detail['diagnostics']==[{'code':'GM_VIEW_MODEL_PINNED_SCHEMA_ERROR','message':"'composites' is a required property"}],detail
            assert detail['gm_candidate_capsule']['status']=='CANDIDATE_CONTEXT_CAPTURED' and detail['gm_candidate_capsule']['event_count']>0
        else:
            assert codes==['COMMAND6_CHARACTER_GM_CONSUMER_FAILED'], run['blockers']
    doc=app.state.character_creation.load_candidate_gm_context(run['run_id'])['owner_character_sheet']
    earned=[r for r in doc['path_and_subpath']['earned_feature_occurrences'] if r.get('parent_record_id')==parent]
    expected=(['star_lit_acupoints','orbital_body','falling_star_descent','constellation_circuit','nine_star_incarnation']
              if parent==NINE else ['five_viscera_circuit','refine_the_impure','twin_furnace_circulation','fivefold_organ_harmony','inner_cosmos_furnace'])
    assert {r['feature_id'] for r in earned}=={parent+'.feature.'+name for level,name in zip((3,6,10,14,18),expected) if cl>=level}
    assert all(r['source_backed'] and r['source_packet_ids'] and r['acquisition_event_hash'] and r['attainment_event_hash'] for r in earned)
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    cached.write_text(json.dumps({'parent':parent,'cl':cl,'document':doc,'document_sha256':canonical_sha256(doc),'validated_native_capsule':1,'run_id':run['run_id'],'project_id':project['project_id'],'gm_blocker_codes':[b['code'] for b in run.get('blockers',[])]},sort_keys=True))
    cache[key]=copy.deepcopy(doc)
    return doc


def installed(root,aid,doc):
    folder=root/'portable_characters'/aid.removeprefix('actor:factory.')
    folder.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))


def game(root,doc,seed='BODY-MODES',ask=True):
    installed(root,OWNER,doc)
    foe=c7.sheet([],cl=18,name='Sparring opponent')
    foe['ability_scores_and_statistics']['hit_points']['maximum']=1000
    installed(root,FOE,foe)
    service=CombatService(ROOT,root)
    if ask:TabletopService(service,root).save_reactions('mode-owner',{'mode':'ask'})
    saved=service.tabletop_maps.save({'display_name':'Body modes native yard','width_squares':14,'height_squares':14,
        'walls':[],'starts':{'team1':[[3,6]],'team2':[[4,6]]}})
    mid=service.create_factory_match(project_ids=['mode-owner'],opponent_actor_ids=[FOE],
        control_modes={OWNER:'MANUAL',FOE:'MANUAL'},arena_id='battlefield:map.'+saved['map_id'],match_seed=seed)['match_id']
    return service,TabletopService(service,root),mid


def loaded(service,mid):
    session=CombatService(service.source_root,service.userdata_root)._load_session(mid)
    assert session.mechanical.replay()['status']=='PASS'
    return session.engine


def settle(table,mid,cid,picks=None):
    answers=[];prompts=[]
    for _ in range(40):
        state=table.state(mid); menu=state['menu']
        result=table.act(mid,cid,menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
        if result['status']=='COMMITTED':return prompts
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];prompts.append(p);rid=p['context']['reaction_source_id']
        options=[o['id'] for o in p.get('choice',{}).get('options',[])]
        value=(picks or {}).get(rid,options[0] if options and rid.startswith('choice:') else None)
        answer={**p['context'],'selection':'USE' if value is not None else 'DECLINE'}
        if value is not None and options:answer['option_ids']=value if isinstance(value,list) else [value]
        answers.append(answer)
    raise AssertionError('Unsettled native choices')


def play(service,table,mid,name,picks=None,target=None):
    candidates=service._load_session(mid).engine.legal_candidates()
    c=next(c for c in candidates if (c.display_name==name or c.display_name.startswith(name+' at ')) and (not target or target in c.target_ids))
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


@pytest.mark.parametrize('parent,cl',[(NINE,3),(NINE,6),(NINE,10),(NINE,14),(NINE,18),(FURNACE,3)])
def test_acquired_progression_has_native_scene_and_mode_contract(catalog_environment,monkeypatch,tmp_path,parent,cl):
    doc=acquire(catalog_environment,monkeypatch,parent,cl)
    service,table,mid=game(tmp_path,doc,seed='BODY-MODE-'+str(cl)+parent)
    engine=loaded(service,mid)
    actor=engine.state.actors[OWNER]
    # This is the fail-before assertion: neither provider had the scene record.
    state=[c for c in actor.conditions.values() if c.condition_id=='condition:typed.body_scene' and c.data.get('source')==parent]
    assert len(state)==1
    assert state[0].data['source_cl']==cl
    if parent==NINE:
        assert actor.resources[MARKS]==(3 if cl>=14 else 1)
    else:
        assert not any('twin_furnace' in json.dumps(r) or 'fivefold' in json.dumps(r) for r in engine.typed_passive_rows[OWNER])
        advance(service,table,mid,picks={'choice:needle.organ_furnaces':['lung']})
        actor=loaded(service,mid).state.actors[OWNER]
        assert next(c for c in actor.conditions.values() if c.condition_id=='condition:typed.organ_furnaces').data['active']==['lung']


def strike_name(engine,aid):
    return next(a.display_name for a in engine.action_catalog.values() if a.owner_id==aid and a.economy.value=='ACTION'
                and any(e.get('type')=='attack' and e.get('attack_kind')=='unarmed' for e in (a.parameters.get('typed') or {}).get('effects',())))


@pytest.mark.parametrize('result',['Move 5 feet','Push 5 feet','Pull 5 feet','+1 AC against it'])
def test_native_star_lit_all_printed_results(catalog_environment,monkeypatch,tmp_path,result):
    doc=acquire(catalog_environment,monkeypatch,NINE,18)
    service,table,mid=game(tmp_path,doc,seed='STAR-LIT-'+result)
    advance(service,table,mid)
    engine=loaded(service,mid);before=engine.state.actors[OWNER].resources[MARKS]
    prompts=play(service,table,mid,strike_name(engine,OWNER),
        {'choice:needle.path_hit.'+NINE+'.feature.star_lit_acupoints':[result]},target=FOE)
    engine=loaded(service,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.path_hit.'+NINE+'.feature.star_lit_acupoints' for p in prompts)
    assert engine.state.actors[OWNER].resources[MARKS]==before-1
    assert any(r.expression.startswith('1d8') for r in engine.rolls)
    if result=='+1 AC against it':
        assert any(c.condition_id=='condition:typed.ac_against' and c.data['against']==FOE for c in engine.state.actors[OWNER].conditions.values())


def test_native_light_no_cost_and_once_during_owner_turn(catalog_environment,monkeypatch,tmp_path):
    doc=acquire(catalog_environment,monkeypatch,NINE,18)
    service,table,mid=game(tmp_path,doc,seed='STAR-LIGHT')
    advance(service,table,mid)
    before=loaded(service,mid).state.actors[OWNER].model_dump(mode='json')
    play(service,table,mid,'Star-Lit Acupoints: Emit Dim Light')
    engine=loaded(service,mid);actor=engine.state.actors[OWNER]
    assert actor.resources==before['resources'] and actor.action_available==before['action_available']
    from combat import senses
    assert senses.pinpoints(engine,engine.state.actors[FOE],actor)
    assert not any(c.display_name.startswith('Star-Lit Acupoints:') for c in engine.legal_candidates())


@pytest.mark.parametrize('mode',['heart','lung','liver','kidney','spleen'])
def test_native_circuit_initiative_all_furnaces_and_cosmetic_setting(catalog_environment,monkeypatch,tmp_path,mode):
    doc=acquire(catalog_environment,monkeypatch,FURNACE,3)
    service,table,mid=game(tmp_path,doc,seed='CIRCUIT-'+mode)
    advance(service,table,mid,picks={'choice:needle.organ_furnaces':[mode]})
    engine=loaded(service,mid);actor=engine.state.actors[OWNER]
    selected=next(c for c in actor.conditions.values() if c.condition_id=='condition:typed.organ_furnaces')
    assert selected.data['active']==[mode] and selected.data['source_cl']==3
    before=actor.model_dump(mode='json')
    play(service,table,mid,'Organ Furnaces: Suppress cosmetic signs')
    actor=loaded(service,mid).state.actors[OWNER]
    assert actor.resources==before['resources'] and actor.action_available==before['action_available']
    assert any(c.condition_id=='condition:typed.organ_furnace_signs' and c.data['visible']==0 for c in actor.conditions.values())
    assert next(c for c in actor.conditions.values() if c.condition_id=='condition:typed.organ_furnaces').data['active']==[mode]


def journey_game(root,doc):
    installed(root,OWNER,doc);installed(root,FOE,c7.sheet([],cl=18,name='Travel opponent'))
    service=CombatService(ROOT,root)
    saved=service.tabletop_maps.save({'display_name':'Body modes travel yard','width_squares':14,'height_squares':14,'walls':[],
        'starts':{'team1':[[3,6]],'team2':[[4,6]]}})
    state=service.create_journey(project_ids=['mode-owner','mode-foe'],arena_id='battlefield:map.'+saved['map_id'],
        positions={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6}},base_paces={OWNER:12000,FOE:12000})
    return service,state['journey_id']


def journey_do(service,jid,kind,payload,aid=OWNER):
    state=service.journey_state(jid)
    return service.journey_act(jid,state['revision'],aid,kind,payload)


def declare_source(service,jid,kind,scope,value,seconds=7200):
    from combat.ext.body_modes_scene_resources import AUTHORITY
    state=service.journey_state(jid)
    service.journey_world_fact(jid,state['revision'],{'source':AUTHORITY,'subject':OWNER,'kind':kind,'scope':scope,'value':value,
        'expires_at':state['seconds']+seconds,'readers':[]})
    return journey_do(service,jid,'body_source_state',{'scope':scope,'kind':kind})


def test_native_lung_one_hour_clock_and_no_air_lifecycle(catalog_environment,monkeypatch,tmp_path):
    doc=acquire(catalog_environment,monkeypatch,FURNACE,3)
    service,jid=journey_game(tmp_path,doc)
    journey_do(service,jid,'furnace_select',{'furnace':'lung'})
    journey_do(service,jid,'furnace_breath',{'operation':'hold'})
    declare_source(service,jid,'breathing_exposure','sealed-room',{'source_rule':'The sealed room has no breathable air.', 'source_cl':3,'no_air':1})
    journey_do(service,jid,'wait',{'seconds':3599})
    cold=CombatService(ROOT,tmp_path);state=cold.journey_state(jid)
    assert state['actors'][OWNER]['incapacitated']==0
    props=cold.journey_menu(jid,OWNER)['properties']
    assert props['hold_breath_seconds']==3600 and props['breath_held_num']==3599
    with pytest.raises(ValueError,match='breathable air'):
        journey_do(cold,jid,'furnace_breath',{'operation':'breathe'})
    journey_do(cold,jid,'wait',{'seconds':61})
    state=CombatService(ROOT,tmp_path).journey_state(jid)
    assert state['actors'][OWNER]['encounter_snapshot']['current_hp']==0
    assert any(e['kind']=='SUFFOCATION_COMMITTED' for e in state['events'])


def test_native_effective_cl_authority_and_source_isolation(catalog_environment,monkeypatch,tmp_path):
    doc=acquire(catalog_environment,monkeypatch,FURNACE,3)
    service,jid=journey_game(tmp_path,doc)
    declare_source(service,jid,'cultivation_suppression','body-seal',{'source_rule':'The recorded seal reduces effective Body CL to 2.',
        'source_cl':18,'system':'body','effective_cl':2},seconds=12)
    from combat.ext.body_modes_scene_resources import AUTHORITY
    with pytest.raises(ValueError,match='table-owner'):
        journey_do(service,jid,'declare_fact',{'source':AUTHORITY,'subject':OWNER,'kind':'cultivation_suppression','scope':'spoof',
            'value':{'source_rule':'fake','source_cl':18,'system':'all','suppressed':1},'expires_at':10,'readers':[]})
    assert not any(o['kind']=='furnace_select' for o in service.journey_menu(jid,OWNER)['options'])
    journey_do(service,jid,'wait',{'seconds':12})
    assert any(o['kind']=='furnace_select' for o in CombatService(ROOT,tmp_path).journey_menu(jid,OWNER)['options'])
    state=service.journey_state(jid)
    service.journey_end_scene(jid,state['revision'],'The recorded hostile situation has ended.')
    state=CombatService(ROOT,tmp_path).journey_state(jid)
    assert any(e['kind']=='SCENE_ENDED' for e in state['events'])


def test_retain_already_captured_native_owner_capsules():
    """Preserve actual validated owner capsules from the earlier source run.

    The acquisition errors remain errors in their terminal log. This reads the
    captured immutable owner context, whose loader verifies its commitment; it
    supplies no GM export or browser acceptance credit and adds no feature rows.
    """
    import sqlite3
    from app.core import Settings
    root=Path('/var/tmp/auto-audit/scratch/MGR-T14-sol-reserve-nine-star-meridian-body-star-lit-acupoints-1/pt-native/vendor_session0')
    assert (root/'foundry.sqlite3').is_file()
    app=create_app(Settings.from_env(ROOT,root))
    connection=sqlite3.connect('file:'+str(root/'foundry.sqlite3')+'?mode=ro',uri=True)
    captured=[]
    for run_id,project_id,blocks in connection.execute('select run_id,project_id,blockers_json from character_creation_runs'):
        blockers=json.loads(blocks)
        if not blockers or not any(b.get('details',{}).get('gm_candidate_capsule') for b in blockers):continue
        context=app.state.character_creation.load_candidate_gm_context(run_id)
        doc=context['owner_character_sheet']
        occurrences=doc['path_and_subpath']['earned_feature_occurrences']
        parent=next(r['parent_record_id'] for r in occurrences if r.get('parent_record_id') in (NINE,FURNACE))
        cl=int(doc['identity']['cultivation_level'])
        assert all(r['source_backed'] and r['acquisition_event_hash'] and r['attainment_event_hash'] for r in occurrences if r.get('parent_record_id')==parent)
        proof={'parent':parent,'cl':cl,'document':doc,'document_sha256':canonical_sha256(doc),'validated_native_capsule':1,
               'run_id':run_id,'project_id':project_id,'gm_blocker_codes':[b['code'] for b in blockers],
               'capsule':next(b['details']['gm_candidate_capsule'] for b in blockers if b.get('details',{}).get('gm_candidate_capsule'))}
        EVIDENCE.mkdir(parents=True,exist_ok=True)
        (EVIDENCE/(parent.rsplit('.',1)[-1]+'-cl'+str(cl)+'-acquisition.json')).write_text(json.dumps(proof,sort_keys=True))
        captured.append((parent,cl))
    connection.close()
    assert set(captured)=={(NINE,10),(NINE,14),(NINE,18),(FURNACE,3)}
