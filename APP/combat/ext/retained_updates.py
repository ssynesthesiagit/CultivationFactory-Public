"""Replay-only instance updates shared by event dispatch and history readers.

end_effect retains an instance while suppressing/restoring it. The existing
application event carries its complete reducer snapshot, but is not a fresh
application. ext dispatch, pressure, shield_riders, riders_shared and history_feed
use this predicate so bookkeeping cannot trigger abilities or reset provenance.
Unmarked events, including old saved fights, keep their original semantics.
end_effect and ice_fracture also use record_instance_update after bookkeeping
changes so the existing reducer snapshot records them without new applications.
water_return uses record_zone_update for area movement; it shares the same
subscriber guard and history predicate without changing creation or expiry.
"""
from typing import Any


def is_retained_update(event_type: str, payload: dict[str, Any]) -> bool:
    """True only for explicitly marked condition/modifier/zone replay upserts."""
    return event_type in ("CONDITION_APPLIED", "MODIFIER_APPLIED", "ZONE_CREATED") and payload.get("retained_instance_update") == 1


def record_zone_update(engine: Any, zone: Any) -> None:
    """Record a retained area's full snapshot without fresh creation subscribers.

    Water Return uses this for relocation; area movement and placement helpers
    can use it for bookkeeping updates without changing identity or lifetime.
    The caller still synchronizes inside effects after changing geometry.
    """
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id,
                         payload={"zone": zone.model_dump(mode="json"), "retained_instance_update": 1})


def record_instance_update(engine: Any, holder: Any, kind: str, key: str, item: Any) -> None:
    """Record a changed retained condition/modifier, preserving source and expiry.

    Gate 3 enriches the event with the retained instance's complete snapshot.
    Fresh-application subscribers ignore the documented update marker.
    """
    if kind == "condition":
        event_type = "CONDITION_APPLIED"
        payload = {"condition_id": item.condition_id, "instance_id": key,
                   "stacks": item.stacks, "expires_on": item.expires_on}
    elif kind == "modifier":
        event_type = "MODIFIER_APPLIED"
        payload = {"modifier_id": key, "target_field": item.target_field,
                   "operation": item.operation, "value": item.value,
                   "applies_to": item.applies_to, "expires_on": item.expires_on}
    else:
        raise ValueError(f"Unsupported retained instance kind: {kind}")
    payload["retained_instance_update"] = 1
    engine._append_event(event_type, item.source_definition_id, actor_id=item.source_actor_id,
                         target_ids=(holder.entity_id,), payload=payload)
