"""A creature that "cannot take Bonus Actions" (rider lane 9, 2026-09-29): Jester's Absurd Agreement, The Whole Court Laughs and
Ten-Thousand Masks Procession print it, and no condition on the table carried it.  The typed condition ``no_bonus_actions``
(combat/rules/typed_conditions.json) is applied like any other typed condition (a "condition" row with a duration); while a creature
bears it, none of its Bonus Action choices is offered (candidate_allowed).  Nothing else about the creature changes.
"""

from __future__ import annotations

from typing import Any

from . import hook

CONDITION = "condition:typed.no_bonus_actions"


@hook("candidate_allowed")
def no_bonus_actions(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if str(getattr(candidate, "kind", "")) != "BONUS_ACTION" or not actor.conditions:
        return None
    return False if any(row.condition_id == CONDITION for row in actor.conditions.values()) else None
