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

from . import effect, hook


def spent_units(ctx: Any) -> int:
    """Actual units spent by this activation; used by objects and unbroken_bolt.

    No scaled-pool effect in this context means zero. The transient cache stays
    owned here rather than becoming another plug-in's private-state dependency.
    """
    return int(ctx.damage_cache.get('_pool_spent') or 0)


@hook('technique_cost_floor')
def all_current_pool_cost(engine, actor, source_id, printed, proposed):
    """Root all-pool activations pay their entire pool at native declaration."""
    action = engine.action_catalog.get(source_id)
    if action is None or action.owner_id != actor.entity_id:
        return None
    typed = action.parameters.get('typed') or {}
    floors = {}
    for row in typed.get('effects') or []:
        resource = row.get('resource_id')
        if row.get('type') == 'spend_pool_scaled' and resource in printed:
            floors[resource] = max(printed[resource], int(actor.resources.get(resource, 0)))
    return floors or None


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


def resolved_effects(ctx: Any) -> list[dict[str, Any]]:
    """Copy this activation's effect tree with paid pool scaling applied.

    The object-area consumer uses this when no creature rolled the area damage.
    It neither spends resources nor mutates the compiled action. Ordinary
    actions without a root scaled-pool effect return their unchanged copy.
    """
    rows = copy.deepcopy((ctx.typed or {}).get('effects') or [])
    for row in rows:
        if row.get('type') == 'spend_pool_scaled':
            per = row.get('per_unit') or {}
            _scale(row.get('effects'), int(per.get('sides') or 0),
                   int(per.get('count') or 1) * spent_units(ctx))
    return rows


@effect("spend_pool_scaled")
def spend_pool_scaled(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    resource = str(row["resource_id"])
    paid = sum(int(event.payload.get('amount') or 0) for event in ctx.engine.events
               if event.event_type == 'RESOURCE_SPENT' and event.actor_id == ctx.actor.entity_id
               and event.source_definition_id == ctx.action.source_definition_id
               and event.transaction_id == getattr(ctx.engine, '_transaction_id', None)
               and event.payload.get('resource_id') == resource)
    # Native payment already took every charge at declaration. Gains from a
    # later response belong to the actor, not to this activation's damage.
    left = 0 if paid else int(ctx.actor.resources.get(resource, 0) or 0)
    if left > 0:
        ctx.engine._spend_resource(ctx.actor, resource, left, ctx.source)
    spent = paid or int(row.get("counted_cost") or 0) + left
    per = row.get("per_unit") or {}
    rows = copy.deepcopy(row.get("effects") or [])
    _scale(rows, int(per.get("sides") or 0), int(per.get("count") or 1) * spent)
    ctx.damage_cache["_pool_spent"] = spent
    run_effects(ctx, rows)
