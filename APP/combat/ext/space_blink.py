"""Blink Guard's hop out of the triggering attack (AUTO23 Space sphere lane, 2026-10-04).

Owner text (authority/typed_mechanics/rules_text.json, tianxia.talent.space.blink_guard):
"Reaction. Trigger: You are hit by an attack, fail a Dexterity saving throw, or are included in an area
effect you can perceive. Cost: 2 CP. Teleport up to 15 feet to an unoccupied space you can see. If the
triggering attack or effect would no longer reach you from your new position ... the attack misses you.
At CL 15, Blink Guard range becomes 30 feet."

The hop itself is the shared reaction teleport (combat/ext/teleport_steps.py: every legal unoccupied
square within reach is offered, the square farthest from the triggering creature first, a player is
asked and may stay put, and an unanswered fight takes the printed default).  This module only supplies
that hop with the printed reach, reading the record's own level table the way the ability compiler
reads one ("At CL 15, range becomes 30 feet"), so nothing about the hop is re-implemented here.

The printed "the attack misses you" is the ordinary typed ``negate_attack`` row that follows this one on
the same record (combat/typed_executor.py block_negate_attack with ``if_out_of_reach``), so the
negotiation of the attack is the shared one used by Peach-Thief Escape and the other "step out of it"
reactions, and the row order on the record is what makes it read the new position.

A2SPACE: the reviewed Folded Reflexes Insight reuses this effect with fold_step_reach=true.
It reads its owner's compiled Fold Step reach, including Extended Fold; Fold Step owns its
ordinary range limits and explicit exceptions. The generic attacked trigger and scene-use resource are independent of Blink
Guard. No new hook is introduced. Rows without the marker retain Blink Guard's own reach.

Inert without an owned reviewed reaction carrying this effect; no hook answers for other actors.
"""

from __future__ import annotations

from typing import Any

from . import effect


def _reach(ctx: Any, row: dict[str, Any]) -> int:
    """The printed reach at this character's level ("At CL 15, Blink Guard range becomes 30 feet")."""
    feet = int(row.get("distance_ft") or 0)
    if row.get("fold_step_reach"):
        # Folded Reflexes uses Fold Step, including its owned range investments.
        # Read the compiled ability through the public reach query; do not share
        # Blink Guard's distinct CL scaling or reinterpret Extended Fold here.
        from ..typed_executor import teleport_reach

        for action in ctx.engine.action_catalog.values():
            typed = (action.parameters or {}).get("typed") or {}
            if action.owner_id == ctx.actor.entity_id and typed.get("source") == "TAL_SPACE_FOLD_STEP":
                reach = teleport_reach(ctx.engine, ctx.actor, action)
                if reach is not None:
                    return int(reach)
        return feet
    level = int((ctx.numbers or {}).get("cl") or 1)
    for low, high, value in row.get("distance_ft_by_cl") or []:
        if int(low) <= level <= int(high):
            return int(value)
    return feet


@effect("space_blink")
def blink(ctx: Any, row: dict[str, Any]) -> None:
    feet = _reach(ctx, row)
    if feet <= 0 or not ctx.actor.active:
        return
    from . import teleport_steps

    teleport_steps.reaction_teleport(ctx, {**row, "distance_ft": feet,
                                           "name": str(row.get("name") or ctx.action.display_name)})
