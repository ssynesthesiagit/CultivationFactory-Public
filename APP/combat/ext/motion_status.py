"""Presentation and native map representation for Athletics' stored Afterimage.

Movement admission/threshold and targeting decisions belong to their providers.
The native condition event supplies the actual committed position; no arbitrary
square, observer knowledge, AC or Hit Points are invented for this image.
"""
from typing import Any

from . import hook
from .. import motion
from . import afterimage_targeting as images


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


@hook("state_event")
def afterimage_map(engine: Any, event: Any) -> None:
    """Bind one native image at creation, then remove it with its exact condition."""
    if event.event_type == "CONDITION_APPLIED":
        owner = engine.state.actors.get(next(iter(event.target_ids), None))
        condition = owner.conditions.get(event.payload.get("instance_id")) if owner is not None else None
        if condition is None or not images.owned_condition(engine, owner, condition) or owner.position is None:
            return
        from ..gate2_runtime_models import RuntimeObjectState
        # Public map IDs must not encode the hidden owner's creature identity.
        object_id = f"object:image.{event.sequence}"
        if object_id in engine.state.map_images:
            return
        # This is the native post-movement position, copied once. Future movement
        # does not drag the stationary image along or create a second marker.
        obj = RuntimeObjectState(object_id=object_id, object_kind="TEMPORARY_IMAGE",
            owner_id=owner.entity_id, position=owner.position.model_copy(deep=True),
            unattended=True, flammable=False, destroyed=False,
            component={"map_marker": 1, "name": "Afterimage", "blocks": 0,
                "condition_instance_id": condition.instance_id,
                "source_definition_id": condition.source_definition_id,
                "intent_id": str(event.trigger_or_intent_id or ""),
                "description": "A visible image left by movement. It disappears when successfully targeted or at the start of its creator's next turn."})
        engine._update_condition_data(owner, condition, {**condition.data, "image_object_id": object_id}, condition.source_definition_id)
        engine._update_object(obj, condition.source_definition_id, owner.entity_id)
    elif event.event_type == "CONDITION_REMOVED":
        instance_id = event.payload.get("instance_id")
        for obj in list(engine.state.map_images.values()):
            component = obj.component or {}
            if (obj.object_kind == "TEMPORARY_IMAGE" and not obj.destroyed
                    and component.get("source_definition_id") == images.SOURCE
                    and component.get("condition_instance_id") == instance_id
                    and obj.owner_id in event.target_ids):
                engine._update_object(obj.model_copy(update={"destroyed": True}), event.source_definition_id, event.actor_id)
    elif event.event_type == "OBJECT_UPDATED":
        for object_id in event.target_ids:
            obj = engine.state.map_images.get(object_id)
            if obj is None or not obj.destroyed or obj.object_kind != "TEMPORARY_IMAGE":
                continue
            component = obj.component or {}
            owner = engine.state.actors.get(obj.owner_id)
            condition = owner.conditions.get(component.get("condition_instance_id")) if owner is not None else None
            if (condition is not None and images.owned_condition(engine, owner, condition)
                    and condition.data.get("image_object_id") == object_id
                    and component.get("source_definition_id") == condition.source_definition_id):
                from .condition_ownership import remove_instance
                remove_instance(engine, owner, condition.instance_id, event.source_definition_id)
