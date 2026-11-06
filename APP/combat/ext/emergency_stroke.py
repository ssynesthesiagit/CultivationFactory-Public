"""Emergency Stroke's physical requirement, using native equipment/hold occupancy.

The existing talismans provider owns creation, CP costs and formula consumption.
This plug-in only enforces the printed free hand for its stroke deliveries;
readying an existing talisman and unrelated actions are unaffected. Writing
materials and legal surfaces still require a separate authoritative producer.
"""
from typing import Any

from . import hook
from .hand_occupancy import free_hands
from .talismans import BASE_STROKE


@hook("candidate_allowed")
def require_stroke_hand(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or action.owner_id != actor.entity_id:
        return None
    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("source") != BASE_STROKE:
        return None
    # Ready a talisman shares this source but retrieves an existing item.
    if not any(row.get("type") == "talisman_stroke" and row.get("variant") != "ready"
               for row in typed.get("effects") or []):
        return None
    return False if not free_hands(engine, actor) else None
