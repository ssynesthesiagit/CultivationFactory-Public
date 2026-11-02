"""Native Body rest and work producers consumed by acquired Goruden characters."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT,sheet
from tests.test_mgr_t14_goruden_build import acquire


def journey(catalog_environment,monkeypatch,tmp_path):
    acquired=acquire(catalog_environment,monkeypatch,cl=15)
    owner='actor:factory.gold';other='actor:factory.other'
    for pid,doc in [('gold',acquired),('other',sheet([],cl=18))]:
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    def cold():return CombatService(ROOT,tmp_path)
    cold().tabletop_maps.save({'display_name':'Rest courtyard','width_squares':20,'height_squares':20,'terrain':[]})
    arena=next(k for k,v in cold().factory_arenas().items() if v['display_name']=='Rest courtyard')
    state=cold().create_journey(project_ids=['gold','other'],arena_id=arena,
        positions={owner:{'x':3,'y':6},other:{'x':4,'y':6}},base_paces={owner:30,other:30})
    jid=state['journey_id']
    def act(kind,payload=None,aid=owner):
        before=cold().journey_state(jid)
        if kind=='goruden_aura':
            # Use the actual Bonus Action and recipient transport, not the
            # retired staging-only journey command.
            from combat.tabletop_service import TabletopService
            from tests.worker2_support import candidate,settle,reload,turn
            from tests.test_mgr_t14_goruden import ready
            result=cold().journey_start_scene(jid,before['revision'],{a:'team:rest.party' for a in before['actors']})
            mid=result['match_id'];table=TabletopService(cold(),tmp_path)
            ready(table,tmp_path,mid);turn(table,mid,aid)
            settle(table,mid,candidate(cold(),mid,'Golden Aura').candidate_id)
            for _ in range(10):
                if reload(tmp_path,mid).state.terminal_result is not None:break
                settle(table,mid,table.state(mid)['menu']['end_turn'])
            assert reload(tmp_path,mid).state.terminal_result is not None
            result=cold().journey_resume(jid,cold().journey_state(jid)['revision'])
        else:
            result=cold().journey_act(jid,before['revision'],aid,kind,payload or {})
        assert result==cold().journey_state(jid)
        assert cold().journey_verify(jid)['status']=='PASS'
        return result
    return cold,jid,owner,other,state,act


def test_acquired_native_rest_clocks_choices_limits_and_inert_controls(catalog_environment,monkeypatch,tmp_path):
    from combat.ext.goruden_journey import FAMILY
    cold,jid,owner,other,state,act=journey(catalog_environment,monkeypatch,tmp_path)
    pool='resource:core.stamina'
    maximum=next(p['maximum'] for p in state['actors'][owner]['bundle']['actor_template']['resources'] if p['resource_id']==pool)
    assert maximum>0 and maximum%5==0
    assert state['actors'][owner]['resources'][pool]==maximum
    initial_other=state['actors'][other]['resources'].copy()
    # Genuine source activation pays the actual compiled costs and use token.
    while state['actors'][owner]['resources'][pool]>0:
        state=act('goruden_aura',{})
        if state['actors'][owner]['resources'][pool]>0:
            state=cold().journey_end_scene(jid,state['revision'],'The completed defensive training bout ends; the next separate bout begins.')
            assert cold().journey_verify(jid)['status']=='PASS'
    assert state['actors'][owner]['resources'][pool]==0
    assert state['actors'][owner]['exhaustion']==1
    scene_pools={k:v for k,v in state['actors'][owner]['resources'].items() if k.startswith('resource:uses.')}
    maximum=next(p['maximum'] for p in state['actors'][owner]['bundle']['actor_template']['resources'] if p['resource_id']==pool)
    state=act('short_rest')
    assert state['seconds']==3600
    assert state['actors'][owner]['resources'][pool]==0  # recovery is optional
    state=act('goruden_short_recovery',{'recover':0})
    assert state['actors'][owner]['source_states'][FAMILY].get('short_recoveries',0)==0
    for use in (1,2):
        state=act('short_rest')
        state=act('goruden_short_recovery',{'recover':1})
        assert state['actors'][owner]['resources'][pool]==min(maximum,use*(maximum//2))
        assert state['actors'][owner]['source_states'][FAMILY]['short_recoveries']==use
    act('short_rest')
    with pytest.raises(ValueError,match='recovery|recover'):
        act('goruden_short_recovery',{'recover':1})
    state=act('short_rest',aid=other)
    assert state['actors'][other]['resources']==initial_other
    assert FAMILY not in state['actors'][other].get('source_states',{})
    state=act('long_rest')
    assert state['actors'][owner]['resources'][pool]==maximum
    assert {k:state['actors'][owner]['resources'][k] for k in scene_pools}==scene_pools
    assert state['actors'][owner]['source_states'][FAMILY]['short_recoveries']==0


def test_full_cultivation_requires_actual_uninterrupted_work(catalog_environment,monkeypatch,tmp_path):
    from combat.ext.goruden_journey import FAMILY
    cold,jid,owner,other,state,act=journey(catalog_environment,monkeypatch,tmp_path)
    source=FAMILY+'.cultivation_session';pool='resource:core.stamina'
    maximum=next(p['maximum'] for p in state['actors'][owner]['bundle']['actor_template']['resources'] if p['resource_id']==pool)
    state=act('goruden_aura',{})
    depleted=state['actors'][owner]['resources'][pool]
    assert depleted==maximum-5
    state=act('activity_start',{'source':source,'parameters':{}})
    state=act('activity_work',{'seconds':3600})
    assert state['actors'][owner]['resources'][pool]==depleted
    state=act('wait',{'seconds':1})
    assert 'journey:activity' not in state['actors'][owner]['source_states']
    with pytest.raises(ValueError):act('activity_work',{'seconds':3600})
    act('activity_start',{'source':source,'parameters':{}})
    state=act('activity_work',{'seconds':7200})
    assert state['actors'][owner]['resources'][pool]==maximum
    assert state['actors'][owner]['source_states'][FAMILY]['cultivation_used']==1
    with pytest.raises(ValueError):act('activity_start',{'source':source,'parameters':{}})
    with pytest.raises(ValueError):act('activity_start',{'source':source,'parameters':{}},aid=other)
    state=act('long_rest')
    assert state['actors'][owner]['source_states'][FAMILY]['cultivation_used']==0
    state=act('activity_start',{'source':source,'parameters':{}})
    assert state['actors'][owner]['source_states']['journey:activity']['worked_seconds']==0
