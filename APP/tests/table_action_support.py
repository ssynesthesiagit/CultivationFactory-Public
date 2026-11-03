"""Native table transaction helpers for worker2 fixtures and acquired Goruden tests.

Keep these calls independent of historical test modules and their unrelated
fixtures, so consumers can be qualified for public CI on their own dependencies.
"""


def act(table, mid, cid, answers=()):
    menu = table.state(mid)['menu']
    return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))


def end_turn(table, mid):
    result = act(table, mid, table.state(mid)['menu']['end_turn'])
    assert result['status'] == 'COMMITTED'
    return result
