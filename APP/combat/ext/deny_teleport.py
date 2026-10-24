"""A creature that "cannot teleport" until a stated time (rider lane 3, 2026-09-29).

  deny_teleport  {"applies_to": "target", "duration": "until_end_of_next_turn"}

Headsman's Mandate (Failed Save): "Until the end of its next turn, the target cannot regain HP, cannot benefit from Temporary HP,
and cannot teleport or turn Invisible ...".  The effect puts a timed condition on the creature; the ``teleport_gate`` hook
(typed_executor._teleport, the same gate the sealed road of Cut the Road Behind You uses) stops the creature's own teleport
while it holds the condition -- the CP and action are spent, it stays where it was, and the table says so.  It does not touch a
creature that is moved by someone else's teleport, which is a different effect.
"""
from typing import Any

from . import effect, hook

CONDITION = "condition:typed.deny_teleport"


@effect("deny_teleport")
def deny_teleport(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    for subject in _default_subject(ctx, row, harmful=True):
        if subject.active:
            ctx.engine._apply_condition(subject, CONDITION, ctx.source, ctx.actor.entity_id,
                                        expires_on=effect_expiry(ctx, row, subject, condition=True) or "START_OF_SOURCE_NEXT_TURN",
                                        data={"label": "Cannot teleport"})


@hook("teleport_gate")
def gate(ctx: Any, start: Any, destination: Any) -> bool | None:
    held = any(c.condition_id == CONDITION for c in ctx.actor.conditions.values())
    if not held:
        return None
    from . import placed

    placed.note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} cannot teleport: it stays at ({start.x}, {start.y}).")
    return False
