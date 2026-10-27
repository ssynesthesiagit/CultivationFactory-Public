"""Momentum Marks acquisition and encounter expiry for Warleader.

The existing warleader provider owns gains, spending and Incapacitated expiry.
Its public MOMENTUM constant is shared here; no second gain implementation is
registered. compile_resources supplies the printed PB-sized, initially empty
pool even when a sheet records its acquired sphere without the redundant base
component cache. The ordinary MATCH_ENDED event empties remaining Marks through
the resource journal, including on inactive leaders. A running match has no
short/long-rest action; starting another encounter compiles an empty pool.

Both hooks are inert for characters without Warleader or its exact base row.
"""
from typing import Any

from . import hook, note
from .warleader import MOMENTUM

OWNER = "WARLEADER_BASE_MOMENTUM_MARKS"
SPHERE = "tianxia.sphere.warleader"


@hook("compile_resources")
def momentum_pool(info: dict[str, Any]) -> list | None:
    if OWNER not in (info.get("owned_ids") or ()) and SPHERE not in (info.get("spheres") or ()):
        return None
    from ..gate2_runtime_models import ResourceDefinition

    return [ResourceDefinition(resource_id=MOMENTUM, initial=0, maximum=int(info["pb"]))]


@hook("state_event")
def encounter_ends(engine: Any, event: Any) -> None:
    # The native checkpoint also receives combat endings caused inside another
    # event subscriber; the outer controller's event hook can suppress those.
    if event.event_type != "MATCH_ENDED":
        return
    for leader in engine.state.actors.values():
        amount = int(leader.resources.get(MOMENTUM, 0))
        if amount:
            engine._spend_resource(leader, MOMENTUM, amount, OWNER)
            note(engine, OWNER, leader, f"Combat ends: {leader.display_name} loses every Momentum Mark.")
