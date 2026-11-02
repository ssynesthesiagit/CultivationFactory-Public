"""Native recorded Path powering reaches acquired-source journey combat."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT,sheet
from tests.test_mgr_cremation_native import verify,PARENT
from tests.worker2_support import settle,turn


@pytest.mark.parametrize('continued',[False,True],ids=['initial-journey','continued-journey'])
def test_native_recorded_stamina_power_does_not_become_qi_from_primary_pool(tmp_path,monkeypatch,continued):
    # The real Powering store accepts installed character UUIDs, not display aliases.
    project='c1c1c1c1';other='b2b2b2b2';a='actor:factory.'+project;b='actor:factory.'+other
    document=sheet(['FIRE_TAL_FIREBALL_ART','tianxia.path.qi_cultivation.feature.qi_sensing'],cl=6,name='Wren',key='CHA',dc=50)
    target=sheet(['FIRE_TAL_FLAME_LASH','tianxia.path.qi_cultivation.feature.qi_sensing'],cl=6,name='Mara',key='CHA')
    document['path_and_subpath'].update(path_record_id='tianxia.path.qi_cultivation',path_record_ids=['tianxia.path.qi_cultivation','tianxia.path.body_refining'],paths=[{'path_id':'tianxia.path.qi_cultivation','attainment':3},{'path_id':'tianxia.path.body_refining','attainment':3}])
    document['ability_scores_and_statistics']['primary_resource']={'name':'Qi','maximum':100,'definitions':[{'name':'Stamina','maximum':100}]}
    target['ability_scores_and_statistics']['hit_points']['maximum']=500
    docs={project:document,other:target}
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:docs[pid])
    arena={'display_name':'Cremation courtyard','stable_id':'battlefield:cremation-power','width_squares':16,'height_squares':16,'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':arena})
    def cold():return CombatService(ROOT,tmp_path)
    table=TabletopService(cold(),tmp_path)
    library=table._bundle_and_summary(project)[1]
    choices={source:'stamina' for source in library['powering']['choices'] if '.FIRE_TAL_FIREBALL_ART' in source}
    assert choices
    table.save_powering(project,{'choices':choices})
    state=cold().create_journey(project_ids=[project,other],arena_id='scene',positions={a:{'x':3,'y':3},b:{'x':6,'y':3}},base_paces={a:100,b:100})
    initial=next(row for row in state['actors'][a]['bundle']['action_catalog'] if row['source_definition_id'].endswith('.FIRE_TAL_FIREBALL_ART'))
    assert dict(initial['costs'])=={'resource:core.stamina':5}
    jid=state['journey_id']
    state=cold().journey_world_fact(jid,state['revision'],{'source':PARENT,'subject':a,'kind':'source_access','scope':'access','value':{'variant':PARENT,'route':'direct','source_rule':'The table owner grants legal direct entry to this Qi 3 / Body 3 cultivator.'},'expires_at':2592000,'readers':[a]})
    state=cold().journey_acquire_source(jid,state['revision'],a,PARENT,{'access_scope':'access'})
    assert cold().journey_state(jid)==state
    if continued:
        state=cold().journey_act(jid,state['revision'],a,'finish',{})
        assert cold().journey_state(jid)==state
        state=cold().create_journey(project_ids=[project,other],arena_id='scene',positions={a:{'x':3,'y':3},b:{'x':6,'y':3}},base_paces={a:100,b:100})
        assert state['journey_id']!=jid
        jid=state['journey_id']
        assert cold().journey_state(jid)==state
        restored=next(row for row in state['actors'][a]['bundle']['action_catalog'] if row['source_definition_id'].endswith('.FIRE_TAL_FIREBALL_ART'))
        assert dict(restored['costs'])=={'resource:core.stamina':5}
    mid=cold().journey_start_combat(jid,state['revision'],{a:'team:a',b:'team:b'})['match_id']
    t=TabletopService(cold(),tmp_path);turn(t,mid,a)
    cast=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    prompts=settle(t,mid,cast.candidate_id)
    engine=verify(cold,mid)
    assert not any('Cremation Touch' in str(prompt) for prompt in prompts)
    assert engine.state.actors[a].resources['resource:core.stamina']==95
    assert engine.state.actors[a].resources['resource:core.qi']==100
    action=engine.action_catalog[cast.source_definition_id]
    assert action.parameters['typed']['technique_alignment']['resource_id']=='resource:core.stamina'
    assert action.parameters['typed']['qi_powered'] is False
