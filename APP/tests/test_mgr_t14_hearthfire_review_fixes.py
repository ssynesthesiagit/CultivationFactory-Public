"""Five Sol findings through acquired source, native seats and cold continuation."""
import json
import pytest
from combat.tabletop_service import TabletopService
from tests import test_mgr_t14_hearthfire_native as native
from tests.worker2_support import OWNER,ALLY,FOE,fixture,candidate,settle,turn,reload


def test_builtin_ai_acquires_real_hearth_item_and_retains_drop_and_fuel(tmp_path):
    combat,table,mid=fixture(tmp_path,[],cl=18,owner_bundle=native.acquired_bundle(tmp_path,18),
        battlefield_transform=lambda b:b.update(map_objects=[
            {'id':91,'kind':'stone_lantern','x':5,'y':6,'weight_lb':10},
            {'id':92,'kind':'crate','x':5,'y':7}]))
    settle(table,mid,candidate(combat,mid,'Kindled Hearth: empower an existing contained flame',
        target='object:map.91').candidate_id,choices={'choice:needle.kindled_hearth_recipients':[OWNER,ALLY]})
    engine=reload(tmp_path,mid)
    ward=next(z for z in engine.state.zones.values() if z.active and
        z.trigger_profile.get('profile',{}).get('hearth_object')=='object:map.91')
    assert ward.center==engine.state.objects['object:map.91'].position
    # Check ignition while fuel touches the flame. Pickup below relocates the
    # real item, so the original crate need not remain a legal fuel target.
    context=combat.ai_decision_context(combat._load_session(mid))
    assert any(c.source_definition_id=='system:hearth.ignite_fuel' and c.target_ids==('object:map.92',)
               for c in context.legal_candidates)
    turn(table,mid,ALLY)
    combat.set_controller_mode(mid,actor_id=ALLY,controller_mode='LOCAL_AUTO')
    context=combat.ai_decision_context(combat._load_session(mid))
    assert any(c.source_definition_id=='system:hearth.item.take.free' for c in context.legal_candidates)
    settle(table,mid,None,auto=True)
    engine=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.hearth_item_custody' for c in engine.state.actors[ALLY].conditions.values())
    context=combat.ai_decision_context(combat._load_session(mid))
    assert any(c.source_definition_id=='system:hearth.item.put_down.utilize' for c in context.legal_candidates)
    # Fuel's public operation must also remain available to the built-in AI.
    assert not engine.action_catalog['system:hearth.ignite_fuel'].parameters.get('player_only')
    combat.set_controller_mode(mid,actor_id=ALLY,controller_mode='MANUAL')
    turn(table,mid,OWNER)
    prompts=settle(table,mid,candidate(combat,mid,'Carry the Hearth').candidate_id,
        choices={'choice:needle.carry_hearth':ALLY,'choice:needle.fact_admission.carry_hearth_consent':'carry'})
    assert any(p['context']['reactor_id']==ALLY for p in prompts)
    engine=reload(tmp_path,mid)
    assert engine.state.objects['object:map.91'].position==engine.state.actors[ALLY].position


@pytest.mark.parametrize('field,key',[('hearth','remaining'),('pavilion','pavilion_remaining'),
                                    ('carry','carry_remaining'),('welcome','welcome_remaining')])
def test_partial_round_clock_survives_combat_resume_and_reentry(tmp_path,monkeypatch,field,key):
    from combat.ext.qi_hearthfire_persistence import CLOCK
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch)
    native.kindle(act,a,b)
    if field=='pavilion':act('hearth_pavilion')
    if field=='carry':act('hearth_carry',{'center':a,'damage_type':'FIRE'})
    if field=='welcome':act('hearth_welcome',{'center':'self','invited':[a,b]})
    state=act('wait',{'seconds':53})
    doc=state['actors'][a]['hearthfire']
    source=doc['welcome'] if field=='welcome' else doc['camp']
    if field in ('pavilion','carry'):source=source[field]
    expected=source['until']-state['seconds']
    assert expected%6==1
    result=native.begin_combat(cold,jid,state['revision'],{a:'party',b:'opponents'},maximum_rounds=1)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    engine=cold()._load_session(mid).engine
    record=next(c.data for c in engine.state.actors[a].conditions.values() if c.condition_id==CLOCK)
    assert record[key]==expected, 'Encounter genesis must neither refill nor consume a partial source round'
    for _ in range(6):
        loaded=cold()._load_session(mid)
        assert loaded.mechanical.replay()['status']=='PASS'
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert loaded.engine.state.terminal_result is not None
    record=next(c.data for c in loaded.engine.state.actors[a].conditions.values() if c.condition_id==CLOCK)
    assert record[key]==max(0,expected-6)
    state=cold().journey_state(jid)
    state=cold().journey_resume(jid,state['revision'])
    assert cold().journey_state(jid)==state
    saved=next(json.loads(v)['data'] for v in state['actors'][a]['encounter_snapshot']['conditions'].values()
               if json.loads(v)['condition_id']==CLOCK)
    assert saved[key]==record[key]
    second=native.begin_combat(cold,jid,state['revision'],{a:'party',b:'opponents'},maximum_rounds=1)
    loaded=cold()._load_session(second['match_id']);assert loaded.mechanical.replay()['status']=='PASS'
    again=next(c.data for c in loaded.engine.state.actors[a].conditions.values() if c.condition_id==CLOCK)
    assert again[key]<=record[key] and (record[key]-again[key])%6==0


@pytest.mark.parametrize('score,skill,bonus',[(18,None,4),(6,None,-2),(18,16,16)])
def test_outside_nonowner_uses_native_wisdom_and_perception(tmp_path,monkeypatch,score,skill,bonus):
    original=native.sheet
    def character(*args,**kwargs):
        doc=original(*args,**kwargs)
        if skill is not None:doc['ability_scores_and_statistics']['skills']=[{'skill':'Perception','bonus':skill}]
        return doc
    monkeypatch.setattr(native,'sheet',character)
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch,guest_score=score)
    native.kindle(act,a,b);act('hearth_pavilion')
    act('move',{'path':[{'x':x,'y':6} for x in range(5,11)]},b)
    state=act('hearth_speak',{'text':'The tea is ready.','expires_at':10000})
    speech=state['events'][-1]['record_id']
    assert not any(r.get('feature_id') in native.FEATURES for r in state['actors'][b]['bundle'].get('typed_passives',()))
    state=act('hearth_listen',{'owner':a,'speaker':a,'method':'check','effect_source_cl':0,'speech_record_id':speech},b)
    roll=state['events'][-1]['roll']
    assert roll['modifier']==bonus
    assert cold().journey_state(jid)==state


def test_fresh_paid_carry_does_not_inherit_previous_partial_round(tmp_path,monkeypatch):
    from combat.ext.qi_hearthfire_persistence import CLOCK
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch)
    native.kindle(act,a,b);act('hearth_carry',{'center':a,'damage_type':'FIRE'})
    state=act('wait',{'seconds':53})
    result=native.begin_combat(cold,jid,state['revision'],{a:'party',b:'opponents'},maximum_rounds=1)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    for _ in range(3):
        if table.state(mid)['menu']['actor_id']==a:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    settle(table,mid,candidate(cold(),mid,'Carry the Hearth').candidate_id,
        choices={'choice:needle.carry_hearth':a,'choice:needle.hearth_initial_damage':'FIRE'})
    loaded=cold()._load_session(mid);assert loaded.mechanical.replay()['status']=='PASS'
    record=next(c.data for c in loaded.engine.state.actors[a].conditions.values() if c.condition_id==CLOCK)
    assert record['carry_remaining']==60
    for _ in range(4):
        if loaded.engine.state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        loaded=cold()._load_session(mid);assert loaded.mechanical.replay()['status']=='PASS'
    assert loaded.engine.state.terminal_result is not None
    record=next(c.data for c in loaded.engine.state.actors[a].conditions.values() if c.condition_id==CLOCK)
    assert record['carry_remaining']==54, 'The terminal round elapsed even before the next owner turn starts'


@pytest.mark.parametrize('distance,covered',[(20,False),(15,True)])
def test_short_rest_requires_coverage_after_carry_expires(tmp_path,monkeypatch,distance,covered):
    cold,jid,act,a,b=native.journey(tmp_path,monkeypatch)
    native.kindle(act,a,b);act('hearth_carry',{'center':a,'damage_type':'FIRE'})
    target=3+distance//5
    act('move',{'path':[{'x':x,'y':6} for x in range(5,target+1)]},b)
    before=cold().journey_state(jid)
    if not covered:
        with pytest.raises(ValueError,match='throughout'):
            act('hearth_short_rest',{},b)
        assert cold().journey_state(jid)==before
        assert not before['actors'][b].get('hearthfire',{}).get('recovery_ready')
    else:
        state=act('hearth_short_rest',{},b)
        assert state['seconds']==before['seconds']+3600
        assert state['actors'][b]['hearthfire']['recovery_ready']==6
        assert not state['actors'][a]['hearthfire']['camp'].get('carry')
        state=act('hearth_recovery',{'benefit':'temp_hp'},b)
        assert state['actors'][b]['hearthfire']['temporary_hp']==12
        assert cold().journey_state(jid)==state


def test_decline_regression_reaches_actual_cold_encounter(tmp_path,monkeypatch):
    from tests import test_mgr_t14_hearthfire_final as final
    final.test_recipient_may_decline_earned_recovery_and_enter_without_spending_cadence(tmp_path,monkeypatch)


@pytest.mark.parametrize('failure',["NameError: name 'FEATURES' is not defined",'AssertionError: unrelated assertion',
                                  'ValueError: unrelated validation'])
def test_counterfactual_rejects_test_crashes_and_unrelated_failures(failure):
    from tests.test_mgr_t14_hearthfire_before import assert_behavioral_failures
    case='tests/test_mgr_t14_hearthfire_final.py::test_recipient_may_decline_earned_recovery_and_enter_without_spending_cadence'
    with pytest.raises(AssertionError):
        assert_behavioral_failures('FAILED '+case+' - '+failure,
            {case:'AssertionError: Homefire Recovery must offer decline to its recipient'})


def test_counterfactual_accepts_only_expected_decline_failure():
    from tests.test_mgr_t14_hearthfire_before import assert_behavioral_failures
    case='tests/test_mgr_t14_hearthfire_final.py::test_recipient_may_decline_earned_recovery_and_enter_without_spending_cadence'
    message='AssertionError: Homefire Recovery must offer decline to its recipient'
    assert_behavioral_failures('FAILED '+case+' - '+message,{case:message})
