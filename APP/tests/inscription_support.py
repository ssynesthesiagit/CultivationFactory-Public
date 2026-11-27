"""Public synthetic writing and table choices for Talismans reading regressions."""


def writing(*, family="Attack", rank="common"):
    return {"id": 900, "x": 4, "y": 6, "kind": "custom", "material": "paper", "size": "tiny",
            "properties": {"inspection": {"kind": "inscription", "facts": {
                "family": family, "rank": rank, "activation": "touch", "integrity": "stable",
                "connection": "door", "safe_touch": 0}}}}


def add_writing(arena, *, family="Attack"):
    arena["map_objects"] = [*(arena.get("map_objects") or []), writing(family=family)]
    return arena


def press(combat, table, mid, *, name, steps=()):
    """Submit the real menu candidate, retaining the existing reading assertions.

    This small synthetic-fixture transport does not import capture/history tests.
    """
    from tests.hunt12_support import send
    chosen = next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name == name)
    answers, prompts = [], []
    result = send(combat, table, mid, chosen)
    while result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        prompts.append(prompt)
        options = {row["id"]: row["label"] for row in prompt["choice"]["options"]}
        wanted = steps[len(answers)] if len(answers) < len(steps) else next(iter(options))
        option = wanted if wanted in options else next(key for key, label in options.items() if wanted in label)
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [option]})
        result = send(combat, table, mid, chosen, answers)
    assert result["status"] == "COMMITTED", result
    return prompts
