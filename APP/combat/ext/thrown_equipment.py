"""Thrown copies leave the hand and use the table's existing dropped-item state.

Only newly compiled Thrown equipment opts in. Ordinary melee attacks, ammunition
weapons and legacy bundles are inert. Stock becomes individual copies so Drop,
Pick up, taking another actor's weapon, and carry weight share one identity.
Returning Inscription is automatic under its printed free-hand/area restrictions;
Moon-Cleaver Return offers its owner return or lodge after the action's targets.
owning an optional recall talent alone never grants unconditional return.

Shared release/return_inscription helpers serve the normal attack hooks and
barrage_second_pass automatic misses: release the physical held copy, then
apply only its recorded Returning Inscription and native free-hand restrictions.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

from . import hook
from .weapon_hits import weapon_identity, is_weapon_hit
from .. import carry

RETURNING_ACTIONS = {"TAL_AXES_MOON_CLEAVER_RETURN"}
MOON_CHOICE = "choice:thrown_equipment.moon_return"


@hook("compile_actions")
def moon_choice_owner(info):
    """Expose this owned technique's off-turn decisions through the public seam."""
    if RETURNING_ACTIONS.intersection(info["owned_ids"]):
        info["passives"].append({"feature_id": "TAL_AXES_MOON_CLEAVER_RETURN", "choice_owner": True})


@hook("choice_options")
def moon_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    if choice_id != MOON_CHOICE or not context.get("moon_return"):
        return None
    return {"option_ids": ["return", "lodge"], "minimum_selections": 1,
            "maximum_selections": 1, "allow_decline": False, "automatic_use": True,
            "preferred_option_ids": ["return"]}


@hook("decision_text")
def moon_choice_text(engine, context, printed_rules):
    if context.get("reaction_source_id") != MOON_CHOICE:
        return None
    return {"feature_id": "TAL_AXES_MOON_CLEAVER_RETURN",
            "cost": "No action, Reaction, or additional resource cost",
            "summary": "After Moon-Cleaver Return resolves, return the axe to your hand or leave it lodged where it landed until someone picks it up.",
            "limits": "Total Cover or a stronger effect can stop the return. A lodged axe cannot be used until recovered."}


def moon_returns(ctx):
    """Manual owners choose; AI deterministically retrieves its usable weapon."""
    from .choice_prompt import action_context

    if ctx.intent is None or not hasattr(ctx.engine, "_gate4_reaction_cache"):
        return True
    prefix = "TYPED:" if ctx.actor.entity_id in getattr(ctx.engine, "typed_ask_reactors", ()) else "CHOICE:"
    targets = ", ".join(target.display_name for target in ctx.targets)
    context = {**action_context(ctx.engine, ctx.actor, ctx.source, ctx.actor),
               "moon_return": True, "actor_id": ctx.actor.entity_id, "target_id": ctx.actor.entity_id,
               "ability": "Moon-Cleaver Return",
               "labels": {"return": "Return the axe to your hand (no action or extra cost)",
                          "lodge": "Leave the axe where it landed until it is picked up"},
               "prompt": f"{ctx.actor.display_name} used Moon-Cleaver Return against {targets}: return the axe to your hand without an action or extra cost, or leave it lodged where it landed?"}
    decision = ctx.engine._reaction_decision(ctx.intent,
        f"{prefix}Moon-Cleaver Return@{ctx.engine.state.event_sequence}:{ctx.actor.entity_id}",
        ctx.actor.entity_id, MOON_CHOICE, context=context)
    return decision is None or "return" in decision.option_ids


def returning_action(ctx):
    return str(ctx.typed.get("option_of") or ctx.typed.get("source") or "") in RETURNING_ACTIONS


@hook("compile_equipment_items")
def copies(items):
    from factory_authoring.starting_kits import _authorities

    catalog = _authorities()[1]
    out, seen, changed = [], {}, False
    for item in items:
        source = item.get("item_id")
        properties = str(catalog.get(source, {}).get("properties") or "")
        if not re.search(r"\bThrown\b", properties, re.I):
            out.append(item)
            continue
        changed = True
        if item.get("combat_item_key"):
            out.append(item)
            number = 1 if item["combat_item_key"] == source else int(item["combat_item_key"].rsplit(".", 1)[-1])
            seen[source] = max(seen.get(source, 0), number)
            continue
        for _ in range(max(0, int(item.get("quantity", 1)))):
            seen[source] = seen.get(source, 0) + 1
            number = seen[source]
            # These are compile-time keys; the sheet and canonical kit stay intact.
            out.append({**item, "quantity": 1,
                        "combat_item_key": source if number == 1 else f"{source}.{number}",
                        "combat_weapon_key": "" if number == 1 else f"copy{number}",
                        **({"combat_name": f"{catalog[source]['name']} (copy {number})"} if number > 1 else {})})
    return out if changed else None


@hook("compile_weapon_traits")
def traits(info):
    weapon = info["weapon"]
    if not re.search(r"\bThrown\b", str(weapon.get("properties") or ""), re.I):
        return None
    returning = any(row.get("enchantment_id") == "tianxia.treasure.enchantment.returning_inscription"
                    for row in weapon.get("enchantments") or [])
    return {"thrown_equipment": {"returning_inscription": returning}, "inventory_key": weapon.get("inventory_key")}


def equipment(ctx):
    """Return physical owner, base id, traits and possession condition, or None.

    A returning action keeps its launched copy across targets; a borrowed copy's
    condition remains on its physical owner. No additional weapon is invented.
    """
    base = weapon_identity(ctx)
    flying = (getattr(ctx, "damage_cache", {}) or {}).get("thrown_copy")
    if returning_action(ctx) and flying and flying[3] == base:
        owner = ctx.engine.state.actors[flying[0]]
        for iid, condition in owner.conditions.items():
            if condition.data.get("disables_action") == flying[1] and condition.data.get("dropped_at"):
                return owner, flying[1], flying[2], iid
    action = ctx.engine.action_catalog.get(base)
    if action is None:
        return None
    contract = (action.parameters.get("typed") or {}).get("thrown_equipment")
    if contract is None:
        return None
    required = action.parameters.get("requires_held_weapon")
    if required:
        for owner in ctx.engine.state.actors.values():
            for iid, condition in owner.conditions.items():
                if condition.data.get("disables_action") == required and condition.data.get("held_by") == ctx.actor.entity_id:
                    return owner, required, contract, iid
        return None
    return ctx.actor, base, contract, None


@hook("attack_allowed")
def held(ctx, target, effect):
    if not is_weapon_hit(ctx, effect):
        return None
    action = ctx.engine.action_catalog.get(weapon_identity(ctx))
    if action is None or "thrown_equipment" not in (action.parameters.get("typed") or {}):
        return None
    item = equipment(ctx)
    if item is None:
        return False
    owner, base, _, held_instance = item
    if held_instance is None and any(c.data.get("disables_action") == base for c in owner.conditions.values()):
        return False
    return None


@hook("candidate_allowed")
def offered(engine, actor, candidate, action):
    if action is None:
        return None
    typed = action.parameters.get("typed") or {}
    if not typed.get("weapon"):
        return None
    ctx = SimpleNamespace(engine=engine, actor=actor, action=action, typed=typed)
    for effect in typed.get("effects") or []:
        if effect.get("type") == "attack" and held(ctx, None, effect) is False:
            return False
    return None


def remove(ctx, owner, iid):
    condition = owner.conditions.pop(iid)
    ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id,
        target_ids=(owner.entity_id,), payload={"condition_id": condition.condition_id, "instance_id": iid})


def reweigh(ctx):
    for actor in ctx.engine.state.actors.values():
        carry.refresh(ctx.engine, actor, ctx.source)


@hook("event", nested=True)
def release_on_roll(engine, event_type, kwargs):
    if event_type != "ATTACK_ROLLED":
        return
    from .attack_scope import current

    frame = current(engine)
    if frame is None or frame.get("thrown_released"):
        return
    if (kwargs.get("actor_id") != frame["actor_id"]
            or tuple(kwargs.get("target_ids") or ()) != (frame["target_id"],)
            or str((kwargs.get("payload") or {}).get("reason") or "").rsplit(":", 1)[0] != "ATTACK:" + frame["source"]):
        return
    ctx, effect = frame["context"], frame["effect"]
    if not is_weapon_hit(ctx, effect) or int(ctx.typed.get("range_ft") or 0) <= 5 or equipment(ctx) is None:
        return
    frame["thrown_released"] = True  # a reroll inside this scope never throws another copy
    release(ctx, engine.state.actors[frame["target_id"]], effect)


def release(ctx, target, effect):
    if not is_weapon_hit(ctx, effect) or int(ctx.typed.get("range_ft") or 0) <= 5:
        return
    item = equipment(ctx)
    if item is None:
        return
    owner, base, contract, iid = item
    carried = carry.item_of(carry.carrying_of(ctx.engine, owner.entity_id), weapon_action=base)
    if carried is None:
        return  # no physical inventory entry: no invented equipment
    if iid is not None:
        remove(ctx, owner, iid)
    ctx.engine._apply_condition(owner, carry.DROPPED, ctx.source, ctx.actor.entity_id,
        expires_on="UNTIL_REMOVED", data={"item_key": carried["key"], "item_name": carried["name"],
            "disables_action": base, "dropped_at": target.position.model_dump(mode="json")})
    # The throw leaves the hand: a stowed grip frees it for the next weapon (SHEETHANDS1).
    # Only an existing grip is touched, so legacy bundles keep their policy.
    from .equipment_hands import set_weapon_readiness
    from .hand_occupancy import supports_grips
    if supports_grips(ctx.engine, owner) and owner.equipment_readiness.get(base, 1):
        set_weapon_readiness(ctx.engine, owner, base, False, source=ctx.source,
                             source_actor_id=ctx.actor.entity_id)
    ctx.damage_cache["thrown_copy"] = (owner.entity_id, base, contract, weapon_identity(ctx))
    reweigh(ctx)
    if not contract["returning_inscription"] and not returning_action(ctx):
        ctx.rider(f"{ctx.action.display_name}: the weapon lands at {target.display_name}'s space; pick it up before using it again.")


@hook("attack_resolved")
def return_inscription(ctx, target, hit, effect):
    thrown = ctx.damage_cache.get("thrown_copy")
    if thrown is not None and returning_action(ctx) and not thrown[2]["returning_inscription"]:
        return  # one returning projectile traverses the action's targets before returning
    ctx.damage_cache.pop("thrown_copy", None)
    if thrown is None or not thrown[2]["returning_inscription"]:
        return
    return_copy(ctx, thrown, "Returning Inscription", magical=True)


@hook("technique_used")
def return_after_action(ctx):
    if not returning_action(ctx):
        return
    thrown = ctx.damage_cache.pop("thrown_copy", None)
    if thrown is not None:
        if moon_returns(ctx):
            return_copy(ctx, thrown, "Moon-Cleaver Return", clear_path=True)
        else:
            ctx.rider(f"Moon-Cleaver Return: {ctx.actor.display_name} leaves the axe lodged where it landed; pick it up before using it again.")


def return_copy(ctx, thrown, label, *, magical=False, clear_path=False):
    owner = ctx.engine.state.actors[thrown[0]]
    iid = next((iid for iid, c in owner.conditions.items()
                if c.data.get("disables_action") == thrown[1] and c.data.get("dropped_at")), None)
    if iid is None:
        return  # already taken or recovered during the attack
    # The throw stows its grip in release(); a returning weapon restores it below.
    # Explicit area prohibitions deny the item's magical return.
    spot = owner.conditions[iid].data["dropped_at"]
    if clear_path:
        from ..gate2_runtime_models import Position

        if not ctx.engine.grid.line_of_sight_between_cell_sets((Position(**spot),), ctx.engine._actor_cells(ctx.actor)):
            ctx.rider(f"{label} is blocked by Total Cover: the weapon stays where it landed; pick it up before using it again.")
            return
    for zone in ctx.engine.state.zones.values():
        rule = zone.trigger_profile.get("rule") or {}
        inside = any(cell.x == spot["x"] and cell.y == spot["y"] for cell in zone.affected_cells)
        if magical and zone.active and (rule.get("no_teleport") or rule.get("no_extradimensional_movement")) and inside:
            ctx.rider("Returning Inscription is blocked: the weapon stays where it landed; pick it up before using it again.")
            return
    remove(ctx, owner, iid)
    # A returning weapon comes back to its grip; a thrown one was stowed above.
    from .equipment_hands import set_weapon_readiness
    if not owner.equipment_readiness.get(thrown[1], 1):
        set_weapon_readiness(ctx.engine, owner, thrown[1], True, source=ctx.source,
                             source_actor_id=ctx.actor.entity_id)
    if owner.entity_id != ctx.actor.entity_id:
        ctx.engine._apply_condition(owner, carry.DROPPED, ctx.source, ctx.actor.entity_id,
            expires_on="UNTIL_REMOVED", data={"disables_action": thrown[1], "held_by": ctx.actor.entity_id})
    reweigh(ctx)
    ctx.rider(f"{label}: the weapon returns to {ctx.actor.display_name}'s hand without an action.")
