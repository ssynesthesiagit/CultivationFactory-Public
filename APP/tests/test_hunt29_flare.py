"""Hunt 29 regressions through persisted manual/AI tables; no browsers or live data."""
import pytest

from tests.hunt28_support import ALLY, FOE, OWNER, act, fixture, options, owner_turn, reload, send


def named(table, mid, prefix):
    return [o for g in table.state(mid)['menu']['actions'] if g['label'].startswith(prefix) for o in g['options']]


@pytest.mark.parametrize('owner_auto', [False, True])
@pytest.mark.parametrize('trigger_auto', [False, True])
@pytest.mark.parametrize('decline', [False, True])
def test_scripture_flare_is_owners_choice_and_lasts_until_bearers_next_turn(tmp_path, owner_auto, trigger_auto, decline):
    combat, table, mid = fixture(tmp_path, ['RADIANCE_TAL_JUDGMENT_RAY',
                                         'tianxia.talent.radiance.dawnmark_scripture'])
    ray = next(o for o in options(table, mid, 'Judgment Ray') if o.get('destination') == {'x': 4, 'y': 6})
    assert act(table, mid, ray['candidate_id'])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    from combat.typed_executor import bears_mark
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Dawnmark')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO' if owner_auto else 'MANUAL')
    prompts = []
    for _ in range(5):
        state = table.state(mid)
        if state['menu']['actor_id'] == FOE:
            break
        actor = state['menu']['actor_id']
        eng = combat._load_session(mid).engine
        cid = next(c.candidate_id for c in eng.legal_candidates() if c.kind == 'END_TURN')
        answers = []
        while True:
            # A manual owner's own turn is manual. On other actors' turns the
            # triggering controller and the owner controller are independent.
            auto = owner_auto if actor == OWNER else trigger_auto
            result = send(combat, table, mid, cid, auto, answers, actor=actor)
            if owner_auto:
                combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
            if result['status'] == 'COMMITTED':
                break
            prompt = result['reaction']
            prompts.append(prompt)
            assert 'Dawnmark Scripture' in str(prompt)
            answers.append({**prompt['context'], 'selection': 'DECLINE' if decline else 'USE',
                            'option_ids': [] if decline else [prompt['choice']['options'][0]['id']]})
    else:
        raise AssertionError('bearer turn not reached')
    assert bool(prompts) == (not owner_auto)
    engine = reload(combat, mid)
    denied = lambda eng: [c for c in eng.state.actors[FOE].conditions.values()
                          if c.condition_id.endswith('.reaction_denied')]
    assert bool(denied(engine)) == (owner_auto or not decline)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    # It must survive the caster's start, even if the Dawnmark itself expires.
    owner_turn(table, mid)
    assert bool(denied(reload(combat, mid))) == (owner_auto or not decline)
    for _ in range(5):
        if table.state(mid)['menu']['actor_id'] == FOE:
            break
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    assert not denied(reload(combat, mid))
