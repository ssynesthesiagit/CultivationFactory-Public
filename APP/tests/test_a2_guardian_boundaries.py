"""Adamant eligibility, predecessor bundle behavior and combat expiry."""
import pytest
from tests.auto_worker1_support import fight, act, reload, settle, turn, LEFT, RIGHT, ALLY
from tests.test_a2_guardian import ADAMANT, STATE, shelter_mods

WITNESS='actor:factory.auto111-witness'


@pytest.mark.parametrize('case', ['bounded', 'outside', 'hidden', 'decline'])
def test_shelter_selects_only_eligible_allies_up_to_pb(tmp_path,case):
    # Two allies and one enemy share the aura; PB 1 makes the bound meaningful.
    c,t,m=fight(tmp_path,[ADAMANT],ally={},extra_witness=True,witness_team='team:factory',left_pb=1,
        left_kit={'items':[]},right_kit={'items':[]},
        positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6},ALLY:{'x':8 if case=='outside' else 3,'y':6 if case=='outside' else 4}},
        prepare_target='ANY_CREATURE',prepare=[{'type':'condition','condition':'invisible','applies_to':'target','duration':'one_minute'}])
    settle(lambda a:act(t,m,'Adamant Guardian Incarnation',a))
    if case=='hidden':
        settle(lambda a:act(t,m,'Prepare',a,target_id=ALLY))
    turn(t,m,RIGHT)
    prompts=[]
    def choose(p):
        if p['context']['reaction_source_id']=='choice:needle.guardian_adamant_shelter':
            prompts.append(p)
            assert p['choice']['maximum']==1
            ids={o['id'] for o in p['choice']['options']}
            assert RIGHT not in ids and LEFT not in ids
            assert (ALLY in ids)==(case not in {'outside','hidden'})
            return [] if case=='decline' else [WITNESS]
        return []
    for _ in range(4):
        if t.state(m)['menu']['actor_id']==LEFT:
            break
        settle(lambda a:act(t,m,'end',a),choose=choose)
    e=reload(c,m)
    assert len(prompts)==1
    assert bool(shelter_mods(e.state.actors[WITNESS]))==(case!='decline')
    assert not shelter_mods(e.state.actors[ALLY])
    assert not shelter_mods(e.state.actors[RIGHT])
    assert c._load_session(m).verify()['status']=='PASS'


@pytest.mark.parametrize('case', ['unowned', 'legacy', 'expired'])
def test_second_pass_is_inert_without_new_live_activation(tmp_path,case):
    def predecessor(bundle):
        if case=='legacy':
            for action in bundle['action_catalog']:
                typed=(action.get('parameters') or {}).get('typed') or {}
                typed['effects']=[e for e in typed.get('effects',[]) if e.get('type')!='guardian_adamant']
    c,t,m=fight(tmp_path,[] if case=='unowned' else [ADAMANT],ally={},bundle_edit=predecessor,
                  maximum_rounds=20,left_kit={'items':[]},right_kit={'items':[]},
                  cause=[{'type':'forced_movement','applies_to':'target','direction':'away','distance_ft':5}])
    if case!='unowned':
        settle(lambda a:act(t,m,'Adamant Guardian Incarnation',a))
    if case=='expired':
        for _ in range(10):
            turn(t,m,RIGHT)
            turn(t,m,LEFT,{'choice:needle.guardian_adamant_shelter':[]})
    e=reload(c,m)
    assert not any(x.condition_id==STATE for x in e.state.actors[LEFT].conditions.values())
    assert not shelter_mods(e.state.actors[ALLY])
    turn(t,m,RIGHT)
    start=reload(c,m).state.actors[LEFT].position
    _,prompts=settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert not any(p['context']['reaction_source_id']=='choice:needle.guardian_adamant_movement' for p in prompts)
    e=reload(c,m)
    assert e.state.actors[LEFT].position!=start
    assert c._load_session(m).verify()['status']=='PASS'
