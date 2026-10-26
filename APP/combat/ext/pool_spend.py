"""Spend what is left of a named pool and scale an ability's dice by everything spent (rider lane C7, 2026-09-30).

Shared by abilities printed as "Cost: ... and all current <Pool>" with damage "+1d10 per <unit> spent" (Adamantine Descent:
"7 Stamina and all current Thunder Charges", "8d10 ... + 1d10 per Charge spent"). The action's typed cost pays the printed
minimum (so an ability that needs "at least 3 Charges" is only offered with 3); this effect spends the rest when the ability
resolves and runs its nested effects with the extra dice:

    {"type": "spend_pool_scaled", "resource_id": "resource:named.thunder_charge", "counted_cost": 3,
     "per_unit": {"count": 1, "sides": 10}, "effects": [ ...rows run with the scaled dice... ]}

``counted_cost`` is how many units the action's own cost already spent (they count as spent). Every damage/extra_damage row
nested in ``effects`` whose dice have ``per_unit.sides`` sides gains ``per_unit.count`` dice per unit spent; the rows are
copied, never the character's compiled definitions. Spending uses the engine's evented _spend_resource. Inert for any other
action: nothing happens unless an owned typed action carries the row.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect


def _scale(rows: Any, sides: int, extra: int) -> None:
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        dice = row.get("dice")
        if row.get("type") in ("damage", "extra_damage") and isinstance(dice, dict) and int(dice.get("sides") or 0) == sides \
                and dice.get("count") is not None:
            row["dice"] = {**dice, "count": int(dice["count"]) + extra}
        for key in ("on_fail", "on_success", "on_hit", "on_miss", "effects"):
            _scale(row.get(key), sides, extra)


@effect("spend_pool_scaled")
def spend_pool_scaled(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    resource = str(row["resource_id"])
    left = int(ctx.actor.resources.get(resource, 0) or 0)
    if left > 0:
        ctx.engine._spend_resource(ctx.actor, resource, left, ctx.source)
    spent = int(row.get("counted_cost") or 0) + left
    per = row.get("per_unit") or {}
    rows = copy.deepcopy(row.get("effects") or [])
    _scale(rows, int(per.get("sides") or 0), int(per.get("count") or 1) * spent)
    ctx.damage_cache["_pool_spent"] = spent
    run_effects(ctx, rows)
