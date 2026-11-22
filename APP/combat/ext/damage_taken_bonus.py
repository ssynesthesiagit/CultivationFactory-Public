"""The first damage roll against a creature gains a bonus (riders lane 2, 2026-09-29: Yang's Overgrown Recovery, "Until the start of your
next turn, the first damage roll against that subject gains a bonus equal to your Proficiency Bonus").

    {"type": "next_damage_taken_bonus", "applies_to": "target", "formula": "pb", "duration": "until_start_of_next_turn",
     "evidence": "Until the start of your next turn, ..."}

puts ``condition:typed.damage_taken_bonus`` on the creature (its ``data`` holds the amount, worked out from the user's numbers with the same
formulas as any typed amount); the first damage roll against it from anyone is raised by that amount and the condition is used up. It
also ends at the printed deadline.  Stacking: a second one on the same creature replaces the first.

The bonus is added in ``incoming_damage`` (combat/typed_reactions.defend), which the engine runs for a Factory fighter that takes damage --
the DAMAGE_ROLLED event consumes the grant even if immunity prevents that roll's damage. Fixed damage and healing rolls do not
consume it. A short-lived condition binds the bonus to that roll's damage source until its commit. Deterministic and evented.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .condition_ownership import remove_instance, refresh_owned

CONDITION = "condition:typed.damage_taken_bonus"
PENDING = "condition:typed.damage_taken_bonus.pending"


@effect("next_damage_taken_bonus")
def apply(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    amount = int(row.get("amount") or 0) + int(ctx.formula(row.get("formula")))
    if amount <= 0:
        return
    for target in _default_subject(ctx, row, harmful=True):
        refresh_owned(ctx.engine, target, CONDITION, ctx.actor.entity_id, ctx.source)
        ctx.engine._apply_condition(target, CONDITION, ctx.source, ctx.actor.entity_id, expires_on=effect_expiry(ctx, row, target, condition=True),
                                    data={"amount": amount, "label": f"The first damage roll against it gains +{amount}"})


@hook("incoming_damage")
def add(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str | None, source_actor_id: str | None) -> int:
    held = [c for c in target.conditions.values() if c.condition_id == PENDING
            and c.data.get("damage_source") == source_definition_id
            and c.data.get("damage_actor") == source_actor_id]
    if not held:
        return 0
    amount = max(int(c.data.get("amount") or 0) for c in held)
    for c in held:
        remove_instance(engine, target, c.instance_id, "system:damage_taken_bonus.applied")
    return -amount  # same named benefit does not stack; all first rolls occurred


@hook("event")
def rolled(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type == "DAMAGE_ROLLED":
        if not str(payload.get("reason") or "").startswith("DAMAGE:") or not payload.get("dice"):
            return
        source = engine.events[-1].source_definition_id
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is None:
                continue
            for held in list(target.conditions.values()):
                if held.condition_id != CONDITION:
                    continue
                remove_instance(engine, target, held.instance_id, "system:damage_taken_bonus.consumed")
                engine._apply_condition(target, PENDING, held.source_definition_id, held.source_actor_id, expires_on="END_OF_CURRENT_TURN",
                                        data={"amount": held.data.get("amount", 0), "damage_source": source,
                                              "damage_actor": kwargs.get("actor_id")})
    elif event_type == "DAMAGE_COMMITTED":
        completed_source = engine.events[-1].source_definition_id
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is not None:
                for held in list(target.conditions.values()):
                    if held.condition_id == PENDING and held.data.get("damage_source") == completed_source \
                            and held.data.get("damage_actor") == kwargs.get("actor_id"):
                        remove_instance(engine, target, held.instance_id, "system:damage_taken_bonus.finished")
