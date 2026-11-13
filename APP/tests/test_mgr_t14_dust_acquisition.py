"""Provider-free acquisition through the real seeded build and installed match.

No feature or trigger receipt is manufactured. The sealed parent choice enters
CharacterBuilder, the native walk, Stage 2, projection and portable installation.
"""
from pathlib import Path
import os
import pytest
from app.api import create_app
from app.core import Settings
from product_bootstrap.service import ProductBootstrapService
from combat.gate2_runtime_content import AN
from combat.tabletop_service import TabletopService
from tests.test_mgr_t14_dust_family import ALL

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.environ.get('DUST_BROWSER_ACCEPTANCE')!='1',
    reason='Lead-only installed-play acceptance: set DUST_BROWSER_ACCEPTANCE=1 outside the sandbox; requires /usr/bin/chromium.')
def test_native_dust_acquisition_to_installed_combat(tmp_path,monkeypatch):
    from ai_provider.service import AIProviderService
    def forbidden(*args,**kwargs):
        raise AssertionError('No model transport is allowed in seeded acquisition')
    monkeypatch.setattr(AIProviderService,'complete_json',forbidden)
    monkeypatch.setenv('TIANXIA_BROWSER_EXECUTABLE','/usr/bin/chromium')
    settings=Settings.from_env(ROOT,tmp_path/'userdata')
    ProductBootstrapService(settings).run()
    import httpx
    from ai_provider.secrets import InMemorySecretStore
    app=create_app(settings,ai_transport=httpx.MockTransport(forbidden),ai_secret_store=InMemorySecretStore())
    built=app.state.character_builder.create_project(
        working_name='Dust Cultivator',concept='An open-school dust cultivator.',
        target_cl=18,power_band='standard',source_reference=None,creation_mode='detailed',
        ability_scores={},generation_route='ai_bootstrap',autogen_seed='DUST-NATIVE-18',
        selections={'path_choice':['tianxia.path.qi_cultivation'],
                    'subpath_choice':['tianxia.subpath.qi.dust_cultivator']})
    pid=built['project_id']
    app.state.character_builder.commit_normal_first_cycle_catalog_choices(pid)
    run=app.state.character_creation.start(pid,execution_mode='STANDARD_API',
        idempotency_key='dust-native-full-progression',controller_route='DETERMINISTIC_CREATIVE_CONTROLLER',combat_ready=True)
    assert run['status']=='READY_FOR_REVIEW', {'status':run['status'],'blockers':run.get('blockers')}
    final=app.state.character_creation.finalize(run['run_id'])
    assert final['status']=='CLEAN_AND_FINALIZED',final.get('blockers')
    combat=app.state.combat
    owner='actor:factory.'+pid
    saved=combat.tabletop_maps.save({'display_name':'Acquired Dust courtyard','width_squares':32,'height_squares':16,
        'walls':[],'terrain':[],
        'world_sources':[{'id':'smoke-remover','name':'Authored smoke removal field','shape':'sphere',
            'x':12,'y':6,'z':0,'size_ft':30,'height_ft':30,'source_cl':18,'save_dc':20,'check_bonus':60,
            'removes':['smoke'],'targets':'both','duration_rounds':10,'cadence_rounds':1,
            'source_rule':'Removes smoke throughout this sphere; cultivated fields contest once each round.'}],
        'starts':{'team1':[[3,6]],'team2':[[4,6]]},
        'objects':[{'id':1,'kind':'wall_section','name':'Five-foot earth section','x':7,'y':6,
            'material':'earth','authored_material':True,'source_cl':0,'ac':10,'hp':40,'height_ft':5,
            'threshold':99,'resist':['FORCE']}]})
    match=combat.create_factory_match(project_ids=[pid],opponent_actor_ids=[AN],
        control_modes={owner:'MANUAL',AN:'MANUAL'},arena_id='battlefield:map.'+saved['map_id'],match_seed='DUST-NATIVE-INSTALLED')
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
    # F1 through the acquired source: smoke alone qualifies for whole-cloud removal.
    from tests.worker2_support import settle
    from combat.placement_menu import CHOICE as PLACE
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    # Aim around the independent earth section; the whole cloud still fits
    # within the removal sphere (20-foot center offset plus 10-foot radius).
    settle(table,mid,action('Dust Cloud'),picks={PLACE:cell_id(Position(x=12,y=10),include_altitude=True)})
    loaded=combat._load_session(mid)
    assert loaded.verify()['status']=='PASS' and loaded.mechanical.replay()['status']=='PASS'
    assert not any(z.active and 'dust_cloud' in z.source_definition_id for z in loaded.engine.state.zones.values())
    assert any(v.event_type=='CHECK_ROLLED' and v.source_definition_id=='world:smoke-remover' for v in loaded.engine.events)
    next_turn()
    # The real Qi chassis owns Potency, but fixed 40 damage has no damage roll.
    assert any(int((a.parameters.get('typed',{}).get('numbers') or {}).get('potency') or 0)>0
        for a in combat._load_session(mid).engine.action_catalog.values() if a.owner_id==owner)
    obj=next(o for o in combat._load_session(mid).engine.state.objects.values()
             if o.component.get('name')=='Five-foot earth section')
    assert obj.component['source_cl']==0
    e=commit(action('Dust to Dust: Crumble Matter',obj.object_id))
    damage=[v for v in e.events if v.event_type=='OBJECT_UPDATED' and v.target_ids==(obj.object_id,) and 'damage' in v.payload]
    assert len(damage)==1 and damage[0].payload['damage']['taken']==40
    assert e.state.objects[obj.object_id].destroyed and (7,6) not in e.grid.blocked
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

    from combat.ext.qi_subpaths_dust import FREE_CHOKING
    assert e.state.actors[owner].turn_flags.get(FREE_CHOKING)
    turns=e.state.actors[owner].turns_started
    e=commit(table.state(mid)['menu']['end_turn'])
    assert e.state.actors[owner].turns_started==turns
    assert FREE_CHOKING not in e.state.actors[owner].turn_flags


def test_legacy_view_validation_keeps_retired_playbooks_absent():
    import zipfile
    import json
    from jsonschema import Draft202012Validator
    from factory_authoring.command5_profile import CharacterGMCommand5Profile
    with zipfile.ZipFile(ROOT/'BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip') as bundle:
        name=next(n for n in bundle.namelist() if n.endswith('/04_SCHEMAS/gm_character_view_model.schema.json'))
        schema=json.loads(bundle.read(name))
    view={'schema_version':'Tianxia_GM_Character_View_Model_v2'}
    adapted=CharacterGMCommand5Profile._pinned_view_validation_payload(view,schema)
    assert adapted['composites']==[] and 'composites' not in view
    errors=list(Draft202012Validator(schema).iter_errors(adapted))
    assert errors and all(e.message!="'composites' is a required property" for e in errors)
    assert any(e.validator=='required' for e in errors)  # Other omissions still fail.
    explicit={**view,'composites':'invalid'}
    assert CharacterGMCommand5Profile._pinned_view_validation_payload(explicit,schema) is explicit
    assert any(e.path and e.path[0]=='composites' for e in Draft202012Validator(schema).iter_errors(explicit))
    assert CharacterGMCommand5Profile._pinned_view_validation_payload(view,{}) is view
