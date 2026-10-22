"""Focused regressions for the Hearthfire review findings."""
from combat import senses
from combat.gate2_runtime_models import Position
from combat.illumination import perceived_level
from tests.test_mgr_t14_hearthfire_light import scene
from tests.test_mgr_t14_hearthfire_native import begin_combat, journey, kindle
from tests.worker2_support import FOE, OWNER, fixture, reload


def test_expired_environment_speed_penalty_is_absent_after_commit_and_reload(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b)
    state=act('hearth_hardship',{'cause':'smoke','ordinary':True,'source_cl':0,'levels':0,
        'penalty':{'speed_penalty_ft':10},'record_id':'smoke:timed','authority':'controller',
        'expires_at':120,'visibility':'subject'},b)
    condition_id=state['actors'][b]['hearthfire']['hardships'][0]['condition_instance_id']
    assert condition_id in state['actors'][b]['encounter_snapshot']['conditions']
    state=act('wait',{'seconds':120})
    assert condition_id not in state['actors'][b]['encounter_snapshot']['conditions']
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert condition_id not in loaded.engine.state.actors[b].conditions


def travel_recovery_options(cold,jid,actor):
    return [o for o in cold().journey_menu(jid,actor)['options']
            if o['kind']=='hearth_recovery' and o['payload'].get('benefit')=='exhaustion:travel']


def test_short_rest_travel_ledger_does_not_recount_healed_levels(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    kindle(act,a,b)
    act('travel_exhaustion',{'levels':2,'ordinary':True},b)
    state=act('hearth_short_rest',{},b)
    assert state['actors'][b]['hearthfire']['travel_exhaustion_levels']==2
    state=act('hearth_recovery',{'benefit':'exhaustion:travel'},b)
    assert state['actors'][b]['exhaustion']==1
    assert state['actors'][b]['hearthfire']['travel_exhaustion_levels']==1
    # A later, non-travel hardship raises total Exhaustion after the long rest
    # recharged Homefire Recovery. Only the one remaining travel level may be
    # healed; the already-healed travel level must not be credited again.
    act('long_rest',{},b)
    kindle(act,a,b)
    state=act('hearth_hardship',{'cause':'smoke','ordinary':True,'source_cl':0,'levels':2,
        'record_id':'smoke:hardship','authority':'controller','expires_at':100000,'visibility':'subject'},b)
    assert state['actors'][b]['exhaustion']==3
    state=act('hearth_short_rest',{},b)
    assert state['actors'][b]['hearthfire']['travel_exhaustion_levels']==1, (
        'the short rest recounted travel history and re-credited a healed level')
    options=travel_recovery_options(cold,jid,b)
    assert len(options)==1
    state=act('hearth_recovery',{'benefit':'exhaustion:travel'},b)
    assert state['actors'][b]['exhaustion']==2
    assert state['actors'][b]['hearthfire']['travel_exhaustion_levels']==0
    # With every travel level healed, a further rest must not offer the travel
    # benefit again while hardship Exhaustion remains.
    act('long_rest',{},b)
    kindle(act,a,b)
    state=act('hearth_short_rest',{},b)
    assert state['actors'][b]['exhaustion']==2
    assert state['actors'][b]['hearthfire']['travel_exhaustion_levels']==0
    assert travel_recovery_options(cold,jid,b)==[], 'no healed travel level may be offered twice'


def test_truesight_darkness_classification_and_range_apply_to_ambient_darkness(tmp_path):
    _,_,mid=fixture(tmp_path,[],battlefield=scene(tmp_path),seed='DARKNESS-SENSE')
    engine=reload(tmp_path,mid)
    viewer=engine.state.actors[OWNER]
    target=engine.state.actors[FOE]
    engine._apply_condition(viewer,senses.SENSE,'test:truesight-darkness',OWNER,expires_on='UNTIL_REMOVED',
        data={'sense':'truesight_darkness','range_ft':30})
    target.position=Position(x=9,y=6)
    assert perceived_level(engine,viewer,target)=='DIM'
    target.position=Position(x=10,y=6)
    assert perceived_level(engine,viewer,target)=='DARKNESS'
