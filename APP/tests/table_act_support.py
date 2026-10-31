"""Shared table-action helpers used by service-level regression fixtures."""


def act(table, mid, cid, answers=()):
    """Submit a candidate using the active menu's decision and state versions."""
    menu = table.state(mid)["menu"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))


def end_turn(table, mid):
    """Commit the current actor's end-turn option."""
    result = act(table, mid, table.state(mid)["menu"]["end_turn"])
    assert result["status"] == "COMMITTED"
    return result
