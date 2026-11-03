"""Opt-in AC adjustment for one incoming attack, bounded by its printed deadline."""
from typing import Any

from . import effect, hook

CONDITION = 'condition:typed.next_attack_ac'


@effect('next_attack_ac')
def apply(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    for target in _default_subject(ctx, row, harmful=True):
        # Hollow the Armor does not stack with itself, including another user's application.
        ctx.engine._remove_condition(target, CONDITION, ctx.source)
        ctx.engine._apply_condition(target, CONDITION, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, row, target, condition=True),
            data={'amount': int(row['amount'])})


@hook('ac')
def armor_class(engine: Any, target: Any) -> int:
    return sum(int(c.data['amount']) for c in target.conditions.values() if c.condition_id == CONDITION)


@hook('event')
def consume(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    # ATTACK_ROLLED includes the already-computed target AC; consume on hit or miss.
    # A penalty created by the attack's later on-hit effects therefore survives for the next attack.
    if event_type == 'ATTACK_ROLLED':
        for target_id in kwargs.get('target_ids') or ():
            target = engine.state.actors.get(target_id)
            if target is not None and any(c.condition_id == CONDITION for c in target.conditions.values()):
                engine._remove_condition(target, CONDITION, 'system:next_attack_ac.consumed')
