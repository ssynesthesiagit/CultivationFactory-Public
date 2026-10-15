"""Source acquisition -> native table choices -> committed state -> cold replay.

No owner feature rows or trigger receipts are inserted in the engine. Scenario
opponents remain ordinary separately compiled creatures. All transport is local.
"""
import copy
import json
import zipfile
import pytest
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
        assert [b['code'] for b in run['blockers']]==['COMMAND6_CHARACTER_GM_CONSUMER_FAILED'], run['blockers']
    doc=app.state.character_creation.load_candidate_gm_context(run['run_id'])['owner_character_sheet']
    earned=[r for r in doc['path_and_subpath']['earned_feature_occurrences'] if r.get('parent_record_id')==parent]
    expected=(['star_lit_acupoints','orbital_body','falling_star_descent','constellation_circuit','nine_star_incarnation']
              if parent==NINE else ['five_viscera_circuit','refine_the_impure','twin_furnace_circulation','fivefold_organ_harmony','inner_cosmos_furnace'])
    assert {r['feature_id'] for r in earned}=={parent+'.feature.'+name for level,name in zip((3,6,10,14,18),expected) if cl>=level}
    assert all(r['source_backed'] and r['source_packet_ids'] and r['acquisition_event_hash'] and r['attainment_event_hash'] for r in earned)
    cache[key]=copy.deepcopy(doc)
    return doc


def installed(root,aid,doc):
    folder=root/'portable_characters'/aid.removeprefix('actor:factory.')
    folder.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))


def game(root,doc,seed='BODY-MODES',ask=True):
    installed(root,OWNER,doc)
    installed(root,FOE,c7.sheet([],cl=18,name='Sparring opponent'))
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
