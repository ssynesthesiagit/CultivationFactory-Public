"""Real frozen-source acquisition into native play; no ownership fixture grants.

The seeded native Character Builder chooses and validates the complete build.
Only the external browser consumer is forbidden by this lane's instructions;
its actual compiled candidate sheet is consumed unchanged by native play.
"""
import json
import zipfile
from pathlib import Path
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.qi_subpaths_five import CLOUD
from combat.flight import horizontal_jump_feet,profile
from tests.h1_support import ROOT
from tests.worker2_support import settle,turn

SOURCE='tianxia.subpath.qi.cloud_walker'
QI='resource:core.qi'
A='actor:factory.nativewalker'
FEATURES=['light_as_a_feather','cloud_step','wind_walk','heavenly_leap','cloud_immortal']


class ForbiddenTransport:
    def status(self):return {'ready':False,'provider_id':'forbidden-test-transport'}
    def complete_json(self,**kwargs):raise AssertionError('Seeded build invoked model transport')
    def __getattr__(self,name):
        raise AssertionError('This seeded native build must not invoke model transport: '+name)


@pytest.fixture(scope='session')
def acquired_sheet(catalog_environment, tmp_path_factory):
    from app.api import create_app
    import os
    evidence=Path(os.environ.get('CF_CLOUD_EVIDENCE') or tmp_path_factory.getbasetemp()/'cloud-acquisition-evidence')
    evidence.mkdir(parents=True,exist_ok=True)
    previous=os.environ.get('TIANXIA_BROWSER_EXECUTABLE')
    os.environ['TIANXIA_BROWSER_EXECUTABLE']=str(evidence/'BROWSER_FORBIDDEN')
    try:
        app=create_app(catalog_environment['settings'])
        app.state.character_creation.provider=ForbiddenTransport()
        builder=app.state.character_builder
        created=builder.create_project(working_name='Native Cloud Walker',
            concept='An Open School Cloud Walker courier and rescuer.',target_cl=18,power_band='standard',
            source_reference=None,creation_mode='detailed',generation_route='ai_bootstrap',
            ability_scores={},autogen_seed='CW-T14-NATIVE-18',
            selections={'path_choice':['tianxia.path.qi_cultivation'],'subpath_choice':[SOURCE]},
            method_planning_mode='AUTO')
        pid=created['project_id']
        builder.commit_normal_first_cycle_catalog_choices(pid)
        run=app.state.character_creation.start(pid,execution_mode='STANDARD_API',
            idempotency_key='cloud-walker-native-acquisition-18',controller_route='DETERMINISTIC_CREATIVE_CONTROLLER')
        (evidence/'acquisition-result.json').write_text(json.dumps({
            'project_id':pid,'run_id':run['run_id'],'status':run['status'],
            'blockers':run.get('blockers',[]),'provider_called':False,
            'source_sha256':{str(f):__import__('hashlib').sha256(f.read_bytes()).hexdigest()
                for f in [ROOT/'combat/ext/cloud_walker.py',ROOT/'combat/ext/cloud_walker_environment.py',
                          ROOT/'combat/flight.py',ROOT/'combat/journey.py',ROOT/'combat/gate5_service.py']}},indent=2)+'\n')
        if run['status']!='READY_FOR_REVIEW':
            assert run['status']=='NEEDS_REVIEW',run
            blockers=run.get('blockers',[])
            assert len(blockers)==1 and blockers[0]['code']=='COMMAND6_CHARACTER_GM_CONSUMER_FAILED',blockers
            harness=blockers[0]['details']['consumer_report']['harness_run']
            assert harness['skipped'] is True and harness['exit_code'] is None
        sheet=app.state.character_creation.load_candidate_gm_context(run['run_id'])['owner_character_sheet']
        assert sheet['identity']['cultivation_level']==18
        from combat.factory_compiler import compile_character
        bundle=compile_character(sheet,actor_id=A)
        owned=next(r['features'] for r in bundle['typed_passives'] if r.get('block')=='cloud_walker')
        assert set(owned)=={CLOUD+f for f in FEATURES}
        (evidence/'acquired-cloud-walker-sheet.json').write_text(json.dumps(sheet,indent=2)+'\n')
        return sheet
    finally:
        if previous is None:os.environ.pop('TIANXIA_BROWSER_EXECUTABLE',None)
        else:os.environ['TIANXIA_BROWSER_EXECUTABLE']=previous


def assert_native_qi_payment(engine,before,since,source,gross):
    """Validate printed debits and the real CL11 Path's separately sourced refund."""
    events=engine.events[since:]
    spends=[e for e in events if e.event_type=='RESOURCE_SPENT' and e.actor_id==A
            and e.payload.get('resource_id')==QI]
    assert sum(e.payload['amount'] for e in spends)==gross
    assert all(e.source_definition_id.endswith(source) for e in spends)
    gains=[e for e in events if e.event_type=='RESOURCE_GAINED' and e.actor_id==A
           and e.payload.get('resource_id')==QI]
    assert [(e.source_definition_id,e.payload['gained']) for e in gains]==[
        ('passive:tianxia.path.qi_cultivation.feature.golden_core_efficiency',1)]
    assert engine.state.actors[A].resources[QI]==before-gross+1


def native_service(tmp_path,doc):
    folder=tmp_path/'portable_characters'/'nativewalker';folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    c=CombatService(ROOT,tmp_path)
    c.tabletop_maps.save({'display_name':'Acquired Cloud Walker yard','width_squares':12,'height_squares':14,
        'walls':[],'starts':{'team1':[[3,6]],'team2':[[6,6]]}})
    return c


def test_real_acquisition_native_table_and_cold_replay(tmp_path,acquired_sheet):
    from combat.gate2_runtime_content import AN
    c=native_service(tmp_path,acquired_sheet)
    result=c.create_factory_match(project_ids=['nativewalker'],opponent_actor_ids=[AN],
        arena_id='battlefield:map.acquired-cloud-walker-yard',match_seed='CLOUD-NATIVE-ACQUIRED',
        control_modes={A:'MANUAL',AN:'MANUAL'})
    mid=result['match_id'];t=TabletopService(c,tmp_path)
    turn(t,mid,A)
    e=c._load_session(mid).engine;actor=e.state.actors[A]
    assert horizontal_jump_feet(e,actor)==actor.strength_score//2*3
    for source,cost,speed in [('cloud_step',2,20),('heavenly_leap',3,None),('cloud_immortal',8,60)]:
        turn(t,mid,A)
        e=c._load_session(mid).engine
        before=e.state.actors[A].resources[QI];since=len(e.events)
        action=next(row for row in e.legal_candidates()
            if e.action_catalog.get(row.source_definition_id)
            and (e.action_catalog[row.source_definition_id].parameters.get('typed') or {}).get('source')==CLOUD+source)
        settle(t,mid,action.candidate_id,choices={'choice:needle.cloud_leap_destination':'first'})
        cold=CombatService(ROOT,tmp_path)._load_session(mid)
        assert_native_qi_payment(cold.engine,before,since,CLOUD+source,cost)
        if speed is not None:assert profile(cold.engine,cold.engine.state.actors[A]).speed_ft==speed
        assert cold.verify()['status']==cold.mechanical.replay()['status']=='PASS'
        settle(t,mid,t.state(mid)['menu']['end_turn'])


def test_real_acquisition_native_ritual_clock_and_expiry(tmp_path,acquired_sheet):
    c=native_service(tmp_path,acquired_sheet)
    state=c.create_journey(project_ids=['nativewalker'],arena_id='battlefield:map.acquired-cloud-walker-yard',
        positions={A:{'x':3,'y':6}},base_paces={A:18000})
    jid=state['journey_id'];before=state['actors'][A]['resources'][QI]
    for kind,payload in [('cloud_wind_begin',{}),('wait',{'seconds':600}),('cloud_wind_finish',{})]:
        c=CombatService(ROOT,tmp_path);state=c.journey_state(jid)
        state=c.journey_act(jid,state['revision'],A,kind,payload)
    assert state['actors'][A]['resources'][QI]==before-5
    assert CLOUD+'wind_walk' in state['actors'][A]['travel_effects']
    state=CombatService(ROOT,tmp_path).journey_act(jid,state['revision'],A,'wait',{'seconds':3599})
    assert CLOUD+'wind_walk' in state['actors'][A]['travel_effects']
    state=CombatService(ROOT,tmp_path).journey_act(jid,state['revision'],A,'wait',{'seconds':1})
    assert CLOUD+'wind_walk' not in state['actors'][A]['travel_effects']
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state


def test_real_acquired_immortal_use_requires_explicit_native_scene_end(tmp_path,acquired_sheet):
    from tests.h1_support import sheet
    c=native_service(tmp_path,acquired_sheet)
    bid='actor:factory.scene-companion'
    folder=tmp_path/'portable_characters'/'scene-companion';folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(sheet([],cl=1,name='Scene companion')))
    state=c.create_journey(project_ids=['nativewalker','scene-companion'],arena_id='battlefield:map.acquired-cloud-walker-yard',
        positions={A:{'x':3,'y':6},bid:{'x':6,'y':6}},base_paces={A:18000,bid:18000})
    jid=state['journey_id']
    pool=next(rid for action in state['actors'][A]['bundle']['action_catalog']
        if action.get('parameters',{}).get('typed',{}).get('source')==CLOUD+'cloud_immortal'
        for rid,amount in action['costs'] if rid.startswith('resource:uses.'))
    result=c.journey_start_combat(jid,state['revision'],{A:'team:a',bid:'team:b'},maximum_rounds=11)
    mid=result['match_id'];t=TabletopService(c,tmp_path);turn(t,mid,A)
    def immortal(engine):
        return [row for row in engine.legal_candidates() if engine.action_catalog.get(row.source_definition_id)
            and engine.action_catalog[row.source_definition_id].parameters.get('typed',{}).get('source')==CLOUD+'cloud_immortal']
    settle(t,mid,immortal(c._load_session(mid).engine)[0].candidate_id)
    assert CombatService(ROOT,tmp_path)._load_session(mid).engine.state.actors[A].resources[pool]==0
    # Allow the actual minute to expire under the native round/slot clock.
    for _ in range(12*len(c._load_session(mid).engine.state.initiative_order)):
        fresh=CombatService(ROOT,tmp_path);session=fresh._load_session(mid)
        if session.engine.state.terminal_result is not None:break
        if session.engine.state.current_actor_id==A:assert not immortal(session.engine)
        t=TabletopService(fresh,tmp_path);settle(t,mid,t.state(mid)['menu']['end_turn'])
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.engine.state.terminal_result is not None
    assert not any(row.condition_id=='condition:typed.cloud_walker_form' for row in session.engine.state.actors[A].conditions.values())
    assert session.verify()['status']==session.mechanical.replay()['status']=='PASS'
    c=CombatService(ROOT,tmp_path);state=c.journey_state(jid)
    state=c.journey_resume(jid,state['revision'])
    assert state['actors'][A]['resources'][pool]==0
    state=c.journey_act(jid,state['revision'],A,'wait',{'seconds':60})
    assert state['actors'][A]['resources'][pool]==0
    before=state['actors'][A]['resources'][QI]
    state=c.journey_end_scene(jid,state['revision'],'The rescue is finished and the party reaches its safe destination.')
    assert state['actors'][A]['resources'][pool]==1
    assert state['actors'][A]['resources'][QI]==before
    assert state['events'][-1]['kind']=='SCENE_ENDED' and state['events'][-1]['authority']=='table_owner'
    result=c.journey_start_combat(jid,state['revision'],{A:'team:a',bid:'team:b'},maximum_rounds=1)
    mid=result['match_id'];t=TabletopService(c,tmp_path);turn(t,mid,A)
    e=c._load_session(mid).engine;since=len(e.events)
    settle(t,mid,immortal(e)[0].candidate_id)
    final=CombatService(ROOT,tmp_path)._load_session(mid)
    assert final.engine.state.actors[A].resources[pool]==0
    assert_native_qi_payment(final.engine,before,since,CLOUD+'cloud_immortal',8)
    assert final.verify()['status']==final.mechanical.replay()['status']=='PASS'
