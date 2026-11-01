"""Transactional d20 rewrites, before any caller consumes the result.

Native callers must resolve modes BEFORE drawing. Gate2Engine.roll_check merges
actor-wide/scoped check rules with independent unresolved sources; auxiliary
attack/save callers use direct_attack_mode/direct_save_mode. Already resolved
native callers keep their full source-set resolution. Never add a new source to
a cancelled NORMAL: retain both original contributions until final cancellation.
The existing post-draw hook consumes allowances even on a cancelled NORMAL roll.
Raw rerolls preserve the settled mode and do not open a second consumption hook.
"""
from collections.abc import Iterator
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

    Each strict d20_bonus provider sees the effective result, including earlier
    bonuses. Optional consent therefore tests the current outcome. Neither
    bonuses nor their events reopen the exclusive d20 rewrite checkpoint.
    Strict d20_finalized observers then settle riders/text on this final record;
    pauses and errors unwind the same action transaction as bonus consent.
    """
    result = _rewrite_d20(engine, roll)
    if getattr(engine, "_rewriting_d20", False):
        return result
    intent = engine._active_intent
    for provider in ext.subscribers("d20_bonus"):
        reply = provider(engine, result, intent)
        if reply is None:
            continue
        if isinstance(reply, dict):
            answers = (reply,)
        elif isinstance(reply, Iterator):
            answers = reply
        else:
            raise ValueError("d20 bonus provider requires a dict or lazy iterator of dicts")
        for answer in answers:
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
    ext.run_strict("d20_finalized", engine, result, intent)
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


def prepare_d20(engine, request):
    """Consent to a fixed natural result before drawing; default-inert.

    Use the normal draw slot after consent to keep unique roll identities and
    deterministic counters. The hidden draw never reaches the deciding hook.
    Existing post-roll hooks consume the effective record as usual.
    """
    answers = ext.run_strict("before_d20", engine, dict(request), engine._active_intent)
    if not answers:
        return None
    if len(answers) != 1:
        raise ValueError("one plugin must own a pre-roll replacement")
    answer = answers[0]
    if (not isinstance(answer, dict) or not isinstance(answer.get('source_id'), str)
            or not answer['source_id'] or type(answer.get('natural_result')) is not int
            or not 1 <= answer['natural_result'] <= 20):
        raise ValueError("pre-roll replacement requires source_id and natural_result in 1..20")
    original = engine.roller.raw_d20(**request)
    result = original.model_copy(update={'natural_result': answer['natural_result'],
                                         'dice': tuple(answer['natural_result'] for _ in original.dice),
                                         'discarded': tuple(answer['natural_result'] for _ in original.discarded),
                                         'total': answer['natural_result'] + original.modifier})
    engine.state.roll_counter = engine.roller.counter
    engine._append_event('D20_REWRITTEN', answer['source_id'], actor_id=request['actor_id'],
                         payload={'operation': 'replace', 'timing': 'before_roll',
                                  'original': original.model_dump(mode='json'),
                                  'result': result.model_dump(mode='json')})
    return result
