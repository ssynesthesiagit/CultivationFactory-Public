"""Real table-commit helpers shared by service tests.

``act`` submits one candidate on the current menu and ``end_turn`` ends the pending turn; both go
through a real TabletopService commit. They live here (not in a test module) so fixtures such as
tests/worker2_support.py can drive the table without importing another lane's historical fight.
"""


def act(table, mid, cid, answers=()):
    menu = table.state(mid)["menu"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))


def end_turn(table, mid):
    result = act(table, mid, table.state(mid)["menu"]["end_turn"])
    assert result["status"] == "COMMITTED"
    return result
