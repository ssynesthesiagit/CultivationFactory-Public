"""Shared durable item retirement for combat and journey continuation.

Consumers: carry projects inventory/load; scoundrel_riders projects custody;
weapon_delivery/equipment_hands project usable gear; armour projects shield AC;
thread_handling validates journey garments. equipment_armor/goruden use carry
for worn-item queries. objects' native state_event and unmaking_channels/shield_riders call destroy.
The original compiled bundle is a blueprint, never a mutable inventory. One
permanent condition on the inventory owner retires one exact physical identity.
It replays with ordinary conditions and crosses encounters in journey_setup's
encounter_snapshot. Standalone fights never write to a character sheet.
"""
from __future__ import annotations

import json
from typing import Any

from . import hook

DESTROYED = "condition:typed.destroyed_item"


def identity(owner_id: str, key: str) -> str:
    """Stable inventory identity, also used by scoundrel transfers and objects."""
    return f"{owner_id}|{key}"


def is_destroyed(actor: Any, *, key: str = "", weapon: str = "") -> bool:
    """Pure retirement query; absent records leave every other item unchanged."""
    weapon = weapon.split("#", 1)[0]
    return actor is not None and any(
        row.condition_id == DESTROYED and (
            (key and row.data.get("item_key") == key)
            or (weapon and row.data.get("disables_action") == weapon))
        for row in actor.conditions.values())


def _weapon_owner(engine: Any, actor: Any, weapon: str) -> tuple[Any, str]:
    weapon = weapon.split("#", 1)[0]
    action = engine.action_catalog.get(weapon)
    if action is not None and action.parameters.get("requires_held_weapon"):
        weapon = str(action.parameters["requires_held_weapon"])
        action = engine.action_catalog.get(weapon)
    owner = engine.state.actors.get(action.owner_id) if action is not None else None
    return owner or actor, weapon


def weapon_destroyed(engine: Any, actor: Any, weapon: str) -> bool:
    """Equipment/delivery query including a borrowed item's original owner."""
    owner, weapon = _weapon_owner(engine, actor, weapon)
    return is_destroyed(owner, weapon=weapon)


def carrying_view(carrying: dict[str, Any] | None, actor: Any) -> dict[str, Any] | None:
    """Read the original inventory through its owner's one retirement record."""
    if carrying is None:
        return None
    retired = [item for item in carrying.get("items") or []
               if is_destroyed(actor, key=str(item.get("key") or ""))]
    if not retired:
        return carrying
    from ..carry import pounds
    keys = {item["key"] for item in retired}
    weight = max(0, pounds(carrying.get("weight_lb")) - sum(pounds(item.get("weight_lb")) for item in retired))
    return {**carrying, "items": [item for item in carrying.get("items") or [] if item.get("key") not in keys],
            "weight_lb": f"{weight:g}", "over": weight > int(carrying.get("capacity_lb") or 0)}


def journey_carrying(actor: dict[str, Any]) -> dict[str, Any] | None:
    """Journey readers use the same snapshot record, not the original bundle."""
    from types import SimpleNamespace
    from ..gate2_runtime_models import ConditionInstance
    conditions = {key: ConditionInstance.model_validate(json.loads(row))
                  for key, row in actor.get("encounter_snapshot", {}).get("conditions", {}).items()}
    return carrying_view(actor["bundle"].get("carrying"), SimpleNamespace(conditions=conditions))


def destroy(engine: Any, owner: Any, *, source: str, key: str = "",
            weapon: str = "", actor_id: str | None = None, why: str = "destroyed") -> bool:
    """The only item-destruction writer; True exactly once per physical item.

    Call after an effect's prevention/protection has resolved. Keys identify real
    inventory rows; weapon-only channels without an inventory row retain their
    exact action identity. Custody never changes the original inventory owner.
    Old placement/readiness receipts are history, not a way to recreate an item.
    """
    from .. import carry
    if weapon and not key:
        owner, weapon = _weapon_owner(engine, owner, weapon)
    item = carry.item_of(carry.carrying_of(engine, owner.entity_id, include_destroyed=True),
                         key=key, weapon_action=weapon)
    if item is not None:
        key = str(item["key"])
        weapon = str(item.get("weapon_action") or weapon)
    elif key or not weapon:
        return False
    if is_destroyed(owner, key=key, weapon=weapon):
        return False
    name = str((item or {}).get("name") or
               getattr(engine.action_catalog.get(weapon), "display_name", "Item")).removesuffix(" attack")
    data = {"label": f"{name} is destroyed ({why}); it cannot be equipped or used."}
    if key:
        data.update(item_key=key, object_id=identity(owner.entity_id, key))
    if weapon:
        data["disables_action"] = weapon
    engine._apply_condition(owner, DESTROYED, source, actor_id or owner.entity_id,
                            expires_on="UNTIL_REMOVED", data=data, unavoidable=True)
    # Retire placement receipts, not merely their visual hand occupant. Native
    # pickup/recovery also reads these records; debris is not a dropped weapon.
    for filed in engine.state.actors.values():
        for iid, row in list(filed.conditions.items()):
            placement = row.data or {}
            if not (placement.get("held_by") or placement.get("dropped_at")):
                continue
            physical = str(placement.get("object_id") or identity(filed.entity_id, str(placement.get("item_key") or "")))
            if ((key and physical == identity(owner.entity_id, key))
                    or (weapon and placement.get("disables_action") == weapon)):
                del filed.conditions[iid]
                engine._append_event("CONDITION_REMOVED", source, actor_id=actor_id or owner.entity_id,
                    target_ids=(filed.entity_id,), payload={"condition_id": row.condition_id, "instance_id": iid})
        retired_actions = {action.source_definition_id for action in engine.action_catalog.values()
                           if weapon and action.owner_id == filed.entity_id
                           and (action.source_definition_id == weapon or action.parameters.get("requires_held_weapon") == weapon)}
        readiness = {action: ready for action, ready in filed.equipment_readiness.items() if action not in retired_actions}
        if readiness != filed.equipment_readiness:
            filed.equipment_readiness = readiness
            engine._append_event("EQUIPMENT_READINESS_SET", source, actor_id=filed.entity_id,
                                 target_ids=(filed.entity_id,), payload={"readiness": readiness})
    # A physical object's map representation derives from the same retirement,
    # whether it was broken in hand, thrown, or damaged on the map.
    obj = engine.state.objects.get(identity(owner.entity_id, key)) if key else None
    if obj is not None and not obj.destroyed:
        engine._update_object(obj.model_copy(update={"destroyed": True, "current_hp": 0}),
                              source, actor_id or owner.entity_id)
    for creature in engine.state.actors.values():
        carry.refresh(engine, creature, source)
    return True


@hook("object_state_record")
def object_record(obj: Any, engine: Any) -> Any:
    """The native object upsert reads retirement before recording any projection.

    A stale carried/thrown representation cannot recreate a destroyed inventory
    identity. Noninventory map objects and nonretired items are unchanged.
    """
    owner_id, sep, key = obj.object_id.partition("|")
    owner = engine.state.actors.get(owner_id)
    if sep and is_destroyed(owner, key=key):
        return obj.model_copy(update={"destroyed": True, "current_hp": 0})
    return obj


@hook("state_event")
def destroyed_object(engine: Any, event: Any) -> None:
    """All native OBJECT_UPDATED writers retire real inventory identities.

    Constructs/scenery have no matching inventory identity and remain inert.
    This native checkpoint also sees nested events and Gate2-only fights.
    """
    if event.event_type != "OBJECT_UPDATED":
        return
    obj = event.payload.get("object") or {}
    if not obj.get("destroyed"):
        return
    owner_id, sep, key = str(obj.get("object_id") or "").partition("|")
    owner = engine.state.actors.get(owner_id)
    if sep and owner is not None:
        destroy(engine, owner, key=key, source=event.source_definition_id, actor_id=event.actor_id)


def _destroyed_delivery(engine: Any, actor: Any, action: Any) -> bool:
    if action is None or not any(c.condition_id == DESTROYED for owner in engine.state.actors.values()
                                 for c in owner.conditions.values()):
        return False
    from ..weapon_delivery import weapon_identity
    typed = (action.parameters or {}).get("typed") or {}
    weapon = weapon_identity(engine, action.source_definition_id, typed, action.parameters, owner_id=actor.entity_id)
    return bool(weapon and weapon_destroyed(engine, actor, weapon))


@hook("candidate_allowed")
def destroyed_delivery(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Retired weapons cannot deliver attacks/techniques, including old catalogs."""
    return False if _destroyed_delivery(engine, actor, action) else None


@hook("opportunity_allowed")
def destroyed_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    for action in engine.action_catalog.values():
        if action.owner_id == reactor.entity_id and ((action.parameters or {}).get("typed") or {}).get("opportunity_of"):
            if _destroyed_delivery(engine, reactor, action):
                return False
    return None


@hook("journey_view")
def journey_inventory(state: dict[str, Any], viewer_id: str | None) -> dict[str, Any] | None:
    """Project carried inventory from the durable encounter result, without writes."""
    for actor in state["actors"].values():
        if actor.get("encounter_snapshot"):
            current = journey_carrying(actor)
            if current is not actor["bundle"].get("carrying"):
                actor["bundle"]["carrying"] = current
    return state
