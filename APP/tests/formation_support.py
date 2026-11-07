"""Shared table/service helpers for the Formations Sphere lanes (AUTO114).

``settle`` drives a real TabletopService transaction and answers the bounded
prompts a fight actually raises (using the first offered option unless the test
names a different one), ``turn`` hands the initiative round on, and ``reload``
rebuilds the fight from disk and asserts a clean mechanical replay.
"""
from combat.gate5_service import CombatService
from tests.worker2_support import ROOT, act


def settle(table, mid, cid, picks=None):
    answers, prompts = [], []
    for _ in range(20):
        result = act(table, mid, cid, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return prompts
        p = result['reaction']
        prompts.append(p)
        rid = p['context']['reaction_source_id']
        choice = (picks or {}).get(rid, 'first' if rid.startswith('choice:') else None)
        answer = {**p['context'], 'selection': 'USE' if choice is not None else 'DECLINE'}
        if choice is not None and p.get('choice'):
            answer['option_ids'] = ([p['choice']['options'][0]['id']] if choice == 'first'
                                    else choice if isinstance(choice, list) else [choice])
        answers.append(answer)
    raise AssertionError('Too many prompts')


def turn(table, mid, actor):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError(f'{actor} never receives a turn')


def reload(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine