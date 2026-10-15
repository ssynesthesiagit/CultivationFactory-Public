"""Provider-free acquisition through the real seeded build and installed match.

No feature or trigger receipt is manufactured. The sealed parent choice enters
CharacterBuilder, the native walk, Stage 2, projection and portable installation.
"""
from pathlib import Path
from app.api import create_app
from app.core import Settings
from product_bootstrap.service import ProductBootstrapService
from combat.gate2_runtime_content import AN
from combat.tabletop_service import TabletopService
from tests.test_mgr_t14_dust_family import ALL

ROOT=Path(__file__).resolve().parents[1]


def test_native_dust_acquisition_to_installed_combat(tmp_path,monkeypatch):
    from ai_provider.service import AIProviderService
    def forbidden(*args,**kwargs):
        raise AssertionError('No model transport is allowed in seeded acquisition')
    monkeypatch.setattr(AIProviderService,'complete_json',forbidden)
    monkeypatch.setenv('TIANXIA_BROWSER_EXECUTABLE',str(tmp_path/'BROWSER_FORBIDDEN'))
    settings=Settings.from_env(ROOT,tmp_path/'userdata')
    ProductBootstrapService(settings).run()
    app=create_app(settings)
    built=app.state.character_builder.create_project(
        working_name='Dust Cultivator',concept='An open-school dust cultivator.',
        target_cl=18,power_band='standard',source_reference=None,creation_mode='detailed',
        ability_scores={},generation_route='ai_bootstrap',autogen_seed='DUST-NATIVE-18',
        selections={'path_choice':['tianxia.path.qi_cultivation'],
                    'subpath_choice':['tianxia.subpath.qi.dust_cultivator']})
    pid=built['project_id']
    run=app.state.character_creation.start(pid,execution_mode='STANDARD_API',
        idempotency_key='dust-native-full-progression',controller_route='DETERMINISTIC_CREATIVE_CONTROLLER',combat_ready=True)
    assert run['status']=='READY_FOR_REVIEW', {'status':run['status'],'blockers':run.get('blockers')}
    final=app.state.character_creation.finalize(run['run_id'])
    assert final['status']=='CLEAN_AND_FINALIZED',final.get('blockers')
    combat=app.state.combat
    owner='actor:factory.'+pid
    match=combat.create_factory_match(project_ids=[pid],opponent_actor_ids=[AN],
        control_modes={owner:'MANUAL',AN:'MANUAL'},arena_id='battlefield:factory_pillar_arena',match_seed='DUST-NATIVE-INSTALLED')
    mid=match['match_id'];table=TabletopService(combat,settings.data_dir)
    engine=combat._load_session(mid).engine
    sources={a.parameters.get('typed',{}).get('option_of') or a.parameters.get('typed',{}).get('source')
             for a in engine.action_catalog.values() if a.owner_id==owner}
    assert set(ALL)<=sources
    session=combat._load_session(mid)
    assert session.verify()['status']=='PASS'
    assert session.mechanical.replay()['status']=='PASS'
    # Real table intents after acquisition, each reloaded and mechanically replayed.
    def commit(cid):
        answers=[]
        for _ in range(20):
            menu=table.state(mid)['menu']
            result=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers)
            if result['status']=='COMMITTED':
                loaded=combat._load_session(mid)
                assert loaded.verify()['status']=='PASS'
                assert loaded.mechanical.replay()['status']=='PASS'
                return loaded.engine
            assert result['status']=='REACTION_REQUIRED',result
            prompt=result['reaction'];answer={**prompt['context'],'selection':'DECLINE'}
            if prompt.get('choice'):
                choice=prompt['choice']
                picks=choice.get('preferred') or [choice['options'][0]['id']]
                answer.update(selection='USE',option_ids=picks[:max(1,choice.get('minimum_selections',1))])
            answers.append(answer)
        raise AssertionError('Too many native choice checkpoints')
    def turn():
        while table.state(mid)['menu']['actor_id']!=owner:
            commit(table.state(mid)['menu']['end_turn'])
    def action(label,target=None):
        return next(o['candidate_id'] for g in table.state(mid)['menu']['actions'] if g['label']==label
            for o in g['options'] if target is None or target in o.get('target_ids',[]))
    def next_turn():
        commit(table.state(mid)['menu']['end_turn']);turn()
    turn()
    commit(action('Primordial Dust'))
    next_turn()
    e=commit(action('Dust Cloud'))
    assert any(z.active and 'dust_cloud' in z.source_definition_id and not z.concentration_link for z in e.state.zones.values())
    # Defense erosion uses the Action while the cloud uses the Bonus Action.
    commit(action('Dust to Dust: Erode Defense',AN))
    next_turn()
    before=combat._load_session(mid).engine.state.actors[owner].resources['resource:core.qi']
    e=commit(action('Primordial Dust: Choking Dust: Eroding Mode (free)',AN))
    assert e.state.actors[owner].resources['resource:core.qi']==before
    e=commit(action('Sandstorm Field'))
    assert any(z.active and 'sandstorm_field' in z.source_definition_id for z in e.state.zones.values())
