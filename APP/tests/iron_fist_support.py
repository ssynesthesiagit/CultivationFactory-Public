"""Shared by table tests whose manual Iron Fist strikes now meet Iron Fist's printed per-strike damage-type question
(L45, 2026-10-01: "Choose the damage type when you make the attack"; combat/ext/body_iron_fist.py).

These tests are about something else (Extra Attack labels, Pressure Points, Flowing Combination, critical dice ...), so
the helper answers only that question, with the table's own automatic pick (``choice.preferred``: the type that lands
hardest, the type these strikes dealt before the question existed), and hands every other prompt back unchanged.
The question itself is tested in tests/test_body_refining_choices.py.
"""
from typing import Any, Callable

IRON_FIST_DAMAGE_TYPE = "choice:needle.iron_fist_damage_type"


def is_iron_fist_question(result: dict[str, Any]) -> bool:
    prompt = result.get("reaction") if result.get("status") == "REACTION_REQUIRED" else None
    return bool(prompt) and prompt["context"]["reaction_source_id"] == IRON_FIST_DAMAGE_TYPE


def automatic_answer(prompt: dict[str, Any]) -> dict[str, Any]:
    return {**prompt["context"], "selection": "USE", "option_ids": list(prompt["choice"]["preferred"][:1])}


def answering_iron_fist(call: Callable[[list], dict[str, Any]], *, initial_answers=()) -> Callable[..., dict[str, Any]]:
    """Wrap ``call(answers)`` (a table.act / auto_step closure): the caller's answers plus automatic Iron Fist
    damage-type answers; returns the first result that is not that question.

    Retain the submitted prefix while another choice is pending. A wrapper
    recreated after table reload can receive that saved prefix explicitly.
    """
    def wrapped(answers=()):
        # An empty request resumes the saved question without discarding the
        # answers that preceded it. Deliver each new answer in that exact order,
        # including when this helper was reconstructed between table requests.
        result = call([])
        carried: list[dict[str, Any]] = []
        key = lambda row: tuple(row.get(k) for k in ('checkpoint', 'reactor_id', 'reaction_source_id'))
        for _ in range(24):
            if result.get('status') != 'REACTION_REQUIRED':
                return result
            pending = (result.get('state') or {}).get('pending_action') or {}
            carried = list(pending.get('reactions', carried))
            prompt = result['reaction']
            supplied = next((a for a in answers if key(a) == key(prompt['context'])), None)
            if supplied is not None:
                chosen = supplied
            elif is_iron_fist_question(result):
                chosen = automatic_answer(prompt)
            else:
                return result
            carried.append(chosen)
            result = call(carried)
        raise AssertionError("more Iron Fist damage-type questions than strikes")
    return wrapped
