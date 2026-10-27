"""Weapon eligibility through the public shared hand_occupancy model.

Menu filtering and actual execution share a query, including delivered talents,
opportunity copies and pre-metadata saved weapon actions. The shared
set_weapon_readiness mutation serves Draw/Stow and transfer_object relocation.
Natural/unarmed
attacks and actions without a physical weapon remain inert.
"""
from __future__ import annotations

from typing import Any

from . import hook, effect
from .hand_occupancy import weapon_allowed
from ..hook_queries import actor_action


@hook("candidate_allowed", query_key=actor_action)
def require_free_hands(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None:
        grip = action.parameters.get("equipment_grip")
        if grip:
            from .hand_occupancy import weapon_grips, free_hands
            from .weapon_hits import available_weapons
            weapon = grip["weapon"]
            if weapon not in available_weapons(engine, actor, include_busy=not grip["held"]):
                return False
            ready = weapon in weapon_grips(engine, actor)
            return (not ready and len(free_hands(engine, actor)) >= grip["hands"]) if grip["held"] else ready
        typed = action.parameters.get("typed") or {}
        replaced = (typed.get('replaces_attack') or {}).get('source_definition_id')
        if replaced:
            parent = engine.action_catalog.get(replaced)
            if parent is not None and weapon_allowed(engine, actor, parent) is False:
                return False
        if typed.get("unarmed_option"):
            return None  # the option itself is unarmed; attack_allowed checks any weapon follow-ups
        for row in typed.get("effects") or []:
            if row.get("type") in {"pickup_item", "recover_weapon", "take_weapon"}:
                from .hand_occupancy import free_hands, resting_hands, supports_grips
                if not supports_grips(engine, actor):
                    return None
                weapon = row.get("weapon")
                if row["type"] == "take_weapon":
                    # Match the executor's deterministic first nearby item.
                    nearby = engine._dropped_weapons_near(actor)
                    if nearby:
                        owner, iid = nearby[0]
                        weapon = owner.conditions[iid].data.get("disables_action")
                if row["type"] == "pickup_item":
                    from .. import carry
                    item = carry.item_of(carry.carrying_of(engine, actor.entity_id), key=row.get("item")) or {}
                    weapon = item.get("weapon_action")
                base = engine.action_catalog.get(weapon)
                return len(free_hands(engine, actor)) >= (resting_hands(base) if base else 1)
    return weapon_allowed(engine, actor, action) if action is not None else None


@hook("candidate_unavailability")
def explain_weapon_hands(engine: Any, actor: Any, candidate: Any, action: Any) -> str | None:
    """Explain the same physical-weapon gate, without relaxing Two-Handed."""
    from .hand_occupancy import (supports_grips, weapon_requirement, weapon_grips,
                                 weapon_capacity, pair_attack)
    from .weapon_hits import available_weapons
    if action is None or not supports_grips(engine, actor):
        return None
    typed = action.parameters.get("typed") or {}
    replaced = (typed.get("replaces_attack") or {}).get("source_definition_id")
    parent = engine.action_catalog.get(replaced) if replaced else None
    checked = parent if parent is not None and weapon_allowed(engine, actor, parent) is False else action
    if weapon_allowed(engine, actor, checked) is not False or pair_attack(checked):
        return None  # A paired follow-up needs its pair, not a spare attacking hand.
    requirement = weapon_requirement(engine, checked)
    if requirement is None:
        return None
    identity, count = requirement
    base = engine.action_catalog.get(identity)
    name = base.display_name.removesuffix(" attack") if base else "this weapon"
    if identity not in available_weapons(engine, actor):
        return f"Cannot attack with {name}: it is not currently usable or in your possession."
    ready = weapon_grips(engine, actor)
    if identity not in ready:
        return f"Draw {name} before attacking with it (no Action)."
    capacity = weapon_capacity(engine, actor, identity)
    if capacity < count:
        others = [engine.action_catalog[key].display_name.removesuffix(" attack")
                  for key in ready if key != identity]
        remedy = (f"Stow or drop {', '.join(others)} to free a hand."
                  if others else "Free a hand by releasing a hold or putting away other held equipment.")
        return (f"{name} needs {count} hands to attack; only {capacity} "
                f"{'is' if capacity == 1 else 'are'} available. {remedy}")
    return "Your held equipment leaves no legal grip for this attack."


def attack_equipment_action(ctx: Any) -> Any:
    """Effective weapon metadata for the attack gate and versatile-die query.

    This is a read-only projection, used only inside attack hooks.
    """
    # The parent Grapple/Shove is unarmed; its Extra Attack follow-ups use
    # their own physical weapon and need the hands left after that maneuver.
    typed = {**ctx.typed}
    typed.pop('unarmed_option', None)
    return ctx.action.model_copy(update={'parameters': {**ctx.action.parameters, 'typed': typed}})


@hook("attack_allowed")
def require_attack_hands(ctx: Any, target: Any, effect: dict[str, Any]) -> bool | None:
    from .weapon_hits import is_weapon_hit
    if not is_weapon_hit(ctx, effect):
        return None
    # A Grapple/Shove action can retain weapon Extra Attacks. Check each actual
    # packet, even though its opening unarmed option needs no weapon grip.
    return weapon_allowed(ctx.engine, ctx.actor, attack_equipment_action(ctx), effect=effect)


@hook("attack_damage")
def versatile_grip_die(ctx: Any, dice: Any) -> Any:
    """The die a Versatile attack uses with the hands actually free, in either direction.

    Uses hand_occupancy.versatile_die_sides, the shared public model, so the runtime answer always agrees
    with what the compiler chose for this character. Only the grip-dependent die size changes: a technique
    or ability that printed ten weapon dice still rolls ten, only against a different-sized die. A
    technique that printed its own die is not weapon damage and keeps it (hand_occupancy.weapon_damage_dice).
    """
    from .hand_occupancy import versatile_die_sides, weapon_damage_dice
    if dice is None:
        return None
    if not weapon_damage_dice(ctx):
        return None
    sides = versatile_die_sides(ctx.engine, ctx.actor, attack_equipment_action(ctx))
    return None if sides is None or sides == int(dice.sides) else dice.model_copy(update={"sides": sides})


@hook("compile_actions")
def grip_actions(info: dict[str, Any]) -> list[Any]:
    """Explicit equipment choices; the existing table spends no actions on drawing/stowing.

    One Draw/Stow pair per physical weapon: its alternative attack modes are the same object,
    so they are not separate gear choices.
    """
    import hashlib
    from .hand_occupancy import resting_hands
    from .weapon_hits import physical_weapon_id
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    out = []
    for action in info["actions"]:
        typed = action.parameters.get("typed") or {}
        if (".weapon." not in action.source_definition_id or not typed.get("weapon")
                or physical_weapon_id(action.source_definition_id, action.parameters) != action.source_definition_id):
            continue
        hands = resting_hands(action)
        name = action.display_name.removesuffix(" attack")
        for held, verb in ((0, "Stow"), (1, "Draw")):
            grip = {"weapon": action.source_definition_id, "held": held, "hands": hands}
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.equipment_grip."
                                     + hashlib.sha256(action.source_definition_id.encode()).hexdigest()[:10] + "." + verb.lower(),
                display_name=f"{verb} {name} ({'uses' if held else 'frees'} {hands} hand{'s' if hands != 1 else ''}; no Action)",
                owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"equipment_grip": grip, "expected_damage": 0,
                            "description": f"{verb} {name}: {'ready it for weapon attacks' if held else 'put it away; you cannot attack with it until you draw it again'}. "
                                           f"{'Uses' if held else 'Frees'} {hands} hand{'s' if hands != 1 else ''} until you {'stow' if held else 'draw'} it. Costs no Action or resource.",
                            "typed": {"numbers": info["numbers"], "effects": [{"type": "equipment_grip", **grip}]}}))
    return out


@hook("ai_candidate_allowed")
def ai_grip_choice(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Permit automatic gear changes only toward a usable attack; never Draw/Stow loops."""
    grip = action.parameters.get("equipment_grip") if action is not None else None
    if not grip:
        return None
    from .hand_occupancy import weapon_grips, weapon_requirement, weapon_capacity
    ready = weapon_grips(engine, actor)
    if any(weapon_allowed(engine, actor, engine.action_catalog[weapon]) for weapon in ready):
        return False
    if not grip["held"]:
        return True
    base = engine.action_catalog[grip["weapon"]]
    requirement = weapon_requirement(engine, base)
    properties = (base.parameters["typed"]["weapon"].get("properties") or "").lower()
    count = 1 if "versatile" in properties and "two-handed" not in properties else requirement[1]
    return not ready and weapon_capacity(engine, actor, grip["weapon"]) >= count


def set_weapon_readiness(engine: Any, actor: Any, weapon: str, held: bool, *,
                         source: str, source_actor_id: str, hand: str | None = None) -> None:
    """Journal readiness for Draw/Stow and same-owner object relocation.

    Possession remains separate: a stored owned weapon is available to Draw,
    while only a drawn weapon contributes its physical grip and can attack.
    Consumers must establish possession before calling this mutation.
    """
    readiness = dict(actor.equipment_readiness)
    readiness[weapon] = hand if held and hand else int(held)
    name = engine.action_catalog[weapon].display_name.removesuffix(" attack")
    verb = "draws" if held else "stows"
    log = None if source == "system:starting_equipment" else actor.display_name + " " + verb + " " + name + "."
    actor.equipment_readiness = readiness
    engine._append_event("EQUIPMENT_READINESS_SET", source, actor_id=actor.entity_id,
                         target_ids=(actor.entity_id,),
                         payload={"readiness": readiness, **({"log": log} if log else {})})


@hook("compile_bundle")
def starting_equipment(bundle: dict[str, Any], info: dict[str, Any]) -> dict[str, Any] | None:
    """Seal a legal, reproducible loadout through the existing compilation hook."""
    from ..gate2_runtime_models import ActionDefinition
    from ..starting_loadout import saved_choices, select_loadout
    carrying = bundle.get("carrying")
    if carrying is None:
        return None
    actions = [ActionDefinition.model_validate(row) for row in bundle["action_catalog"]]
    preferences = saved_choices(info["owner_sheet"], info["kit"], info["owner_items"])
    # The compiler publishes each physical weapon's exact inventory key. Use
    # it rather than guessing action suffixes (given weapons and copies differ).
    weapon_items = {row["row"]["inventory_key"]: row["owner_action"] for row in bundle.get("weapons") or []}
    carrying = {**carrying, "items": [{**item, **({"weapon_action": weapon_items[item["key"]]}
                                               if item["key"] in weapon_items else {})}
                                     for item in carrying.get("items") or []]}
    plan = select_loadout(actions, carrying, bundle["actor_id"], preferences)
    return {**bundle, "carrying": {**carrying, "starting_loadout": {**plan, "preferences": preferences}}}


@hook("match_start", priority=90)
def ready_starting_equipment(engine: Any) -> None:
    """Journal initial grips once at genesis; cold loads restore their saved overrides.

    Inert without a freshly compiled starting_loadout. No selection happens on
    turn start, drop, or recovery, so a stowed spare never draws itself.
    """
    from .. import carry
    from ..starting_loadout import physical_weapons, select_loadout
    from .hand_occupancy import hand_parts
    source = "system:starting_equipment"
    for actor in engine.state.actors.values():
        carrying = carry.carrying_of(engine, actor.entity_id) or {}
        sealed = carrying.get("starting_loadout")
        if (sealed is None or actor.equipment_readiness
                or any(event.source_definition_id == source and event.actor_id == actor.entity_id
                       and event.payload.get("starting_equipment") == 1 for event in engine.events)):
            continue
        actions = list(engine.action_catalog.values())
        plan = select_loadout(actions, carrying, actor.entity_id, sealed.get("preferences") or (),
                              hands=len(hand_parts(engine, actor)))
        readiness = {action.source_definition_id: int(action.source_definition_id in plan["weapons"])
                     for action in physical_weapons(actions, actor.entity_id)}
        actor.equipment_readiness = readiness
        for item in carrying.get("items") or []:
            if not item.get("shield") or item["key"] in plan["held_items"]:
                continue
            if carry.owned_item_location(actor, item["key"]) is None:
                engine._apply_condition(actor, "condition:typed.shield_equipped", source, actor.entity_id,
                                        expires_on="UNTIL_REMOVED",
                                        data={"item_key": item["key"], "item_name": item["name"],
                                              "owner": actor.entity_id, "held_by": actor.entity_id,
                                              "object_location": "carried", "label": item["name"] + " carried"})
        for item in carrying.get("items") or []:
            if item.get("shield") or item["key"] not in plan["held_items"]:
                continue
            from .hand_occupancy import free_hands
            part = next(iter(free_hands(engine, actor)), None)
            if part and carry.owned_item_location(actor, item["key"]) is None:
                engine._apply_condition(actor, "condition:typed.held_object", source, actor.entity_id,
                                        expires_on="UNTIL_REMOVED",
                                        data={"item_key": item["key"], "item_name": item["name"],
                                              "owner": actor.entity_id, "held_by": actor.entity_id,
                                              "object_location": "hand:" + part, "hand": part,
                                              "label": item["name"] + " held"})
        if physical_weapons(actions, actor.entity_id) or carrying.get("items"):
            engine._append_event("EQUIPMENT_READINESS_SET", source, actor_id=actor.entity_id,
                                 target_ids=(actor.entity_id,),
                                 payload={"readiness": readiness, "log": actor.display_name + ": " + plan["note"],
                                          "starting_equipment": 1})


@effect("equipment_grip")
def change_grip(ctx: Any, row: dict[str, Any]) -> None:
    set_weapon_readiness(ctx.engine, ctx.actor, row["weapon"], bool(row["held"]),
                         source=ctx.source, source_actor_id=ctx.actor.entity_id)
