"""Native Open School acquisition boundaries; no manufactured feature receipts."""
from pathlib import Path
import pytest
from app.api import create_app
from app.core import Settings
from product_bootstrap.service import ProductBootstrapService
from combat.gate2_runtime_content import AN
from tests.test_mgr_t14_raincaller_native import ALL,Play
from combat.tabletop_service import TabletopService

ROOT=Path(__file__).resolve().parents[1]
LEVELS=(3,6,10,14,18)

@pytest.mark.parametrize('cl',[2,3,6,10,14,18])
def test_native_earned_progression_has_exact_attained_rows(tmp_path,monkeypatch,cl):
    from ai_provider.service import AIProviderService
    def forbidden(*a,**k):raise AssertionError('Native seeded acquisition cannot request a model transport')
    monkeypatch.setattr(AIProviderService,'complete_json',forbidden)
    settings=Settings.from_env(ROOT,tmp_path/'userdata')
    ProductBootstrapService(settings).run();app=create_app(settings)
    selections={'path_choice':['tianxia.path.qi_cultivation']}
    if cl>=3:selections['subpath_choice']=['tianxia.subpath.qi.raincaller_cultivator']
    built=app.state.character_builder.create_project(working_name=f'Raincaller CL{cl}',concept='An open-school raincaller.',
        target_cl=cl,power_band='standard',source_reference=None,creation_mode='detailed',ability_scores={},
        generation_route='ai_bootstrap',autogen_seed=f'RAIN-EARNED-{cl}',selections=selections)
    pid=built['project_id']
    run=app.state.character_creation.start(pid,execution_mode='STANDARD_API',idempotency_key='rain-earned',
        controller_route='DETERMINISTIC_CREATIVE_CONTROLLER',combat_ready=True)
    assert run['status']=='READY_FOR_REVIEW',run.get('blockers')
    final=app.state.character_creation.finalize(run['run_id'])
    assert final['status']=='CLEAN_AND_FINALIZED',final.get('blockers')
    owner='actor:factory.'+pid;combat=app.state.combat
    match=combat.create_factory_match(project_ids=[pid],opponent_actor_ids=[AN],control_modes={owner:'MANUAL',AN:'MANUAL'},
        arena_id='battlefield:factory_pillar_arena',match_seed=f'RAIN-EARNED-COMBAT-{cl}')
    p=Play(combat,TabletopService(combat,settings.data_dir),match['match_id'],owner,settings.data_dir)
    engine=p.load()
    owned={r['feature_id'] for r in engine.typed_passive_rows.get(owner,()) if r.get('block')=='raincaller_acquired'}
    assert owned=={source for source,level in zip(ALL,LEVELS) if cl>=level}
    sources={(a.parameters.get('typed') or {}).get('source') for a in engine.action_catalog.values() if a.owner_id==owner}
    assert not any(source in sources for source,level in zip(ALL,LEVELS) if cl<level)
    if cl>=3:
        p.cast('Call Rain',{'choice:needle.rain_form':'heavy'} if cl>=6 else {})
        rain=next(z for z in p.load().state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('rain_family')=='call')
        assert bool(rain.trigger_profile['profile']['form'])==(cl>=6)
