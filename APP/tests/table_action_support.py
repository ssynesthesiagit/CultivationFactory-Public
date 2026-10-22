"""Synthetic table-action transport for Worker 2 and Reed Slip regressions.

No integration-test modules, archives, history or owner state are imported.
The real table service still validates decisions and commits every action.
"""


def act(table, mid, cid, answers=()):
    menu = table.state(mid)["menu"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))


def end_turn(table, mid):
    result = act(table, mid, table.state(mid)["menu"]["end_turn"])
    assert result["status"] == "COMMITTED"
    return result
