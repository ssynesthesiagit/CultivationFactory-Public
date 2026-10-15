"""Guardian second pass through table transactions and cold service replay."""
import pytest
from tests.auto_worker1_support import fight, act, reload, settle, turn, action_sender, LEFT, RIGHT, ALLY

ADAMANT = 'TAL_GUARDIAN_ADAMANT_GUARDIAN_INCARNATION'
STATE = 'condition:typed.state.adamant_guardian_second_pass'


def shelter_mods(actor):
    return [m for m in actor.modifiers.values() if m.source_definition_id == ADAMANT + '#shelter']


@pytest.mark.parametrize('allow', [False, True])
def test_adamant_refuses_or_willingly_allows_forced_movement(tmp_path, allow):
    c,t,m=fight(tmp_path,[ADAMANT],left_kit={'items':[]},right_kit={'items':[]},
                  cause=[{'type':'forced_movement','applies_to':'target','direction':'away','distance_ft':5}])
    settle(lambda a:act(t,m,'Adamant Guardian Incarnation',a))
    e=reload(c,m);start=e.state.actors[LEFT].position
    assert any(c.condition_id==STATE for c in e.state.actors[LEFT].conditions.values())
    turn(t,m,RIGHT)
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),choose=lambda p: ['allow' if allow else 'refuse'])
    assert prompts
    e=reload(c,m)
    assert (e.state.actors[LEFT].position!=start)==allow
    assert c._load_session(m).verify()['status']=='PASS'


@pytest.mark.parametrize('ai', [False, True])
def test_adamant_shelter_hard_ally_eligibility_consumption_expiry_and_reach(tmp_path, ai):
    c,t,m=fight(tmp_path,[ADAMANT],ally={},left_kit={'items':[]},right_kit={'items':[]},
                  cause_target='ANY_CREATURE',cause=[{'type':'damage','flat':10,'damage_types':['force'],'applies_to':'target'}],
                  prepare_target='SELF',prepare=[{'type':'condition','condition':'prone','applies_to':'self','duration':'one_minute'}])
    settle(action_sender(c,t,m,'Adamant Guardian Incarnation',ai=ai))
    if ai:
        c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    e=reload(c,m)
    assert not shelter_mods(e.state.actors[ALLY]), 'activation is not a start-of-turn trigger'
    settle(lambda a:act(t,m,'Prepare',a))
    assert not any(x.condition_id=='condition:typed.prone' for x in reload(c,m).state.actors[LEFT].conditions.values())
    # Both sides are within 20 feet. The real LOCAL_AUTO owner makes the start choice.
    turn(t,m,RIGHT)
    if ai:
        c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    turn(t,m,LEFT)
    if ai:
        c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    e=reload(c,m)
    assert len(shelter_mods(e.state.actors[ALLY]))==13
    assert not shelter_mods(e.state.actors[RIGHT])
    assert not shelter_mods(e.state.actors[LEFT])
    from combat.typed_reactions import physical_melee_reach
    assert physical_melee_reach(e,e.state.actors[LEFT])==10
    turn(t,m,RIGHT)
    hp=reload(c,m).state.actors[ALLY].current_hp
    settle(lambda a:act(t,m,'Cause',a,target_id=ALLY))
    e=reload(c,m)
    assert hp-e.state.actors[ALLY].current_hp==5
    assert not shelter_mods(e.state.actors[ALLY])
    hp=e.state.actors[ALLY].current_hp
    settle(lambda a:act(t,m,'Cause',a,target_id=ALLY))
    assert hp-reload(c,m).state.actors[ALLY].current_hp==10
    turn(t,m,LEFT)
    assert len(shelter_mods(reload(c,m).state.actors[ALLY]))==13
    # Decline the following start; the previous generation must expire.
    turn(t,m,RIGHT)
    turn(t,m,LEFT,{'choice:needle.guardian_adamant_shelter':[]})
    assert not shelter_mods(reload(c,m).state.actors[ALLY])
    assert c._load_session(m).verify()['status']=='PASS'
