"""Shared table-fight helpers for the Talismans tests: take a menu button and answer its prompts.

Used by tests/test_auto10_talismans.py and tests/test_mgr_t14_talisman_scribe.py. Moved out of the auto10 module
so that the Scribe tests do not import a module that also holds a git-history replay.
"""
from tests.hunt12_support import ME as TABLE_ME, send


def answer(prompt, option_id):
    return {**prompt["context"], "selection": "USE", "option_ids": [option_id]}


def options(prompt):
    return {row["id"]: row["label"] for row in prompt["choice"]["options"]}


def pick(prompt, needle):
    """The offered option whose label contains ``needle``."""
    offered = options(prompt)
    if "cultivation points" in needle:
        assert all(" CP" not in label for label in offered.values())
    return next(key for key, label in offered.items() if needle in label)


def chooser(combat, mid, *, prefix=None, name=None, target=None):
    """The fighter's menu button by name (prefix or exact) and, when the button has one, its target."""
    def matches(candidate_row):
        label = str(candidate_row.display_name)
        if name is not None and label != name:
            return False
        if prefix is not None and not label.startswith(prefix):
            return False
        if target is not None and tuple(candidate_row.target_ids or ()) != (target,):
            return False
        return candidate_row.actor_id == TABLE_ME

    return next(row for row in combat._load_session(mid).engine.legal_candidates() if matches(row))


def press(combat, table, mid, steps=(), *, prefix=None, name=None, target=None):
    """Take a button, answering each prompt in turn.

    Each step answers one prompt: the option with that exact id when the prompt offers it (a creature's entity id, ""
    for the caster's own hand), otherwise the option whose label holds the text.  A prompt with no step left takes
    its first option.  Returns the prompts, so a test can read what was offered.
    """
    chosen = chooser(combat, mid, prefix=prefix, name=name, target=target)
    answers, prompts = [], []
    response = send(combat, table, mid, chosen, answers)
    while response["status"] == "REACTION_REQUIRED":
        prompt = response["reaction"]
        prompts.append(prompt)
        offered = options(prompt)
        if len(answers) < len(steps):
            wanted = steps[len(answers)]
            option = wanted if wanted in offered else pick(prompt, wanted)
        else:
            option = next(iter(offered))
        answers.append(answer(prompt, option))
        response = send(combat, table, mid, chosen, answers)
    assert response["status"] == "COMMITTED", response
    return prompts
