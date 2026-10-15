"""Presentation for combat.motion's stored Afterimage; no new motion mechanics."""
from typing import Any

from . import hook
from .. import motion


@hook("status_description")
def motion_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    if row.get("condition_id") != motion.AFTERIMAGE:
        return None
    return {"handling": "The table rolls the visible Afterimage's d2 when targeted and removes it when it takes the attack."}
