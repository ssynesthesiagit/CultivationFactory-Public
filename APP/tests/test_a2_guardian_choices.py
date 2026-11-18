"""Independent forced-movement consent and clear-effect Shelter recipients."""
from tests.auto_worker1_support import fight, act, reload, settle, turn, LEFT, RIGHT, ALLY
from tests.test_a2_guardian import ADAMANT, shelter_mods


def test_two_pushes_in_one_intent_have_independent_consent(tmp_path):
    push={'type':'forced_movement','applies_to':'target','direction':'away','distance_ft':5}
    c,t,m=fight(tmp_path,[ADAMANT],left_kit={'items':[]},right_kit={'items':[]},cause=[dict(push),dict(push)])
    settle(lambda a:act(t,m,'Adamant Guardian Incarnation',a))
    turn(t,m,RIGHT)
    start=reload(c,m).state.actors[LEFT].position
    choices=[]
    def choose(prompt):
        choices.append(prompt)
        return ['refuse' if len(choices)==1 else 'allow']
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT),choose=choose)
    e=reload(c,m)
    assert len(choices)==2
    assert choices[0]['context']['checkpoint']!=choices[1]['context']['checkpoint']
    assert choices[0]['action']=='Cause'
    assert choices[0]['trigger_actor']=='Visitor'
    assert choices[0]['affected']=='Keeper'
    assert e.grid.distance_ft(start,e.state.actors[LEFT].position)==5
    assert c._load_session(m).verify()['status']=='PASS'


def test_manual_guardian_is_enrolled_for_shelter_during_ai_end_turn_without_ask_reactions(tmp_path):
    """A free start-of-turn choice remains with the manual owner on an AI turn."""
    c,t,m=fight(tmp_path,[ADAMANT],left_kit={'items':[]},right_kit={'items':[]},reaction_ask=False,
                ally={},prepare_target='SELF')
    settle(lambda a:act(t,m,'Adamant Guardian Incarnation',a))
    turn(t,m,RIGHT)
    c.set_controller_mode(m,actor_id=RIGHT,controller_mode='LOCAL_AUTO')
    result=None
    while t.state(m)['menu']['actor_id']==RIGHT:
        result=t.auto_step(m,t.state(m)['last_sequence'],[])
        if result['status']=='REACTION_REQUIRED':
            break
        assert result['status']=='COMMITTED', result
    assert result['status']=='REACTION_REQUIRED', result
    prompt=result['reaction']
    assert prompt['reaction']=='Adamant Guardian: Shelter the Weak'
    assert [o['id'] for o in prompt['choice']['options']]
    # The prompt survives a cold service reload and the player's answer commits it.
    fresh=reload(c,m)
    assert c._load_session(m).verify()['status']=='PASS'
    state=t.state(m)
    answer={**prompt['context'],'selection':'USE','option_ids':[prompt['choice']['options'][0]['id']]}
    result=t.auto_step(m,state['last_sequence'],[answer])
    assert result['status']=='COMMITTED', result
    fresh=reload(c,m)
    assert len(shelter_mods(fresh.state.actors[ALLY]))==13
    assert any('If that attack dealt no damage, put the protection back' in str(event) for event in t.events(m,0)['events'])
    assert c._load_session(m).verify()['status']=='PASS'


def test_manual_guardian_owns_push_consent_during_ai_action_without_ask_reactions(tmp_path):
    push={'type':'forced_movement','applies_to':'target','direction':'away','distance_ft':5}
    c,t,m=fight(tmp_path,[ADAMANT],left_kit={'items':[]},right_kit={'items':[]},reaction_ask=False,
                cause=[push])
    settle(lambda a:act(t,m,'Adamant Guardian Incarnation',a))
    turn(t,m,RIGHT)
    from tests.auto_worker1_support import action_sender
    send=action_sender(c,t,m,'Cause',ai=True,target_id=LEFT)
    result=send([])
    assert result['status']=='REACTION_REQUIRED', result
    prompt=result['reaction']
    assert prompt['action']=='Cause'
    assert prompt['trigger_actor']=='Visitor'
    assert prompt['affected']=='Keeper'
    assert 'Cause' in prompt['moment']
    assert c._load_session(m).verify()['status']=='PASS'
    state=t.state(m)
    answer={**prompt['context'],'selection':'USE','option_ids':[prompt['choice']['options'][0]['id']]}
    result=t.auto_step(m,state['last_sequence'],[answer])
    assert result['status']=='COMMITTED', result
    fresh=reload(c,m)
    assert c._load_session(m).verify()['status']=='PASS'


def test_shelter_does_not_cross_blocked_effect_ray_even_with_sight(tmp_path,monkeypatch):
    from combat import targeting,stealth
    c,t,m=fight(tmp_path,[ADAMANT],ally={},left_kit={'items':[]},right_kit={'items':[]})
    settle(lambda a:act(t,m,'Adamant Guardian Incarnation',a))
    e=reload(c,m)
    assert stealth.sees(e,e.state.actors[LEFT],e.state.actors[ALLY])
    real=targeting.line_of_effect
    # Isolate a transparent effect-blocker at the public geometry query; all
    # ability ownership, turn choices, modifier delivery and persistence are real.
    def glass(engine,actor,*,target=None,destination=None):
        if actor.entity_id==LEFT and target is not None and target.entity_id==ALLY:
            return False
        return real(engine,actor,target=target,destination=destination)
    monkeypatch.setattr(targeting,'line_of_effect',glass)
    turn(t,m,RIGHT);turn(t,m,LEFT)
    assert not shelter_mods(reload(c,m).state.actors[ALLY])
    assert c._load_session(m).verify()['status']=='PASS'
