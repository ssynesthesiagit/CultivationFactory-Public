"""Final native environmental, decision, Armament and lifecycle paths."""
import pytest
from tests.test_mgr_t14_hearthfire_native import (FEATURES,journey,kindle,weather,begin_combat,candidate,settle,
 test_welcome_no_guest_stable_once_and_outright_guard as verify_rescue)

def test_actual_rescue_move_is_available_at_zero_hp_and_does_not_provoke(tmp_path):
    verify_rescue(tmp_path,True)


@pytest.mark.parametrize('phenomenon',['smoke','cold','heat','rain'])
def test_welcome_environment_without_any_hearth_has_real_world_caller(tmp_path,monkeypatch,phenomenon):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    act('hearth_welcome',{'center':'self','invited':[b]})
    assert not cold().journey_state(jid)['actors'][a]['hearthfire'].get('camp')
    assert any(o['kind']=='hearth_weather' for o in cold().journey_menu(jid,b)['options'])
    state=act('hearth_weather',weather(a,phenomenon=phenomenon),b)
    assert state['events'][-1]['blocked']==1
    assert state['events'][-1]['source'].endswith('.flame_that_welcomes_all')
    assert cold().journey_state(jid)==state
    act('hearth_end_welcome')
    # The separate world-owner declaration commits successfully. Only the
    # creature's subsequent attempt to use the ended field must be atomic.
    delivery=act.admit('hearth_weather',weather(a,record_id='ended-field',phenomenon=phenomenon),b)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('hearth_weather',delivery,b)
    assert cold().journey_state(jid)==before


def test_recipient_may_decline_earned_recovery_and_enter_without_spending_cadence(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    act('hearth_welcome',{'center':'self','invited':[b]})
    options=cold().journey_menu(jid,b)['options']
    assert any(o['kind']=='hearth_recovery' and o['payload']['benefit']=='decline' for o in options), 'Homefire Recovery must offer decline to its recipient'
    state=act('hearth_recovery',{'benefit':'decline'},b)
    assert FEATURES[1] not in state['actors'][b]['travel_uses']
    assert not state['actors'][b]['hearthfire'].get('recovery_ready')
    service=cold();result=service.journey_start_combat(jid,state['revision'],{a:'team:a',b:'team:b'})
    loaded=cold()._load_session(result['match_id'])
    assert loaded.mechanical.replay()['status']=='PASS'
    assert loaded.engine.state.actors[b].temporary_hp==0


def test_actual_domain_armament_center_is_reachable_in_travel_and_cold_encounter(tmp_path,monkeypatch):
    from combat.tabletop_service import TabletopService
    from combat.ext.qi_path import armament_point
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,owner_base_features=['tianxia.path.qi_cultivation.feature.domain_armament'])
    state=cold().journey_state(jid)
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'},maximum_rounds=1)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    for _ in range(2):
        if table.state(mid)['menu']['actor_id']==a:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    settle(table,mid,candidate(cold(),mid,'Domain Armament: Manifest',at=(5,5)).candidate_id)
    for _ in range(5):
        loaded=cold()._load_session(mid);assert loaded.mechanical.replay()['status']=='PASS'
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert armament_point(loaded.engine.state.actors[a])==(5,5)
    state=cold().journey_state(jid);cold().journey_resume(jid,state['revision'])
    kindle(act,a,b)
    option=next(o for o in cold().journey_menu(jid,a)['options'] if o['kind']=='hearth_carry')
    assert 'domain_armament' in option['fields']['center']['options']
    state=act('hearth_carry',{'center':'domain_armament','damage_type':'RADIANT'})
    camp=state['actors'][a]['hearthfire']['camp'];oid=camp['native_object']['object_id']
    assert camp['position']=={'x':5,'y':5}
    state=act('move',{'path':[{'x':3,'y':7}]})
    assert state['runtime_objects'][oid]['position']=={'x':5,'y':5}
    result=begin_combat(cold,jid,state['revision'],{a:'team:a',b:'team:b'},maximum_rounds=1)
    loaded=cold()._load_session(result['match_id']);assert loaded.mechanical.replay()['status']=='PASS'
    assert (loaded.engine.state.objects[oid].position.x,loaded.engine.state.objects[oid].position.y)==(5,5)
    ward=next(z for z in loaded.engine.state.zones.values() if z.active and z.trigger_profile.get('profile',{}).get('hearth_object'))
    assert ward.trigger_profile['profile']['carry_armament']==1


def test_travel_homefire_heals_actual_native_stable_zero_hp_and_cold_replay(tmp_path,monkeypatch):
    from combat.tabletop_service import TabletopService
    cold,jid,act,a,b=journey(tmp_path,monkeypatch,zero_guest=True)
    enemy='actor:factory.raider'
    state=cold().journey_state(jid)
    result=begin_combat(cold,jid,state['revision'],{a:'party',b:'party',enemy:'raiders'},maximum_rounds=5)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    choices={'choice:needle.hearth_feed':a,'choice:needle.hearth_shield':None,
        'choice:needle.hearth_rescue_move':None,'choice:needle.homefire_recovery':None,
        'choice:needle.welcoming_allies':[a,b]}
    cast=False
    for _ in range(35):
        loaded=cold()._load_session(mid);assert loaded.mechanical.replay()['status']=='PASS'
        e=loaded.engine
        if e.state.terminal_result is not None:break
        current=e.state.current_actor_id
        if current==a and not cast:
            settle(table,mid,candidate(cold(),mid,'Flame That Welcomes All').candidate_id,choices=choices);cast=True
        elif current==enemy and cast and e.state.actors[b].current_hp>0:
            settle(table,mid,candidate(cold(),mid,'Falling Star',at=(9,6)).candidate_id,choices=choices)
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices=choices)
    assert cast and loaded.engine.state.terminal_result is not None
    assert loaded.engine.state.actors[b].current_hp==0 and loaded.engine.state.actors[b].life_state=='STABLE'
    # Falling Star left Prone (STAND_UP), which generic Journey admission
    # deliberately requires the GM to resolve. Keep zero HP and Stable intact.
    state=cold().journey_state(jid)
    state=cold().journey_resume(jid,state['revision'],effect_resolutions={b:'The party settles the fallen guest after combat; the encounter-only Prone effects have ended.'})
    assert state['actors'][b]['incapacitated']==1
    act('hearth_end_welcome')
    state=cold().journey_state(jid)
    cold().journey_end_scene(jid,state['revision'],'The battle is over; the survivors begin treating the fallen guest.')
    act('hearth_welcome',{'center':'self','invited':[b]})
    state=act('hearth_recovery',{'benefit':'heal'},b)
    snap=state['actors'][b]['encounter_snapshot']
    assert snap['current_hp']==12 and snap['life_state']==''
    assert snap['death_saves']=={'ok':0,'bad':0} and state['actors'][b]['incapacitated']==0
    assert cold().journey_state(jid)==state
    state=act('hearth_end_welcome')
    result=begin_combat(cold,jid,state['revision'],{a:'party',b:'party',enemy:'raiders'},maximum_rounds=1)
    loaded=cold()._load_session(result['match_id']);assert loaded.mechanical.replay()['status']=='PASS'
    assert loaded.engine.state.actors[b].current_hp==12
    assert loaded.engine.state.actors[b].life_state not in ('DYING','STABLE')
