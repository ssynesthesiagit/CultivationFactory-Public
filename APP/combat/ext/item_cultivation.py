"""Named cultivated item properties, shared by Empty Palm and treasure readers.

Empty Palm discovers inventory refinements, inscriptions/enhancements and live
item-bound effects here. Native weapon, thrown_equipment and treasure_armor readers consult the
same persisted per-item suppression receipt. Physical attacks, shield protection,
possession, original durations and costs are never suppressed by that receipt.
The compiler's item_property tag identifies all effects of ONE inscription.
"""
from copy import deepcopy

from . import hook

HOLLOWED_ITEM = "condition:typed.hollowed_item"


@hook("compile_bundle")
def seal_properties(bundle, info):
    records = [("treasure_weapon", info["kit"].get("resolved_treasure_weapon")),
               ("treasure_armor", info["kit"].get("resolved_treasure_armor"))]
    records += [(f"given.{i}", r.get("record")) for i, r in enumerate(info["owner_items"])]
    result = None
    for key, record in records:
        if not isinstance(record, dict):
            continue
        props = []
        refinement = int(record.get("refinement_bonus") or 0)
        if refinement:
            benefit = "AC" if (record.get("chassis") or {}).get("armor_category") else "attack and damage rolls"
            props.append({"key": "refinement", "name": f"Refinement (+{refinement} to {benefit})", "bonus": refinement})
        for row in [*(record.get("enchantments") or []), *(record.get("enhancements") or [])]:
            props.append({"key": row.get("enchantment_id") or row.get("enhancement_id") or row["name"], "name": row["name"]})
        if not props:
            continue
        result = result or deepcopy(bundle)
        for item in result["carrying"]["items"]:
            if item["key"] == key:
                item["cultivated_properties"] = props
    return result


def suppressed(engine, owner_id, item_key, property_id):
    """Pure per-physical-item query for Empty Palm, weapons and treasure armor.

    Receipts live on the original inventory owner so transfer cannot reset them.
    Without the applied condition every reader is inert.
    """
    owner = engine.state.actors.get(owner_id)
    return owner is not None and any(
        c.condition_id == HOLLOWED_ITEM
        and (c.data or {}).get("item_key") == item_key
        and (c.data or {}).get("property_id") == property_id
        for c in owner.conditions.values())


def weapon_item(engine, actor, action):
    """Original inventory identity, including a borrowed weapon's attack variants."""
    from ..weapon_delivery import physical_weapon_id

    physical = ((action.parameters or {}).get("requires_held_weapon") or
                physical_weapon_id(action.source_definition_id, action.parameters))
    original = engine.action_catalog.get(physical) or action
    owner = original.owner_id or actor.entity_id
    from ..carry import carrying_of, item_of

    item = item_of(carrying_of(engine, owner), weapon_action=physical)
    return owner, item["key"] if item is not None else None


def carried_properties(engine, target):
    """All actually carried eligible items and their independently active properties.

    Live effects name the inventory item through item_key, implement_id/item or
    the native Mandate weapon action identity. Sibling numeric modifiers from
    that same activation belong to the same named property.
    """
    from ..carry import carrying_of, item_carrier
    from ..typed_executor import is_active_typed_condition
    from . import end_effect

    out = []
    for owner in engine.state.actors.values():
        for item in (carrying_of(engine, owner.entity_id) or {}).get("items", []):
            key = item["key"]
            if item.get("kind") == "armor" and not item.get("shield"):
                continue  # body armor is not one of Hollow the Weapon's item kinds
            if item_carrier(engine, owner, key) != target.entity_id:
                continue
            props = [dict(p) for p in item.get("cultivated_properties", [])
                     if not suppressed(engine, owner.entity_id, key, p["key"])]
            for holder in {owner.entity_id: owner, target.entity_id: target}.values():
                for iid, condition in holder.conditions.items():
                    if not is_active_typed_condition(condition):
                        continue
                    data = condition.data or {}
                    if any(field in data for field in ("held_by", "object_location", "dropped_at")):
                        continue  # possession/equipment state is not an active cultivated property
                    bound = (data.get("item_key") == key or
                             data.get("weapon") == item.get("weapon_action") and bool(item.get("weapon_action")) or
                             data.get("implement_id") == item.get("item_id") or
                             data.get("item") == item.get("item_id"))
                    if not bound or condition.condition_id in (HOLLOWED_ITEM, "condition:typed.dropped_item"):
                        continue
                    if condition.condition_id.startswith(("condition:typed.equipment_", "condition:typed.mark.")):
                        continue
                    members = [("condition", iid)]
                    members += [("modifier", mid) for mid, mod in holder.modifiers.items()
                                if mod.source_definition_id == condition.source_definition_id
                                and mod.source_actor_id == condition.source_actor_id
                                and not mod.target_field.startswith("suppressed:")]
                    props.append({"key": iid, "name": data.get("name") or data.get("label") or
                                  end_effect.describe(engine, "condition", condition),
                                  "holder": holder.entity_id, "members": members})
            if item.get("weapon_action") or item.get("shield") or props:
                out.append({"key": f"{owner.entity_id}|{key}", "item_key": key,
                            "owner": owner.entity_id, "name": item["name"], "properties": props})
    return out


@hook("effect_allowed")
def property_effect_allowed(ctx, row):
    key = row.get("item_property")
    if not key:
        return None
    owner, item = weapon_item(ctx.engine, ctx.actor, ctx.action)
    return False if item and suppressed(ctx.engine, owner, item, key) else None


@hook("attack_bonus")
def refinement_attack(ctx, actor):
    return refinement_penalty(ctx)


@hook("attack_damage_bonus")
def refinement_damage(ctx, target, effect):
    return refinement_penalty(ctx)


def refinement_penalty(ctx):
    owner, key = weapon_item(ctx.engine, ctx.actor, ctx.action)
    if not key or not suppressed(ctx.engine, owner, key, "refinement"):
        return None
    from ..carry import carrying_of, item_of

    item = item_of(carrying_of(ctx.engine, owner), key=key) or {}
    return -sum(int(p.get("bonus") or 0) for p in item.get("cultivated_properties", [])
                if p["key"] == "refinement")


@hook("ac")
def refinement_ac(engine, target):
    from ..carry import carrying_of

    return -sum(int(p.get("bonus") or 0)
                for item in (carrying_of(engine, target.entity_id) or {}).get("items", [])
                if (item.get("worn") or item.get("shield"))
                for p in item.get("cultivated_properties", [])
                if p["key"] == "refinement" and suppressed(engine, target.entity_id, item["key"], p["key"])) or None
