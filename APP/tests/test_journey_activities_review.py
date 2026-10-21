"""Review regressions through native acquisition, journey/table commits and reload.

No live model clients: automatic decisions consume only the actor's offered menu.
"""
import copy
import pytest
from combat import ext
from combat.gate5_service import CombatServiceError
from combat.tabletop_service import TabletopService
from tests.test_journey_activities_native import (
    A, B, PIDS, ARENA, CHECK, PENDING, EFFECT, EFFECTS, DREAM, DREAM_KEY,
    DUTY, LEARN, game, request, ledger, inst, catalog,
    controlling_source_base,
)
from tests.test_shield_fix_r2 import advance, finish
from tests.test_shield_fix_r1 import table_action


def auto(cold,jid,aid=A,option=None):
    before=cold().journey_state(jid)
    result=cold().journey_auto_step(jid,before['revision'],aid,option)
    assert cold().journey_state(jid)==result
    assert cold().journey_verify(jid)['status']=='PASS'
    return result


def complete_encounter(cold,mid,tmp_path):
    for _ in range(8):
        if cold()._load_session(mid).engine.state.terminal_result: break
        assert table_action(TabletopService(cold(),tmp_path),mid,'end')['status']=='COMMITTED'
    assert cold()._load_session(mid).engine.state.terminal_result
    assert cold().verify(mid)['status']=='PASS'
    assert cold().replay(mid)['status']=='PASS'


def test_frightened_source_and_single_instance_survive_native_encounter_resume(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    world(EFFECT,'effect','fear',{'id':'fear','label':'Fear of the Steward','category':'frightened',
        'source':'external:frightening-presence','source_actor_id':A,'save_ability':'WIS','save_dc':20},B)
    teams={A:'team:a',B:'team:b'}
    mids=[]
    for encounter in range(2):
        state=cold().journey_state(jid)
        mid=cold().journey_start_combat(jid,state['revision'],teams,maximum_rounds=1)['match_id']
        mids.append(mid)
        actor=cold()._load_session(mid).engine.state.actors[B]
        conditions=[c for c in actor.conditions.values() if c.condition_id=='condition:typed.frightened']
        assert len(conditions)==1
        assert conditions[0].source_actor_id==A
        assert conditions[0].source_definition_id=='external:frightening-presence'
        assert cold().verify(mid)['status']=='PASS'
        complete_encounter(cold,mid,tmp_path)
        state=cold().journey_state(jid)
        state=cold().journey_resume(jid,state['revision'])
        assert cold().journey_state(jid)==state
        assert len(state['actors'][B]['source_states'][EFFECTS])==1
        assert state['actors'][B]['source_states'][EFFECTS]['fear']['source_actor_id']==A
    act('wait',{'seconds':1})
    assert cold().journey_verify(jid)['bound_matches']==mids


@pytest.mark.parametrize('pending_actor',[A,B])
@pytest.mark.parametrize('transition',['finish','enter_combat','service_combat'])
def test_party_transition_waits_for_every_pending_check(tmp_path,monkeypatch,catalog,pending_actor,transition):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    world(CHECK,'request','pending',{'purpose':'read the visible roster','ability':'INT','skill':'',
        'dc':12,'sect_context':0,'role':'','duty':'','institution':'','recovery':''},pending_actor)
    act('check_start',{'scope':'pending','merit':0},pending_actor)
    before=copy.deepcopy(cold().journey_state(jid))
    with pytest.raises(ValueError,match='pending check'):
        if transition=='service_combat':
            cold().journey_start_combat(jid,before['revision'],{A:'team:a',B:'team:b'})
        else: act(transition,aid=B if pending_actor==A else A)
    assert cold().journey_state(jid)==before
    act('check_settle',{'merit':0},pending_actor)
    state=act('finish')
    assert state['phase']=='finished'
    state=cold().create_journey(project_ids=PIDS,arena_id=ARENA,
        positions={A:{'x':2,'y':2},B:{'x':2,'y':3}},base_paces={A:1800,B:1800})
    assert all(PENDING not in actor.get('source_states',{}) for actor in state['actors'].values())
    assert cold().journey_verify(state['journey_id'])['status']=='PASS'


@pytest.mark.parametrize('duplicate',[False,True])
@pytest.mark.parametrize('sect_context',[0,1])
def test_native_tool_check_includes_proficiency_once_across_reopen(tmp_path,monkeypatch,catalog,duplicate,sect_context):
    tool='Herbalism Kit'
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,native_tools=(tool,) if duplicate else ())
    state=act('sect_learn',{'ability':'INT','proficiency':tool,'approval':''})
    assert ledger(state)['training']['duplicate']==int(duplicate)
    def check(cold,jid,scope):
        state=cold().journey_state(jid)
        state=cold().journey_world_fact(jid,state['revision'],{'source':CHECK,'subject':A,'kind':'request','scope':scope,
            'value':{'purpose':'identify medicinal plants','ability':'INT','skill':tool,'dc':12,
                'sect_context':sect_context,'role':'','duty':'','institution':'','recovery':''},
            'expires_at':state['seconds']+100,'readers':[A]})
        state=cold().journey_act(jid,state['revision'],A,'check_start',{'scope':scope,'merit':0})
        pending=state['actors'][A]['source_states'][PENDING]
        assert pending['total']-pending['natural']==6+(2 if duplicate and sect_context else 0)
        state=cold().journey_act(jid,state['revision'],A,'check_settle',{'merit':0})
        assert cold().journey_verify(jid)['status']=='PASS'
        return state
    state=check(cold,jid,'first')
    cold().journey_act(jid,state['revision'],A,'finish',{})
    state=cold().create_journey(project_ids=PIDS,arena_id=ARENA,
        positions={A:{'x':2,'y':2},B:{'x':2,'y':3}},base_paces={A:1800,B:1800})
    assert tool in state['actors'][A]['bundle']['journey_tool_proficiencies']
    check(cold,state['journey_id'],'reopened')


@pytest.mark.parametrize('explicit',[False,True])
def test_autonomous_check_uses_auto_step_and_finishes_decision(tmp_path,monkeypatch,catalog,explicit):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,auto=True)
    request(world,'auto-check',skill='',dc=100)
    act('check_start',{'scope':'auto-check','merit':0})
    state=auto(cold,jid,option='check:finish' if explicit else None)
    assert PENDING not in state['actors'][A]['source_states']


@pytest.mark.parametrize('explicit',[False,True])
def test_autonomous_restful_recipient_resolves_offered_choices(tmp_path,monkeypatch,catalog,explicit):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='dreams',auto=True)
    world(EFFECT,'effect','nightmare',{'id':'nightmare','label':'Ordinary nightmare','category':'ordinary_nightmare',
        'source':'external:bad-sleep','save_ability':'','save_dc':0})
    state=cold().journey_state(jid)
    act('declare_fact',{'source':DREAM,'subject':A,'kind':'willing','scope':A,'value':1,
        'expires_at':state['seconds']+3600,'readers':[A]})
    # Both the ritual start and actual work are chosen through the auto boundary.
    state=auto(cold,jid)
    assert state['actors'][A]['source_states']['journey:activity']['source']==DREAM
    state=auto(cold,jid)
    assert 'journey:activity' not in state['actors'][A]['source_states']
    act('short_rest')
    state=auto(cold,jid,option='restful:minor:nightmare' if explicit else None)
    assert ledger(state,key=DREAM_KEY)['minor_choice']==0
    assert 'nightmare' not in state['actors'][A]['source_states'][EFFECTS]


def test_autonomous_learning_is_reachable_without_removing_manual_options(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,auto=True)
    menu=cold().journey_menu(jid,A)
    learn=[o for o in menu['options'] if o['kind']=='sect_learn']
    assert len(learn)==24 and all(o['auto_select'] for o in learn)
    state=auto(cold,jid)
    assert ledger(state)['training']['ability'] in ('INT','WIS','CHA')
    act('long_rest')
    state=auto(cold,jid)
    assert ledger(state)['role'] and ledger(state)['role_rest']==1


def test_ask_plan_keeps_pending_journey_choice_player_owned(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,auto=True,ask=True)
    request(world,'ask-check')
    act('check_start',{'scope':'ask-check','merit':0})
    before=cold().journey_state(jid)
    assert auto(cold,jid,option='check:finish')==before
    state=act('check_settle',{'merit':0})
    assert PENDING not in state['actors'][A]['source_states']


def test_autonomous_duty_work_and_approved_reward_use_personally_offered_options(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,auto=True)
    act('sect_learn',{'ability':'INT','proficiency':'History','approval':''})
    inst(world)
    world(LEARN,'duty_plan','auto-duty',{'obligation':'copy the visible roster','institution':'hall',
        'steps':[{'task':'copy roster','seconds':60}]})
    menu=cold().journey_menu(jid,A)
    option=next(o for o in menu['options'] if o['kind']=='sect_duty')
    state=auto(cold,jid,option=option['id'])
    instance=ledger(state)['duty']['instance_id']
    state=auto(cold,jid)  # begin the available Duty step
    assert state['actors'][A]['source_states']['journey:activity']['source']==DUTY
    state=auto(cold,jid)  # complete its real work clock
    assert ledger(state)['duty']['completed'][0]['worked_seconds']==60
    world(LEARN,'duty_verification',instance,{'witness':'Roster clerk','record':'signed copy',
        'approved_rewards':['favor'],'detail':'The clerk received the completed roster'})
    state=auto(cold,jid)
    assert ledger(state)['duty']['rewarded']==1


def test_empty_journey_replay_proof_has_stable_segment_schema(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog)
    proof=cold().journey_verify(jid)
    assert proof['previous_segments']==0 and proof['bound_matches']==[]


def test_reaction_admission_failure_cannot_commit_an_attack(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='shield')
    state=cold().journey_state(jid)
    mid=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},maximum_rounds=3)['match_id']
    table=TabletopService(cold(),tmp_path)
    advance(table,mid,B)
    ext.effects()
    def broken(*args): raise ValueError('Invalid admission receipt')
    monkeypatch.setitem(ext._HOOKS,'reaction_admission',[broken])
    before=cold()._load_session(mid).engine.state.model_dump(mode='json')
    with pytest.raises(CombatServiceError) as rejected:
        finish(table,mid,'Bi Shou (Dagger) attack',lambda p:['reaction'],target=A)
    assert rejected.value.diagnostic.details['reason']=='reaction_admission: Invalid admission receipt'
    assert cold()._load_session(mid).engine.state.model_dump(mode='json')==before
    assert cold().verify(mid)['status']=='PASS'


def test_shield_declaration_stores_readable_state_and_lifetime_after_reload(tmp_path,monkeypatch,catalog):
    cold,jid,act,world=game(tmp_path,monkeypatch,catalog,sphere='shield')
    state=cold().journey_state(jid)
    mid=cold().journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'},maximum_rounds=3)['match_id']
    table=TabletopService(cold(),tmp_path)
    advance(table,mid,A)
    finish(table,mid,'Record Shield presentation circumstances',lambda p:['cannot_present'])
    actor=cold()._load_session(mid).engine.state.actors[A]
    condition=next(c for c in actor.conditions.values() if c.condition_id=='condition:typed.fact_consent_admission')
    # Admission receipts are intentionally hidden by the presentation provider;
    # this asserts persisted declaration text, not a visible condition pill.
    assert condition.data['label']=='Shield presentation: cannot present your Shield toward an incoming attack; remains until you change this declaration'
    assert cold().verify(mid)['status']=='PASS' and cold().replay(mid)['status']=='PASS'
