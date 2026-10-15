"""Presentation for combat.motion's stored Afterimage; no new motion mechanics."""
from typing import Any

from . import hook
from .. import motion


@hook("committed_teleport_receipt")
def teleport_distance(engine: Any, receipt: dict[str, int | str]) -> None:
    """Owned distance evidence only; progress/threshold creation is separate."""
    from .ability_source import compiled_feature_rows

    if (not receipt["self_teleport"] or not receipt["willing"]
            or int(receipt["distance_ft"]) <= 0
            or not any(row.get("block") == "motion" and row.get("kind") == "afterimage"
                       for row in compiled_feature_rows(engine, receipt["actor_id"], "TAL_ATHLETICS_AFTERIMAGE"))):
        return
    if any(event.event_type == "PASSIVE_TRIGGERED"
           and event.payload.get("receipt_id") == receipt["receipt_id"] for event in engine.events):
        return
    engine._append_event("PASSIVE_TRIGGERED", receipt["source_definition_id"],
                         actor_id=receipt["actor_id"], trigger_or_intent_id=receipt["intent_id"],
                         payload={**receipt, "receipt_kind": "motion_distance_receipt",
                                  "log": f'{engine.state.actors[receipt["actor_id"]].display_name} '
                                         f'teleports {receipt["distance_ft"]} feet willingly.'})


@hook("status_description")
def motion_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    if row.get("condition_id") != motion.AFTERIMAGE:
        return None
    return {"handling": "The table rolls the visible Afterimage's d2 when targeted and removes it when it takes the attack."}
