"""Activation-owned damage choices, shared by Qi potency and Barrage delivery.

Typed multiattacks share their committed intent. A delivery split over intents
may publish a stable identity through damage_activation_identity(ctx). Receipts
contain JSON primitives in the actor's existing turn state; normal transaction
rollback, cold reload and replay therefore own their lifecycle.
"""
from typing import Any


def identity(ctx: Any) -> str:
    from . import ext
    supplied = [value for value in ext.run_strict("damage_activation_identity", ctx) if value is not None]
    if supplied:
        if len(supplied) != 1 or not isinstance(supplied[0], str) or not supplied[0]:
            raise ValueError("one damage activation identity owner is required")
        return supplied[0]
    committed = getattr(ctx.intent, "intent_id", "") or "passive"
    # A triggered feature can own a separate activation inside another actor's
    # intent. The context cache binds its nested packets; the event ordinal
    # separates independent uses, including two uses of the same source.
    return ctx.damage_cache.setdefault("_damage_activation_id",
        f"{committed}:{ctx.typed.get('source') or ctx.source}:{ctx.engine.state.event_sequence}")


def receipt(ctx: Any, owner: str) -> dict:
    """Return this provider's one receipt for the activation, never a sibling's."""
    key = owner + ":" + identity(ctx)
    # The engine retains the existing _round_ namespace across turn resets.
    # These are historical consumption receipts for this fight, not timed
    # benefits: a delayed packet must never reopen an already spent activation.
    receipts = ctx.actor.turn_flags.setdefault("damage_activation_round_receipts", {})
    return receipts.setdefault(key, {"choice": "", "used": False})
