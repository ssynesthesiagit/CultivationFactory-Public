"""Purchased Treasure Consumables as activatable fight actions (lane A2GTRECON, 2026-10-11).

Why this plug-in exists
  Treasure consumables (APP/authority/Tianxia_Treasure_Catalog_Authority_R1.json, "consumables") are bought at
  character creation. Until this lane, ``combat/factory_compiler.py`` read ``resolved_treasure_purchases``
  for ``wondrous`` only (its attunement and carry loops); the ``consumables`` half of the same purchase was
  rendered as text on the character sheet and had no combat representation at all, so every printed combat
  effect of every consumable was a GM-only note. They are also absent from ``typed_mechanics/rules_text.json``,
  so the authority builder skips any ``reviewed_final`` row naming one of them
  (tools/build_typed_mechanics_authority.py: the row is dropped when the id has no printed text). A plug-in on
  documented hooks is therefore the only available route; this file is that route and holds no engine special case.

What is general here
  ``compile_actions`` publishes one action per purchased consumable batch, from the same
  ``resolved_treasure_purchases.consumables`` list the sheet already carries. Nothing keys off a particular
  consumable id: the printed activation, reach and per-batch quantity come from the purchased row, and the
  per-consumable behaviour lives in typed data (``EXTENSIONS`` below) keyed by consumable_id.
  A later lane automates another family by adding rows to that table, not by editing this machinery.
  ``EXTENSIONS`` maps a consumable_id to its printed rows; ids with no row compile no action, which is the
  inert reading for a consumable whose family is not automated yet.

Quantity
  A purchased batch is ``batch_quantity`` uses. Spending is an integer turn flag
  ``_consumable_round_spent.<consumable_id>`` (ammunition's shared ``turn_flags`` accounting, ammunition.py:294), so a
  commit, a cold reload and a mechanical replay all retain the same remaining count. ``candidate_allowed`` hides
  an exhausted action; ``consume`` decrements. The _round_ namespace survives native turn resets. No hidden pool and no per-ability special case is introduced.

Recipient rule
  Every burst here is an unscoped damaging area, so it resolves against hostile creatures only, through the
  engine's own area recipient selection. Nothing widens that to allies.

Fixed printed Difficulty Classes
  ``block_save`` reads the DC from the action's own ``numbers.save_dc`` (typed_executor.py:1595), so each
  printed DC (13, 15, 17, 19) rides on the action that prints it. No core file changes and no global DC.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

SPENT_PREFIX = "_consumable_round_spent."


def _burst(consumable_id: str, *, ability: str, dc: int, dice: str, damage_types: list[str], evidence: str,
           on_fail_extra: list[dict[str, Any]] | None = None, radius_ft: int = 10) -> dict[str, Any]:
    """One printed thrown burst: a sphere, one saving throw, full damage on a failure and half on a success.

    ``dice`` is the printed expression ("4d6"); it becomes the row's ``dice`` dict because
    ``typed_amounts.effect_dice`` reads that field, not a formula string.
    """
    count, _, sides = dice.partition("d")
    return {
        "consumable_id": consumable_id,
        # Unscoped damaging area: hostiles in the area only, never the thrower (owner ruling). scoped_area
        # seals an already-scoped area as-is (area_recipients.py:64) and strips the policy keys only when
        # harmful_recipient_override is present, so these three keys are what the printed scope rides on.
        "area": {"shape": "sphere", "size_ft": radius_ft, "centered_on_self": False,
                 "recipients": "hostile", "harmful_recipients": "hostile", "exclude_self": True},
        "save": {"ability": ability, "dc": dc,
                 "on_fail": [*[{"type": "damage", "applies_to": "target",
                              "dice": {"count": int(count), "sides": int(sides or 0)},
                              "damage_types": [kind], "flat": 0, "duration": "instant", "evidence": evidence}
                             for kind in damage_types], *(on_fail_extra or [])],
                 "on_success": [{"type": "half_damage", "evidence": "half as much damage on a successful save"}]},
    }


# Combat Pellets: "Action; throw to N feet", the group's highest combat impact. Each printed batch is one
# detonation at a chosen point; the reach and activation below are the printed ones.
PELLET_BURSTS: dict[str, dict[str, Any]] = {
    "tianxia.treasure.consumable.011.dragon_furnace_explosive_pellet": {
        **_burst("tianxia.treasure.consumable.011.dragon_furnace_explosive_pellet", ability="dex", dc=13,
                 dice="4d6", damage_types=["fire"],
                 evidence="Creatures in the area make a DC 13 Dexterity saving throw, taking 4d6 fire damage on a "
                          "failed save or half as much on a successful save."),
        "range_ft": 60, "economy": "action", "object_effect": "ignite", "expected_damage": 14,
        "button": "Throw the pellet to a point within 60 feet; enemies in a 10-foot radius make a DC 13 Dexterity save and take 4d6 fire damage (half on a success)."},
    "tianxia.treasure.consumable.014.thunderclap_pellet": {
        **_burst("tianxia.treasure.consumable.014.thunderclap_pellet", ability="con", dc=13, dice="3d8",
                 damage_types=["thunder"],
                 evidence="Creatures in the area make a DC 13 Constitution saving throw. On a failed save, a "
                          "creature takes 3d8 thunder damage, is Deafened until the end of its next turn, and "
                          "cannot take Reactions until then.",
                 on_fail_extra=[{"type": "condition", "applies_to": "target", "condition": "deafened",
                                 "duration": "until_end_of_next_turn",
                                 "evidence": "is Deafened until the end of its next turn", "flat": 0,
                                 "damage_types": [], "ability": "none", "distance_ft": 0, "on": ""},
                                {"type": "reaction_denied", "applies_to": "target",
                                 "until": "end_of_next_turn",
                                 "evidence": "cannot take Reactions until then", "flat": 0, "damage_types": [],
                                 "ability": "none", "condition": "none", "distance_ft": 0, "on": "",
                                 "duration": "until_end_of_next_turn"}]),
        "range_ft": 60, "economy": "action", "expected_damage": 13,
        "button": "Throw the pellet to a point within 60 feet; enemies in a 10-foot radius make a DC 13 Constitution save, taking 3d8 thunder damage (half on a success), and on a failure are Deafened and cannot take Reactions until the end of their next turn."},
    "tianxia.treasure.consumable.019.calamity_star_pellet": {
        **_burst("tianxia.treasure.consumable.019.calamity_star_pellet", ability="dex", dc=17, dice="6d8",
                 damage_types=["lightning", "force"], radius_ft=20,
                 evidence="Creatures in the area make a DC 17 Dexterity saving throw. On a failed save, a creature "
                          "takes 6d8 lightning damage and 6d8 force damage and falls Prone.",
                 on_fail_extra=[{"type": "condition", "applies_to": "target", "condition": "prone",
                                 "duration": "instant", "evidence": "falls Prone", "flat": 0, "damage_types": [],
                                 "ability": "none", "distance_ft": 0, "on": ""}]),
        "range_ft": 120, "economy": "action", "object_effect": "maximum_force", "expected_damage": 54,
        "button": "Throw the pellet to a point within 120 feet; enemies in a 20-foot radius make a DC 17 Dexterity save, taking 6d8 lightning plus 6d8 force damage and falling Prone on a failure (half damage and no new Prone condition on a success)."},
}

RECOVERY = "tianxia.treasure.consumable.001.nine_breath_recovery_pill"
FIREBOLT = "tianxia.treasure.consumable.023.firebolt_talisman"
FROST = "tianxia.treasure.consumable.012.frost_bloom_pellet"
SWIFT = "tianxia.treasure.consumable.021.swift_step_talisman"
CORROSIVE = "tianxia.treasure.consumable.015.bone_melting_corrosive_pellet"
EXTENSIONS: dict[str, dict[str, Any]] = {**PELLET_BURSTS,
    FROST: {**_burst("tianxia.treasure.consumable.012.frost_bloom_pellet", ability="con", dc=13,
                    dice="3d6", damage_types=["cold"], evidence="Creatures in the area make a DC 13 Constitution save; take 3d6 cold damage, or half on a success."),
            "range_ft": 60, "economy": "action", "expected_damage": 10, "effects": [{"type": "zone"}],
            "zone_spec": {"name": "Frost-Bloom", "shape": "sphere", "size_ft": 10,
                          "duration": {"kind": "minutes", "amount": 1}, "difficult": "all",
                          "triggers": [{"id": "treasure:frost_bloom", "name": "Frost-Bloom cold", "on": ["enter", "start"], "who": "hostile",
                                        "effects": [{"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 6}, "damage_types": ["cold"]}]}]},
            "button": "Throw one pellet to a point within 60 feet. Enemies in a 10-foot radius make a DC 13 Constitution save against 3d6 cold damage (half on a success). For 1 minute the frost is Difficult Terrain and deals 1d6 cold damage to enemies entering it or starting their turn there, once per turn."},
    SWIFT: {"effects": [{"type": "treasure_free_step", "distance_ft": 20}],
            "economy": "bonus_action", "target_kind": "SELF", "range_ft": 0,
            "button": "Spend one talisman to move up to 20 feet without provoking Opportunity Attacks. Choose a reachable space."},
    CORROSIVE: {"effects": [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
                             "on_hit": [{"type": "damage", "dice": {"count": 4, "sides": 6}, "damage_types": ["acid"]}],
                             "on_miss": []}], "attack_bonus": 5, "economy": "action", "target_kind": "ANY_CREATURE", "range_ft": 60,
                "expected_damage": 14,
                "button": "Throw one pellet at a creature, unattended object, or Formation component within 60 feet (+5 to hit). A creature takes 4d6 acid damage on a hit; an object takes 24 acid damage."},
    RECOVERY: {"effects": [{"type": "healing", "applies_to": "self", "dice": {"count": 2, "sides": 8}, "flat": 2}],
               "economy": "bonus_action", "target_kind": "SELF", "range_ft": 0,
               "button": "Take one pill as a Bonus Action to regain 2d8 + 2 Hit Points."},
    FIREBOLT: {"effects": [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
                           "on_hit": [{"type": "damage", "dice": {"count": 4, "sides": 8}, "damage_types": ["fire"]}],
                           "on_miss": []}], "attack_bonus": 5, "economy": "action", "target_kind": "ANY_CREATURE", "range_ft": 90,
               "expected_damage": 18,
               "button": "Spend one talisman to attack a creature or object within 90 feet (+5 to hit); on a hit, deal 4d8 fire damage."},
}


def _purchased(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Consumable batches this fighter bought at creation, in purchase order (the sheet's own list)."""
    rows: list[dict[str, Any]] = []
    for entry in (info.get("owner_sheet") or {}).get("equipment") or []:
        kit = entry.get("starting_kit") if isinstance(entry, dict) else None
        if not isinstance(kit, dict):
            continue
        for row in (kit.get("resolved_treasure_purchases") or {}).get("consumables") or []:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def batch_quantity(row: dict[str, Any]) -> int:
    """Uses in a purchased batch (printed ``batch_quantity``; a legacy row with none is a single use)."""
    return max(1, int(row.get("batch_quantity") or 1))


def remaining(actor: Any, consumable_id: str, quantity: int) -> int:
    """Uses left of a purchased batch: its printed count less this fight's integer spent flag."""
    spent = int((getattr(actor, "turn_flags", None) or {}).get(SPENT_PREFIX + str(consumable_id), 0))
    return max(0, int(quantity) - spent)


def _batch_sizes(info: dict[str, Any]) -> dict[str, int]:
    """Printed batch size per consumable_id this fighter bought, read from the same sheet rows."""
    sizes: dict[str, int] = {}
    for row in _purchased(info):
        key = str(row.get("consumable_id"))
        sizes[key] = sizes.get(key, 0) + batch_quantity(row)
    return sizes


@hook("compile_actions")
def consumable_actions(info: dict[str, Any]) -> list[Any] | None:
    """Publish owned actions with fixed DC/attack bonus and pooled purchased stock."""
    from copy import deepcopy
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    made = []
    sizes = _batch_sizes(info)
    owned = {str(row.get("consumable_id")): row for row in _purchased(info)}
    for consumable_id, row in owned.items():
        spec = EXTENSIONS.get(consumable_id)
        if not spec:
            continue
        effects = deepcopy(spec.get("effects") or [])
        if "save" in spec:
            effects.insert(0, {"type": "save", **deepcopy(spec["save"])})
        if spec.get("object_effect"):
            effects.append({"type": "treasure_burst_objects", "mode": spec["object_effect"]})
        # Spending belongs to the acting creature, even when the chosen square
        # is empty because a remembered target moved. The executor keeps
        # self-scoped accounting effects on location misses.
        effects.append({"type": "treasure_consumable_spend", "consumable_id": consumable_id,
                        "applies_to": "self"})
        numbers = dict(info["numbers"])
        if "save" in spec:
            numbers["save_dc"] = int(spec["save"]["dc"])
        if "attack_bonus" in spec:
            numbers["attack_bonus"] = int(spec["attack_bonus"])
        typed = {"source": f"consumable.{consumable_id}", "effects": effects, "numbers": numbers,
                 "area": deepcopy(spec.get("area") or {}), "duration": {"kind": "instant"}, "riders": [],
                 # A finishing hit must still charge the stock and resolve the printed object/zone clauses.
                 "hold_victory_until_resolved": True}
        if spec.get("zone_spec"):
            typed["zone_spec"] = deepcopy(spec["zone_spec"])
        params = {"typed": typed, "consumable_batch_quantity": sizes[consumable_id],
                  "description": spec["button"]}
        # Ordinary Gate 2/4 AI scoring consumes this per-target damage estimate;
        # Gate 2 multiplies area estimates by perceived hostile recipients.
        if spec.get("expected_damage") is not None:
            params["expected_damage"] = int(spec["expected_damage"])
        source = f"action:typed.{info['short']}.consumable.{consumable_id}"
        name = str(row.get("name") or "Consumable")
        made.append(ActionDefinition(source_definition_id=source, display_name=name, owner_id=info["actor_id"],
            economy=EconomyKind(spec["economy"].upper()), resolution_kind="TYPED",
            target_kind=spec.get("target_kind", "CELL"), range_ft=int(spec.get("range_ft", 60)), parameters=params))
        if consumable_id == RECOVERY:
            administer = deepcopy(typed)
            administer["effects"][0]["applies_to"] = "target"
            made.append(ActionDefinition(source_definition_id=source + ".administer", display_name="Administer Nine-Breath Recovery Pill",
                owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="ANY_CREATURE", range_ft=5,
                parameters={**params, "typed": administer, "consumable_administer": True,
                            "description": "Give one pill to another creature at 0 Hit Points within reach; it regains 2d8 + 2 Hit Points."}))
    return made or None


@hook("candidate_allowed")
def _stock_gate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Hide a consumable action once its purchased batch is spent; other actions are untouched."""
    if action is None:
        return None
    quantity = (getattr(action, "parameters", None) or {}).get("consumable_batch_quantity")
    source = str((((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source")) or "")
    if quantity is None or not source.startswith("consumable."):
        return None
    if not remaining(actor, source[len("consumable."):], int(quantity)):
        return False
    from . import ai_controlled
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", ()) or ()), ""))
    if ai_controlled(engine, actor) and target is not None:
        effects = ((action.parameters or {}).get("typed") or {}).get("effects") or []
        self_benefit = target.entity_id == actor.entity_id and any(
            isinstance(row, dict) and row.get("type") in {"healing", "treasure_free_step"}
            for row in effects
        )
        beneficial = bool((action.parameters or {}).get("consumable_administer")) or self_benefit
        if (target.team_id == actor.team_id) != beneficial:
            return False
    if (action.parameters or {}).get("consumable_administer"):
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", ()) or ()), ""))
        return target is not None and target.entity_id != actor.entity_id and target.current_hp == 0 and target.life_state != "DEAD"
    return True


@effect("treasure_consumable_spend")
def _spend(ctx: Any, effect_row: dict[str, Any]) -> None:
    """Charge one use of the purchased batch this activation consumed."""
    key = SPENT_PREFIX + str(effect_row.get("consumable_id"))
    ctx.actor.turn_flags[key] = int(ctx.actor.turn_flags.get(key, 0)) + 1

@effect("treasure_burst_objects")
def burst_objects(ctx: Any, row: dict[str, Any]) -> None:
    """Printed object clauses; freeze all reached objects before changing a blocker."""
    from ..object_geometry import target_cells
    from ..typed_executor import in_area
    from .objects import deal, ignite
    engine = ctx.engine
    aim = ctx.damage_cache.get("_checkpoint_aim") or (ctx.intent.destination if ctx.intent else None)
    if aim is None:
        return
    area = ctx.typed["area"]
    struck = []
    for obj in engine.state.objects.values():
        if obj.destroyed:
            continue
        cells = target_cells(engine, obj)
        own = {(c.x, c.y) for c in cells}
        if any(in_area(engine, ctx.actor.position, aim, cell, {**area, "spreads": True})
               and not any(p in engine.grid.blocked and p not in own for p in engine.grid.ray_cells(aim, cell)[1:-1])
               for cell in cells):
            struck.append(obj)
    for obj in struck:
        if row["mode"] == "ignite" and obj.unattended and obj.flammable:
            ignite(engine, obj.object_id, ctx.source, ctx.actor.entity_id)
        elif row["mode"] == "maximum_force" and (obj.unattended or (obj.component or {}).get("role") in {"eye", "node", "anchor"}):
            deal(engine, ctx.actor, obj, [(48, "FORCE")], ctx.source)


@hook("object_targets")
def attack_object_targets(engine: Any, actor: Any, action: Any) -> list[str] | None:
    source = str(((action.parameters or {}).get("typed") or {}).get("source"))
    if source not in {"consumable." + FIREBOLT, "consumable." + CORROSIVE}:
        return None
    return [obj.object_id for obj in engine.state.objects.values() if not obj.destroyed and obj.ac is not None and obj.current_hp is not None
            and (source.endswith(FIREBOLT) or obj.unattended or (obj.component or {}).get("role") in {"eye", "node", "anchor"})]


@hook("object_action")
def attack_object(engine: Any, actor: Any, action: Any, obj: Any, candidate: Any, intent: Any) -> bool | None:
    source = str(((action.parameters or {}).get("typed") or {}).get("source"))
    if source not in {"consumable." + FIREBOLT, "consumable." + CORROSIVE}:
        return None
    cid = source[len("consumable."):]
    from ..typed_executor import Context
    from .objects import object_damage
    ctx = Context(engine, actor, action, intent, action.parameters["typed"], [], None)
    ctx.damage_cache["_object"] = obj
    if cid == FIREBOLT:
        object_damage(ctx, {"type": "object_damage", "attack_roll": True, "dice": {"count": 4, "sides": 8}, "damage_types": ["fire"]})
    else:
        object_damage(ctx, {"type": "object_damage", "attack_roll": True, "flat": 24, "damage_types": ["acid"]})
        damaged = engine.state.objects[obj.object_id]
        component = damaged.component or {}
        if damaged.destroyed and not component.get("created_by") and not component.get("artifact") and not component.get("magical"):
            engine._update_object(damaged.model_copy(update={"component": {**component, "dissolved": True}}), ctx.source, actor.entity_id)
    _spend(ctx, {"consumable_id": cid})
    return True


@effect("treasure_free_step")
def free_step(ctx: Any, row: dict[str, Any]) -> None:
    from .rider_movement import routes, step
    from .needle import ask, checkpoint_id
    paths = routes(ctx.engine, ctx.actor, int(row["distance_ft"]))
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "treasure_step", ctx.source), ctx.actor,
                   "choice:treasure.free_step", list(paths), labels={key: f"Move to {path[-1].x},{path[-1].y}" for key, path in paths.items()},
                   prompt=f"{ctx.action.display_name}: spend one talisman and your Bonus Action to move to a reachable space within 20 feet. Declining (staying here) still spends both.",
                   minimum=0, maximum=1, allow_decline=True, name=ctx.action.display_name)
    if selected:
        step(ctx.engine, ctx.actor, paths[selected[0]], ctx.source)


@hook("choice_options")
def consumable_choices(engine: Any, intent: Any, checkpoint: str, reactor_id: str, choice_id: str, context: dict[str, Any]) -> dict[str, Any] | None:
    from .needle import option_spec
    return option_spec(choice_id, context, "choice:treasure.")
