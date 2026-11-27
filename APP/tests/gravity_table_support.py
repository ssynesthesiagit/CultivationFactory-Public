"""Shared Gravity table and area helpers for AUTO67 and A2 regressions."""

def _area(engine, prefix, at=None):
    """The name of an area's point-targeted candidate: "Gravity Well at 8,6"."""
    names = sorted({c.display_name for c in engine.legal_candidates() if c.display_name.startswith(prefix)})
    assert names, f"{prefix!r} is not legal; legal: {sorted({c.display_name for c in engine.legal_candidates()})[:20]}"
    if at is not None:
        pick = next((n for n in names if n.split(" at ")[-1].split(" ")[0] == f"{at[0]},{at[1]}"), None)
        assert pick, f"{prefix!r} has no candidate at {at}; it offers {names[:8]}"
        return pick
    return names[0]



def _table_send(table, match_id, candidate_id, answers=()):
    state = table.state(match_id)
    return table.act(match_id, candidate_id, state["menu"]["decision_id"], state["menu"]["state_version"],
                     state["last_sequence"], list(answers))


def _table_press(table, match_id, label, answer=None):
    """Press the table button carrying ``label``, answering every question it puts to the player in turn. "End Turn" is the
    menu's own button rather than an action group. ``answer(question) -> option ids`` chooses among the printed options; the
    default takes the table's own first choice, so a committed turn never depends on a lucky die."""
    menu = table.state(match_id)["menu"]
    candidate_id = menu["end_turn"] if label == "End Turn" else next(
        option["candidate_id"] for group in menu["actions"] if label in group["label"] for option in group["options"])
    asked = []
    answers = []
    for _ in range(20):
        result = _table_send(table, match_id, candidate_id, answers)
        if result["status"] == "COMMITTED":
            return result, asked
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        asked.append(prompt)
        choice = prompt.get("choice") or {}
        picked = answer(prompt, choice) if answer else None
        reply = {**prompt["context"], "selection": "DECLINE"}
        if choice and (picked is None or picked is not False):
            reply.update(selection="USE", option_ids=list(picked or (choice.get("preferred")
                                                                     or [choice["options"][0]["id"]])[:1]))
        answers.append(reply)
    raise AssertionError("the table never committed the printed choice")


