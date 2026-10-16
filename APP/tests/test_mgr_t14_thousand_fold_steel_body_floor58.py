"""Thousand-Fold native acquisition, committed choices and cold mechanical replay."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from app.api import create_app
from combat.ext import steel_forms
from combat.gate5_service import CombatService
from tests.test_body_modes_native import game, advance, play, strike_name

PARENT='tianxia.subpath.body.thousand_fold_steel_body'
FEATURES=dict(zip((3,6,10,14,18),('body_forged_in_three_forms','quench_the_impact','folded_edge_hidden_spine','ten_thousand_reforgings','body_beyond_the_hammer')))
OWNER='actor:factory.11111111-1111-4111-8111-111111111111'
FOE='actor:factory.22222222-2222-4222-8222-222222222222'
EVIDENCE=Path('/var/tmp/auto-audit/fix/MGR-T14-ling-seam-thousand-fold-steel-body-4-evidence')


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
    doc=app.state.character_creation.load_candidate_gm_context(run['run_id'])['owner_character_sheet']
    earned=[r for r in doc['path_and_subpath']['earned_feature_occurrences'] if r.get('parent_record_id')==PARENT]
    assert {r['feature_id'] for r in earned}=={PARENT+'.feature.'+n for level,n in FEATURES.items() if level<=cl}
    assert all(r['source_backed'] and r['source_packet_ids'] and r['acquisition_event_hash'] and r['attainment_event_hash'] for r in earned)
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    (EVIDENCE/f'acquisition-cl{cl}.json').write_text(json.dumps({'document':doc,'run_id':run['run_id'],'blockers':run.get('blockers',[])},sort_keys=True))
    cache[cl]=copy.deepcopy(doc)
    return doc


def loaded(service,mid):
    session=CombatService(service.source_root,service.userdata_root)._load_session(mid)
    replay=session.mechanical.replay()
    assert replay['status']=='PASS',replay
    engine=session.engine
    state=engine.state.model_dump(mode='json')
    digest=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest()
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
    assert not any('integrated_con' in c.source_definition_id for c in engine.legal_candidates())
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
