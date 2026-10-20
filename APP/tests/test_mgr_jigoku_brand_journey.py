"""Real Brand continuation: table commits -> travel -> cold replay."""
import json
import pytest
from combat.ext.jigoku_procedures import journey_brands, BRAND_CLOCK
from combat.journey import JourneySession
from tests.test_mgr_jigoku_native import (
    game, combat, turn, candidate, reload, end_encounter, A, B, SOURCE, PREFIX,
    test_native_one_action_extinguishes_one_of_two_real_brands,
    test_native_acquisition_reaches_factory_and_stock_bearer_extinguish,
)
from tests.worker2_support import settle


def branded_journey(tmp_path, monkeypatch, *, defender=False, foe_cl=None):
    cold, jid, acquire = game(tmp_path, monkeypatch, cl=17 if defender and foe_cl is None else 10,
        foe_cl=foe_cl if foe_cl is not None else (10 if defender else 14))
    acquire()
    if defender:
        s = cold().journey_state(jid)
        cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':B,'kind':'legal_access','scope':'acquisition',
            'value':'The actual admitted Forbidden Method scripture.','expires_at':31536000,'readers':[]})
        acquire(B)
    for _ in range(10):
        service, table, mid = combat(cold, jid, rounds=1)
        turn(table, mid, A)
        settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,
               {'choice:needle.path_hit.'+PREFIX+'flame_fist':['Use Burning Brand'],
                'choice:needle.fact_admission.hostile_intent':None})
        end_encounter(table, mid)
        terminal = reload(cold, mid)
        s = cold().journey_state(jid)
        s = cold().journey_resume(jid, s['revision'], effect_resolutions={A:'The turn has ended', B:'The turn has ended'})
        if journey_brands(JourneySession(s), B): return cold, jid, mid, terminal, s
    raise AssertionError('The real deterministic encounters never left a surviving Brand')


def answer_pending(cold, jid, s, choose=None):
    for _ in range(60):
        pending = s.get('native_effect_choice')
        if not pending: return s
        aid = pending['request']['reactor_id']
        menu = cold().journey_menu(jid, aid)
        rows = [r for r in menu['options'] if r['kind']=='native_effect_answer']
        assert rows
        selected = choose(rows,pending) if choose else next((r for r in rows if r['payload']['selection']=='DECLINE'),rows[0])
        s = cold().journey_act(jid,s['revision'],aid,selected['kind'],selected['payload'])
        assert cold().journey_verify(jid)['status']=='PASS'
    raise AssertionError('Native choices did not finish')


def native_events(s, after=0):
    return [json.loads(e['event']) for e in s['events'][after:] if e['kind']=='NATIVE_EFFECT_EVENT']


def test_brand_elapsed_damage_repeat_save_cold_replay(tmp_path,monkeypatch):
    cold,jid,mid,terminal,s = branded_journey(tmp_path,monkeypatch)
    from combat.journey_native import KEY as NATIVE
    assert [json.loads(e) for e in s[NATIVE]['creation_events']]==[
        e.model_dump(mode='json') for e in terminal.events if e.event_type=='MATCH_CREATED']
    old = s['actors'][B]['encounter_snapshot']['current_hp']; offset = len(s['events'])
    s = cold().journey_act(jid,s['revision'],A,'wait',{'seconds':5})
    assert s['actors'][B]['encounter_snapshot']['current_hp']==old
    assert s['actors'][B]['source_states'][BRAND_CLOCK]['remaining_seconds']=='1'
    assert cold().journey_verify(jid)['status']=='PASS'
    s = answer_pending(cold,jid,cold().journey_act(jid,s['revision'],A,'wait',{'seconds':1}))
    events = native_events(s,offset)
    assert not any(e['event_type']=='MATCH_CREATED' for e in events)
    packets = [e for e in events if e['event_type']=='DAMAGE_COMMITTED' and B in e['target_ids']]
    saves = [e for e in events if e['event_type']=='SAVE_ROLLED' and e['actor_id']==B]
    assert len(packets)==len(saves)==1
    assert packets[0]['payload']['damage_type']=='FIRE'
    assert old-s['actors'][B]['encounter_snapshot']['current_hp']==packets[0]['payload']['hp_damage']>0
    assert packets[0]['sequence'] < saves[0]['sequence']
    s = answer_pending(cold,jid,cold().journey_act(jid,s['revision'],A,'wait',{'seconds':600}))
    assert not journey_brands(JourneySession(s),B)
    assert cold().journey_verify(jid)['status']=='PASS'
    assert reload(cold,mid).state==terminal.state


@pytest.mark.parametrize('rescuer',[A,B])
def test_brand_journey_extinguish_action_self_or_adjacent(tmp_path,monkeypatch,rescuer):
    cold,jid,mid,terminal,s = branded_journey(tmp_path,monkeypatch)
    with pytest.raises(ValueError, match='Burning Brand'):
        cold().journey_act(jid,s['revision'],rescuer,'finish',{})
    assert cold().journey_state(jid)==s
    menu = cold().journey_menu(jid,rescuer)
    option = next(r for r in menu['options'] if r['kind']=='jigoku_extinguish' and r['payload']['target']==B)
    old = s['actors'][B]['encounter_snapshot']['current_hp']; seconds=s['seconds']
    s = cold().journey_act(jid,s['revision'],rescuer,option['kind'],option['payload'])
    assert s['seconds']==seconds+6
    assert not journey_brands(JourneySession(s),B)
    s = cold().journey_act(jid,s['revision'],A,'wait',{'seconds':60})
    assert s['actors'][B]['encounter_snapshot']['current_hp']==old
    assert cold().journey_verify(jid)['status']=='PASS'
    s=cold().journey_act(jid,s['revision'],rescuer,'finish',{})
    assert s['phase']=='finished'


def test_brand_journey_fire_immunity_uses_native_defense(tmp_path,monkeypatch):
    cold,jid,mid,terminal,s = branded_journey(tmp_path,monkeypatch,defender=True,foe_cl=14)
    old = s['actors'][B]['encounter_snapshot']['current_hp']; offset=len(s['events'])
    s = answer_pending(cold,jid,cold().journey_act(jid,s['revision'],A,'wait',{'seconds':6}))
    assert s['actors'][B]['encounter_snapshot']['current_hp']==old
    assert any(e['event_type']=='SAVE_ROLLED' and e['actor_id']==B for e in native_events(s,offset))
    assert cold().journey_verify(jid)['status']=='PASS'


def test_brand_journey_player_decisions_rollback_and_resume(tmp_path,monkeypatch):
    cold,jid,mid,terminal,s = branded_journey(tmp_path,monkeypatch,defender=True)
    old=s['actors'][B]['encounter_snapshot']['current_hp']; seconds=s['seconds']
    pending=cold().journey_act(jid,s['revision'],A,'wait',{'seconds':6})
    assert 'native_effect_choice' in pending
    assert pending['seconds']==seconds and pending['actors'][B]['encounter_snapshot']['current_hp']==old
    assert cold().journey_verify(jid)['status']=='PASS'
    extinguish=next(r for r in cold().journey_menu(jid,B)['options'] if r['kind']=='jigoku_extinguish')
    with pytest.raises(ValueError, match='Answer the ongoing'):
        cold().journey_act(jid,pending['revision'],B,extinguish['kind'],extinguish['payload'])
    assert cold().journey_state(jid)==pending
    def benefits(rows, pending):
        rid=pending['request']['reaction_source_id']
        desired={'choice:needle.fact_admission.hostile_intent':'genuine',
                 'choice:needle.eat_the_flame':'eat','choice:needle.pain_eater':'mark'}.get(rid)
        return next((r for r in rows if r['payload']['option_ids']==[desired]),
                    next((r for r in rows if r['payload']['selection']=='DECLINE'),rows[0]))
    stamina=s['actors'][B]['resources']['resource:core.stamina']
    s=answer_pending(cold,jid,pending,benefits)
    assert s['seconds']==seconds+6
    assert s['actors'][B]['encounter_snapshot']['current_hp']<old
    assert s['actors'][B]['resources']['resource:core.stamina']==stamina-1
    assert s['actors'][B]['encounter_snapshot']['temporary_hp']>0
    assert any(json.loads(c)['condition_id']=='condition:typed.pain_eater_mark'
               for c in s['actors'][A]['encounter_snapshot']['conditions'].values())
    s=answer_pending(cold,jid,cold().journey_act(jid,s['revision'],A,'wait',{'seconds':6}))
    assert not any(json.loads(c)['condition_id']=='condition:typed.pain_eater_mark'
                   for c in s['actors'][A]['encounter_snapshot']['conditions'].values())
    assert cold().journey_verify(jid)['status']=='PASS'


def test_brand_pulses_during_actual_travel_step(tmp_path,monkeypatch):
    cold,jid,mid,terminal,s=branded_journey(tmp_path,monkeypatch)
    seconds=s['seconds']; offset=len(s['events']); hp=s['actors'][B]['encounter_snapshot']['current_hp']
    s=answer_pending(cold,jid,cold().journey_act(jid,s['revision'],B,'move',{'path':[{'x':4,'y':2}]}))
    assert s['seconds']==seconds+10 and s['actors'][B]['position']=={'x':4,'y':2}
    assert s['actors'][B]['encounter_snapshot']['current_hp']<hp
    assert len([e for e in native_events(s,offset) if e['event_type']=='SAVE_ROLLED' and e['actor_id']==B])==1
    assert cold().journey_verify(jid)['status']=='PASS'


def test_brand_interrupts_native_cultivation_work_without_recovery(tmp_path,monkeypatch):
    from combat.ext.jigoku_procedures import SESSION
    from combat.ext.journey_activities import KEY as ACTIVITY
    cold,jid,mid,terminal,s=branded_journey(tmp_path,monkeypatch,defender=True)
    s=cold().journey_act(jid,s['revision'],B,'activity_start',{'source':SESSION,'parameters':{}})
    stamina=s['actors'][B]['resources']['resource:core.stamina']; seconds=s['seconds']
    s=answer_pending(cold,jid,cold().journey_act(jid,s['revision'],B,'activity_work',{'seconds':7200}))
    assert ACTIVITY not in s['actors'][B]['source_states']
    assert s['seconds']==seconds+6
    assert s['actors'][B]['resources']['resource:core.stamina']==stamina
    assert not any(e['kind']=='ACTIVITY_FINISHED' and e['actor_id']==B for e in s['events'])
    assert cold().journey_verify(jid)['status']=='PASS'
