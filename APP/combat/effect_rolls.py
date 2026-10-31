"""Shared non-d20 amount rolls for typed effects, reactions and plug-in responses.

Consumers: typed_executor, typed_reactions and ext.yang_sun_marks.
Callers retain event recording and delivery; providers can shape the effective dice
before either occurs. No provider leaves the deterministic draw unchanged.
"""
from typing import Any


def roll_amount(engine: Any, actor: Any, spec: Any, source: str, reason: str, *,
                critical: bool = False) -> Any:
    from . import ext

    roll = engine.roller.roll(spec, actor_id=actor.entity_id, reason=reason, critical=critical)
    for replacement in ext.run_strict("amount_roll", engine, actor, source, spec, roll):
        if replacement is not None:
            roll = replacement
    return roll
