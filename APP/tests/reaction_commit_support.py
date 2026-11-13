"""Commit an action at the table through every reaction prompt it raises.

The shared step for tests that must see a whole action land (all reaction prompts answered "use it"), including the
restored and free Reactions the riders c15 and methods r1 families exercise.

Users: tests/test_riders_c15.py, tests/test_c15_reaction_grants.py, tests/test_methods_r1_table.py.
"""

TOO_MANY_PROMPTS = 12


def commit_all(send, cid, auto, picks=None):
    """Answer each reaction prompt with "use it" (taking ``picks`` for a prompt that offers a choice) until ``cid``
    commits; returns the prompts it answered."""
    answers, prompts = [], []
    for _ in range(TOO_MANY_PROMPTS):
        result = send(cid, answers, auto=auto)
        if result["status"] == "COMMITTED":
            return prompts
        p = result["reaction"]
        prompts.append(p)
        answer = {**p["context"], "selection": "USE"}
        if p.get("choice"):
            pick = (picks or {}).get(p["context"]["reaction_source_id"])
            answer["option_ids"] = [pick] if pick else (p["choice"].get("preferred") or [p["choice"]["options"][0]["id"]])[:1]
        answers.append(answer)
    raise AssertionError("too many prompts")
