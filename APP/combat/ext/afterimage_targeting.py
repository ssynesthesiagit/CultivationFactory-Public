"""Public image identity shared by Athletics map, attack and nonattack consumers.

No targeting decision or die is resolved here. The server-side binding is
condition.data.image_object_id -> state.map_images RuntimeObjectState, whose owner_id and
component condition_instance_id/source_definition_id match the live condition.
component.intent_id records the creating native intent (empty only if absent).
These identities are primitive strings; projection never publishes the source's
name or treats seeing an image as knowing its owner's location.
"""
from .. import motion, senses
from .condition_ownership import remove_instance

FEATURE = "TAL_ATHLETICS_AFTERIMAGE"
SOURCE = "passive:" + FEATURE


def owned_condition(engine, owner, condition):
    """Exact native source/recipient and sealed compiled ownership, no guesses."""
    return (condition.condition_id == motion.AFTERIMAGE
            and condition.source_definition_id == SOURCE
            and condition.source_actor_id == owner.entity_id
            and condition.target_id == owner.entity_id
            and any(row.get("block") == "motion" and row.get("kind") == "afterimage"
                    and row.get("feature_id") == FEATURE
                    for row in getattr(engine, "typed_passive_rows", {}).get(owner.entity_id, ())))


def image_for_condition(engine, owner, condition):
    """Return the live bound image, or None for missing/mismatched/stale identity."""
    if owner.conditions.get(condition.instance_id) is not condition or not owned_condition(engine, owner, condition):
        return None
    obj = engine.state.map_images.get(condition.data.get("image_object_id"))
    if obj is None or obj.destroyed or obj.suppressed or obj.object_kind != "TEMPORARY_IMAGE":
        return None
    component = obj.component or {}
    if (obj.owner_id != owner.entity_id or component.get("condition_instance_id") != condition.instance_id
            or component.get("source_definition_id") != condition.source_definition_id):
        return None
    return obj


def perceived_image(engine, viewer, owner):
    """Pure public sibling query: perception of the image itself, never its owner."""
    if viewer is None or owner is None or not viewer.active or viewer.position is None:
        return None
    for condition in owner.conditions.values():
        obj = image_for_condition(engine, owner, condition)
        if obj is not None and senses.perceives_object(engine, viewer, obj):
            return obj
    return None


def destroy_image(engine, image_object_id, source_definition_id, actor_id, intent_id=None):
    """Evented exact-instance destruction for interception siblings; returns bool.

Call only after that sibling admits successful targeting. No d2, hit rule,
target admission or observer knowledge is manufactured. Preserve peer component
fields, recording the destroying primitive actor/source/intent receipt.
"""
    obj = engine.state.map_images.get(image_object_id)
    owner = engine.state.actors.get(obj.owner_id) if obj is not None else None
    condition = owner.conditions.get((obj.component or {}).get("condition_instance_id")) if owner is not None else None
    if condition is None or image_for_condition(engine, owner, condition) is not obj:
        return False
    gone = obj.model_copy(update={"destroyed": True, "component": {**obj.component,
        "destroyed_by_actor_id": str(actor_id or ""), "destruction_source_definition_id": str(source_definition_id),
        "destruction_intent_id": str(intent_id or engine._active_intent_id or "")}})
    engine._update_object(gone, source_definition_id, actor_id)
    # The map provider's native OBJECT_UPDATED hook removes exactly this instance.
    # Keep removal explicit/idempotent for sibling callers even if dispatch order changes.
    if condition.instance_id in owner.conditions:
        remove_instance(engine, owner, condition.instance_id, source_definition_id)
    return True
