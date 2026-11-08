"""Drive lazy square placement through the real table flow.

Since 0b7a87b0 a placed action is one placeholder per action/origin, carrying no
destination. Its cell is bound by the ordinary persisted square choice
`choice:placement_menu.square` after the action is committed, so tests answer
that prompt rather than filtering options by `destination`, which only the
retired eager menu carried. Option ids are `cell:x,y[,z]` (combat/needle.cell_id).

`place` answers that prompt. `square_candidate` instead submits the engine's
exact native candidate for the chosen square, which is what the picker itself
resolves to, for tests that want the square as a first-stage aim.

Shared by test_disease_plague_cloud.py (from MAINREDNEW1C, 7cbc921f) and the
MAINREDRELOAD1B riders and perception tests.
"""

PLACEMENT_SQUARE = "choice:placement_menu.square"


def square_of(option):
    """(x, y, z) of a square option, read from its `cell:x,y[,z]` id."""
    x, y, *rest = option["id"].removeprefix("cell:").split(",")
    return int(x), int(y), int(rest[0]) if rest else 0


def nearest_square(cells, centre_on):
    """The offered square nearest the printed centre (Manhattan, then altitude)."""
    return min(cells, key=lambda o: (abs(square_of(o)[0] - centre_on["x"]) + abs(square_of(o)[1] - centre_on["y"]),
                                     square_of(o)[2]))


def place(table, mid, state, candidate, *, centre_on=None, pick=None, other=None, answers=()):
    """Commit `candidate`, binding its square prompt.

    The square is `pick(options)` if given, else the option nearest `centre_on`,
    else the first offered. Other prompts get `other(prompt)` if given, else a
    DECLINE. Returns the final table result; callers assert its status.
    """
    menu = state["menu"]
    answers = list(answers)
    result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
    for _ in range(16):
        if result["status"] != "REACTION_REQUIRED":
            return result
        prompt = result["reaction"]
        context = prompt["context"]
        if context["reaction_source_id"] == PLACEMENT_SQUARE:
            cells = prompt["choice"]["options"]
            assert cells, prompt
            if pick is not None:
                picked = pick(cells)
            elif centre_on is not None:
                picked = nearest_square(cells, centre_on)
            else:
                picked = cells[0]
            answers.append({**context, "selection": "USE", "option_ids": [picked["id"]]})
        elif other is not None:
            answers.append(other(prompt))
        else:
            answers.append({**context, "selection": "DECLINE"})
        result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
    raise AssertionError("too many placement prompts")


def square_candidate(table, mid, label, xy, *, contains=False):
    """The exact candidate id for the table row `label` aimed at ground square `xy`.

    The row is found in the table's own menu (`contains` matches part of its label), then the square is the
    engine's candidate for that row's source, as the square picker resolves it.
    """
    groups = table.state(mid)["menu"]["actions"]
    source = next(g["source_definition_id"] for g in groups
                  if (label in g["label"] if contains else g["label"] == label))
    engine = table.combat._load_session(mid).engine
    return next(c.candidate_id for c in engine.legal_candidates()
                if c.source_definition_id == source and c.destination is not None
                and (c.destination.x, c.destination.y, c.destination.z) == (*xy, 0))
