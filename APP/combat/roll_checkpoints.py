"""Transactional d20 rewrites, before any caller consumes the result."""
from typing import Any

from . import ext


def _optional_user_id(answer: dict[str, Any]) -> str | None:
    """The creature that used the ability, or None when the producer does not say.

    The roll being changed often belongs to a different creature -- an ally rerolls
    another's save -- and the fight log reads the event as "the user rerolled the
    roller", so the owner travels with the answer. Producers written before the key
    existed omit it: the event then keeps exactly the shape it was recorded with, and
    the log falls back to the roll's own creature.
    """
    user_id = answer.get("user_id")
    if user_id is None:
        return None
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("d20 rewrite user_id must be a creature entity id")
    return user_id


def rewrite_d20(engine, roll):
    """Apply a rewrite, then optional bonuses before any outcome is consumed.

    The shared d20_bonus seam serves Court and Serendipity without changing
    the natural d20, advantage mode or saved-fight contracts.
    """
    result = _rewrite_d20(engine, roll)
    if getattr(engine, "_rewriting_d20", False):
        return result
    intent = engine._active_intent
    for answer in ext.run_strict("d20_bonus", engine, result, intent):
        if not isinstance(answer, dict) or type(answer.get("bonus")) is not int or not answer.get("source_id"):
            raise ValueError("d20 bonus requires integer bonus and source_id")
        bonus = answer["bonus"]
        if not bonus:
            continue
        original = result
        result = result.model_copy(update={"modifier": result.modifier + bonus, "total": result.total + bonus})
        payload = {"operation": "bonus", "bonus": bonus, "original": original.model_dump(mode="json"),
                   "result": result.model_dump(mode="json")}
        user_id = _optional_user_id(answer)
        if user_id is not None:
            payload["user_id"] = user_id
        engine._append_event("D20_REWRITTEN", answer["source_id"], actor_id=roll.actor_id, payload=payload)
    return result


def _rewrite_d20(engine, roll):
    if not ext.has("d20_result") or getattr(engine, "_rewriting_d20", False):
        return roll
    engine._rewriting_d20 = True
    try:
        answers = ext.run_strict("d20_result", engine, roll, engine._active_intent)
        if not answers:
            return roll
        if len(answers) != 1:
            raise ValueError("one plugin must own a d20 rewrite")
        answer = answers[0]
        if not isinstance(answer, dict) or not isinstance(answer.get("source_id"), str) or not answer["source_id"]:
            raise ValueError("d20 rewrite requires source_id")
        # Optional: the creature that used the ability, which is not always the one
        # whose roll is rewritten (an ally rerolls another's save). Older producers
        # omit it and the event keeps its recorded shape.
        user_id = _optional_user_id(answer)
        operation = answer.get("operation")
        if operation == "replace":
            natural = answer.get("natural_result")
            if type(natural) is not int or not 1 <= natural <= 20:
                raise ValueError("d20 replacement must be an integer in 1..20")
            result = roll.model_copy(update={"natural_result": natural, "total": natural + roll.modifier})
        elif operation == "reroll":
            # The reroll keeps the original mode and modifier; plugins cannot silently change either.
            drawn = engine.roller.raw_d20(modifier=roll.modifier, actor_id=roll.actor_id,
                                          reason=roll.reason, mode=roll.mode)
            result = drawn.model_copy(update={"roll_id": roll.roll_id, "counter_start": roll.counter_start})
        else:
            raise ValueError("unknown d20 rewrite operation")
        # A save rewrite may recheck the DC with a printed signed modifier.
        # Apply it before observers/riders and callers consume the effective roll.
        bonus = answer.get("save_bonus", 0)
        if type(bonus) is not int:
            raise ValueError("save rewrite bonus must be an integer")
        if bonus:
            context = engine.d20_context(roll)
            if context is None or context["kind"] != "save":
                raise ValueError("save rewrite bonus requires a saving throw")
            result = result.model_copy(update={"modifier": result.modifier + bonus, "total": result.total + bonus})
        engine.state.roll_counter = engine.roller.counter
        payload = {"operation": operation, "original": roll.model_dump(mode="json"),
                   "result": result.model_dump(mode="json")}
        if user_id is not None:
            payload["user_id"] = user_id
        engine._append_event("D20_REWRITTEN", answer["source_id"], actor_id=roll.actor_id, payload=payload)
        return result
    finally:
        engine._rewriting_d20 = False
