"""F6 review regressions through native acquisition, committed IO and cold replay."""
import pytest
from combat.tabletop_service import TabletopService
from tests.test_journey_activities_native import (
    A, B, CP, DREAM, DREAM_KEY, LEARN, DUTY, RECOVER, MERIT, BASE_REQUESTS,
    CHECK, PENDING, game, inst, work, ledger, request, catalog, controlling_source_base,
)
from tests.test_journey_activities_review import auto
from tests.test_journey_activities_f5 import fixture_action
from tests.test_shield_fix_r1 import table_action
from tests.test_shield_fix_r2 import advance, finish


def consent(cold, jid, act, seconds=3600):
    state=cold().journey_state(jid)
    return act('declare_fact',{'source':DREAM,'subject':A,'kind':'willing','scope':A,
        'value':1,'expires_at':state['seconds']+seconds,'readers':[A]})


@pytest.mark.parametrize('used',[False,True])
def test_automatic_dream_does_not_replace_pending_or_used_benefit(tmp_path,monkeypatch,catalog,used):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='dreams',auto=True,cp=4)
    consent(cold,jid,act)
    before=cold().journey_state(jid)
    initial_cp=before['actors'][A]['resources'][CP]
    auto(cold,jid)  # start the ritual
    state=auto(cold,jid)  # finish all ten minutes
    assert state['seconds']==600
    if used:
        act('short_rest')
        state=consent(cold,jid,act)
        assert ledger(state,key=DREAM_KEY)['benefit_rest']==state['actors'][A]['long_rests']
    else:
        assert 'pending' in ledger(state,key=DREAM_KEY)
    # Legal explicit repeats stay reachable, but are not automatic defaults.
    rituals=[o for o in cold().journey_menu(jid,A)['options'] if o['kind']=='activity_start']
    assert rituals and all(not o['auto_select'] for o in rituals)
    for _ in range(3):
        position=state['actors'][A]['position']
        state=auto(cold,jid)
        assert state['actors'][A]['position']!=position
        assert state['actors'][A]['resources'][CP]==initial_cp-1
        assert 'journey:activity' not in state['actors'][A].get('source_states', {})
    assert len([e for e in state['events'] if e['kind']=='RITUAL_PAID'])==1


@pytest.mark.parametrize('seconds,starts',[(599,False),(600,False),(601,True)])
def test_automatic_dream_requires_consent_through_completion(tmp_path,monkeypatch,catalog,seconds,starts):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='dreams',auto=True)
    before=consent(cold,jid,act,seconds)
    options=[o for o in cold().journey_menu(jid,A)['options'] if o['kind']=='activity_start']
    assert options and all(bool(o['auto_select']) is starts for o in options)
    state=auto(cold,jid)
    assert ('journey:activity' in state['actors'][A].get('source_states', {})) is starts
    assert state['actors'][A]['resources'][CP]==before['actors'][A]['resources'][CP]-int(starts)
    if starts:
        state=auto(cold,jid)
        assert 'pending' in ledger(state,key=DREAM_KEY)
    else:
        assert state['actors'][A]['position']!=before['actors'][A]['position']


@pytest.mark.parametrize('seconds,present,good,expected',[
    (1,1,1,0),(599,1,1,0),(600,1,1,4),
    (1,0,0,1),(600,0,0,1),(600,1,0,0),
])
def test_merit_recovery_enforces_completed_duration_after_context_change(tmp_path,monkeypatch,catalog,seconds,present,good,expected):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    inst(world)
    for _ in range(4):
        act('sect_petition',{'institution':'hall','request':BASE_REQUESTS[0].text})
    inst(world,present=0,good=0)
    state=work(act,RECOVER,{'institution':'hall','activity':'maintain the traveling ledger','seconds':seconds},seconds)
    receipt=ledger(state)['recovery_work']
    assert receipt['worked_seconds']==seconds and receipt['recovery_mode']=='away'
    assert ledger(cold().journey_state(jid))['recovery_work']==receipt
    inst(world,present=present,good=good)
    state=act('long_rest')
    assert state['actors'][A]['resources'][MERIT]==expected
    assert 'recovery_work' not in ledger(state)
    state=act('long_rest')
    assert state['actors'][A]['resources'][MERIT]==expected
    assert cold().journey_verify(jid)['status']=='PASS'


def test_active_defense_readiness_names_trigger_and_both_creatures(tmp_path,monkeypatch,catalog):
    fixture_action(monkeypatch,'Invisible fixture',[{'type':'condition','condition':'invisible',
        'applies_to':'self','expires_on':'UNTIL_REMOVED'}],{'kind':'instant'})
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='shield')
    state=cold().journey_state(jid)
    mid=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},maximum_rounds=2)['match_id']
    table=TabletopService(cold(),tmp_path)
    advance(table,mid,B)
    assert table_action(table,mid,'Invisible fixture')['status']=='COMMITTED'
    prompts=finish(table,mid,'Bi Shou (Dagger) attack',lambda p:None,target=A)
    prompt=next(p for p in prompts if 'fact_admission.shield_readiness' in p['context']['reaction_source_id'])
    engine=cold()._load_session(mid).engine
    for text in ('Active Defense','Bi Shou (Dagger) attack',
                 engine.state.actors[A].display_name,engine.state.actors[B].display_name):
        assert text in prompt['moment']
    assert 'spends no Reaction or Martial Focus' in prompt['moment']
    assert cold().verify(mid)['status']=='PASS' and cold().replay(mid)['status']=='PASS'


def test_supplies_reward_describes_companion_choice_and_delivers_it(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    inst(world)
    world(LEARN,'duty_plan','roster',{'obligation':'deliver the roster','institution':'hall',
        'steps':[{'task':'deliver roster','seconds':1}]})
    state=act('sect_duty',{'scope':'roster'})
    instance=ledger(state)['duty']['instance_id']
    work(act,DUTY,{'step':0},1)
    package={'description':'Food and common-room sleeping space','items':[],
        'entitlements':['food','shelter']}
    world(LEARN,'duty_verification',instance,{'witness':'Hall clerk','record':'signed roster',
        'approved_rewards':['supplies'],'detail':'The clerk received the roster','supplies':package})
    option=next(o for o in cold().journey_menu(jid,A)['options'] if o['id']=='sect:reward:supplies')
    assert 'typed command' not in option['label']
    assert 'choose up to five companions' in option['label']
    state=act(option['kind'],{**option['payload'],'companions':[B]})
    assert ledger(state,B)['support'][-1]['fulfillment']==package
    assert ledger(state)['duty']['rewarded']==1


@pytest.mark.parametrize('duplicate',[False,True])
def test_learned_journey_skill_uses_canonical_compiled_total_once(tmp_path,monkeypatch,catalog,duplicate):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,duplicate=duplicate)
    act('sect_learn',{'ability':'INT','proficiency':'History','approval':''})
    request(world,'learned-history')
    state=act('check_start',{'scope':'learned-history','merit':0})
    pending=state['actors'][A]['source_states'][PENDING]
    assert pending['total']-pending['natural']==(8 if duplicate else 6)
    act('check_settle',{'merit':0})
