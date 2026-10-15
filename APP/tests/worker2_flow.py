"""Turn-settling helpers shared by the cloud worker-2 table tests (ported with AUTO125).

`test_auto35_yang.py` upstream defines these three next to its own Yang tests, and imports
`combat.ext.yang_recovery.ROUND`, which does not exist on main. These helpers have no Yang
dependency, so they live here as a support module and the AUTO48 Radiance test imports them
from here instead.
"""
from combat.gate5_service import CombatService
from tests.worker2_support import ROOT, act


def settle(table, mid, cid, picks=None):
    """Run one candidate to completion, answering every reaction prompt (default: decline)."""
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
    """Advance the table's turn order until it is `actor`'s turn."""
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('No turn')


def reload(tmp_path, mid):
    """Reload the fight from disk, asserting the saved replay still verifies."""
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine
