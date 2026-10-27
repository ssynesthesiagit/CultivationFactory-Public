"""Devil Heart, Second Furnace Subpath (subpaths worker 2026-09-28: "make sure all the talents and class abilities
... is applied"). Reuses combat/ext/qi_path.py's Golden Core Efficiency refund-after-resolution pattern (the cost
was already paid when the feature was used; this table has no "reduce a cost before it is paid" hook).

Devil-Qi Augment (CL6) is an optional once-per-turn ``damage_dealt`` rider. "Once per turn" uses the shared per-creature
``typed_once_turn:`` clock (reset at each creature's turn start), and the augment applies once to the whole activation
(a Barrage, volley or multiattack gets it once). Its typed passive row is ownership evidence; the hook asks the owning
player or AI, spends the compiled Devil Qi pool, adds the chosen damage, and only applies the selected rider from the
positive-damage callback for that added packet. A decline leaves later packets of the same activation offerable.

Demon Seed Overdraw  once per turn, when you pay at least 1 Qi for a Qi feature: refund Proficiency Bonus Qi (never
                     below 0), gain 1 Corruption, then gain 1 Devil Qi and choose one Seed-Fed Reinforcement
                     (Temporary HP = PB; move 5 feet; move your Domain Armament up to 10 feet -- GM-adjudicated,
                     since the table does not expose a generic "move a summoned Domain Armament" hook here; or
                     Advantage on an Intimidation or Cultivation Check before the end of your next turn), a free
                     player choice kept until changed. The printed exclusion list (Legendary/artifact/Secret-Law/
                     Immortal Art/permanent-transformation/etc.) is GM-adjudicated.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

DEMON_SEED_OVERDRAW = "tianxia.subpath.qi.devil_heart_second_furnace.feature.demon_seed_overdraw"
QI = "resource:core.qi"
CORRUPTION = "resource:named.corruption"
DEVIL_QI = "resource:named.devil_qi"
DEVIL_QI_AUGMENT = "tianxia.subpath.qi.devil_heart_second_furnace.feature.devil_qi_augment"
CHOICE = "condition:typed.demon_seed_overdraw_choice"
USED_AUGMENT = "typed_once_turn:devil_qi_augment"
RIDER_NAMES = {"damage": "extra damage", "no_reactions": "no Reactions", "push": "push 5 feet",
               "pull": "pull 5 feet", "speed": "Speed reduced by 10 feet", "temp_hp": "Temporary Hit Points",
               "armament": "move Domain Armament"}
OPTIONS = {"temp_hp": "Temporary Hit Points", "move": "Move 5 Feet", "armament": "Move Domain Armament", "advantage": "Advantage on a Check"}


@hook("history_event_metadata")
def augment_history_name(event: dict[str, Any], events: Any) -> dict[str, str] | None:
    """Give the independently attributed Augment outcomes their plain player name."""
    source = str((event.get("payload") or {}).get("display_source_id") or event.get("source_definition_id") or "")
    prefix = DEVIL_QI_AUGMENT + "."
    if not source.startswith(prefix) or source[len(prefix):] not in RIDER_NAMES:
        return None
    return {"display_name": "Devil-Qi Augment: " + RIDER_NAMES[source[len(prefix):]]}


def _rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "devil_heart_second_furnace" and row.get("kind") == "demon_seed_overdraw"]


def _owns_augment(engine: Any, actor: Any) -> bool:
    return any(row.get("block") == "devil_heart_second_furnace" and row.get("kind") == "devil_qi_augment"
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


QI_PATH_FEATURE_PREFIX = "tianxia.path.qi_cultivation."
QUALIFYING_PREFIXES = (QI_PATH_FEATURE_PREFIX, "tianxia.subpath.", "tianxia.talent.", "tianxia.recorded_art.",
                       "tianxia.forged_technique.", "recorded_art.", "forged_technique.")


def _qualifying_source(ctx: Any) -> bool:
    """Printed sources only: Qi Path features, Subpath features, Sphere abilities, Recorded Arts, Forged Techniques and
    weapon-delivered cultivation techniques. Owner ruling (2026-10-11): all Sphere abilities count as talents.
    Other Path features and generated basic weapon attacks do not qualify merely because they carry a weapon.

    Factory runtime ids are opaque. Resolve explicit damage attribution, or the compiled row's printed source/owning
    menu feature, through the shared authority reader. Forged Techniques retain provenance even with user-chosen ids.
    Stable legacy source namespaces remain supported only when there is no authority record to classify.
    """
    from ..typed_numbers import authority_mechanics

    typed = ctx.typed or {}
    mechanics = authority_mechanics()
    attribution = getattr(ctx, "effect_source", None)
    if not attribution and typed.get("forged_from") in mechanics:
        return True
    source = str(attribution or typed.get("option_of") or typed.get("source")
                 or getattr(ctx.action, "source_definition_id", "") or ctx.source or "")
    # Named passive damage keeps the enclosing action for delivery/targeting,
    # but its own printed ability determines Augment eligibility.
    source = source.removeprefix("passive:")
    row = mechanics.get(source)
    if row is not None:
        kind = row.get("kind")
        return bool((kind == "path_feature" and row.get("path_id") == "tianxia.path.qi_cultivation")
                    or kind == "subpath_feature"
                    or row.get("sphere_id")
                    or row.get("weapon_delivery") or (row.get("range") or {}).get("weapon_delivery"))
    return source.startswith(QUALIFYING_PREFIXES)


def _source_cl(engine: Any, source_id: str, source_actor_id: str | None, data: dict[str, Any]) -> int:
    for key in ("source_cl", "source_level", "cl"):
        if isinstance(data.get(key), int):
            return int(data[key])
    action = (getattr(engine, "action_catalog", {}) or {}).get(source_id)
    numbers = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("numbers") or {}
    if isinstance(numbers.get("cl"), int):
        return int(numbers["cl"])
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(str(source_actor_id or ""), [])
    return max((int((row.get("numbers") or {}).get("cl") or 0) for row in rows), default=0)


def _consecrated_source_cl(ctx: Any, target: Any) -> int:
    """Return the level of a stored Consecrated condition or zone protecting this creature."""
    levels = []
    for condition in target.conditions.values():
        data = dict(condition.data or {})
        action = (getattr(ctx.engine, "action_catalog", {}) or {}).get(condition.source_definition_id)
        description = " ".join((str(condition.condition_id), str(data.get("label") or ""), str(data.get("name") or ""),
                                str(condition.source_definition_id), str(getattr(action, "display_name", "")))).lower()
        if "consecrat" not in description:
            continue
        levels.append(_source_cl(ctx.engine, condition.source_definition_id, condition.source_actor_id, data))
    from ..spatial_areas import zone_contains
    for zone in (getattr(ctx.engine.state, "zones", {}) or {}).values():
        if not zone.active or not zone_contains(ctx.engine, target, zone):
            continue
        action = (getattr(ctx.engine, "action_catalog", {}) or {}).get(zone.source_definition_id)
        description = " ".join((zone.source_definition_id, str(getattr(action, "display_name", "")),
                                str((zone.trigger_profile or {}).get("label") or ""))).lower()
        if "consecrat" in description:
            owner_id = getattr(zone, "owner_id", None)
            data = dict(zone.trigger_profile or {})
            levels.append(_source_cl(ctx.engine, zone.source_definition_id, owner_id, data))
    return max(levels, default=0)


def _prompt_context(ctx: Any, target: Any) -> dict[str, Any]:
    """Shared triggering-action metadata for every augment prompt: the enclosing action, the creature it hit, and the
    augment's own Devil Qi price (never the enclosing action's cost)."""
    action_name = getattr(ctx.action, "display_name", None) or "the enclosing attack"
    return {"source_definition_id": DEVIL_QI_AUGMENT, "action_name": action_name,
            "action_actor_id": ctx.actor.entity_id, "affected_id": target.entity_id, "cost": "1 Devil Qi"}


def _ask(ctx: Any, target: Any, key: str, options: list[str], labels: dict[str, str], prompt: str,
         *, allow_decline: bool = False, chooser: Any = None) -> list[str]:
    from .needle import CHOICE as NEEDLE_CHOICE, ask, checkpoint_id

    chooser = chooser or ctx.actor
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "DEVIL_QI_AUGMENT", ctx.actor.entity_id,
                                                       target.entity_id, key), chooser,
               NEEDLE_CHOICE + "devil_qi_augment", options, labels=labels, allow_decline=allow_decline,
               automatic=True, default="decline" if allow_decline else "first", target_id=target.entity_id,
               name="Devil-Qi Augment", feature_id=DEVIL_QI_AUGMENT, prompt=prompt,
               prompt_context=_prompt_context(ctx, target))


def _armament_present(actor: Any) -> bool:
    return any(c.condition_id == "condition:typed.domain_armament" for c in actor.conditions.values())


def move_armament_choice(ctx: Any, target: Any, distance_ft: int = 15, *, feature_id: str = DEVIL_QI_AUGMENT, name: str = "Devil-Qi Augment") -> bool:
    """Shared optional armament positioning for Augment and furnace_core.

    distance_ft bounds this one grant; native control range and saved event/state
    remain qi_path's. Never creates an armament. Returns True only when the
    selected point became the armament's saved position; decline or failure
    leaves an optional once-per-turn movement unspent.
    """
    from . import qi_path
    from .needle import ask, cell_id, checkpoint_id

    armed = qi_path.armament_condition(ctx.actor)
    if armed is None:
        return False
    current = qi_path.armament_point(ctx.actor)
    max_range = qi_path.armament_control_range(ctx.engine, ctx.actor)
    candidates = []
    occupied = {cell for other in ctx.engine.state.actors.values() if other.active
                for cell in ctx.engine._actor_cells(other)}
    for x in range(ctx.engine.grid.width):
        for y in range(ctx.engine.grid.height):
            cell = (x, y)
            distance = int(ctx.engine.grid.distance_ft(current, cell))
            if (distance > 0 and distance <= distance_ft
                    and int(ctx.engine.grid.distance_ft(cell, ctx.actor.position)) <= max_range
                    and ctx.engine.grid.placement_legal(cell, occupied_cells=occupied)):
                candidates.append(ctx.actor.position.model_copy(update={"x": int(x), "y": int(y)}))
    if not candidates:
        return False
    options = [cell_id(point) for point in sorted(candidates, key=lambda p: (p.x, p.y))]
    labels = {cell_id(point): f"Move the Domain Armament to ({point.x}, {point.y})" for point in candidates}
    from .choice_prompt import action_context
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "DEVIL_QI_AUGMENT_ARMAMENT" if feature_id == DEVIL_QI_AUGMENT else "FURNACE_ARMAMENT:" + feature_id, ctx.actor.entity_id,
                                                        target.entity_id), ctx.actor,
                 "choice:needle.devil_qi_augment_armament", options, labels=labels, allow_decline=True,
                 automatic=True, default="decline", target_id=target.entity_id, name=name,
                 feature_id=feature_id,
                 prompt=f"{name}: move your Domain Armament up to {distance_ft} feet. "
                        f"Choose its new space.",
                 prompt_context={**action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id, target, action=ctx.action),
                                 "cost": "No extra cost"})
    if not picked:
        return False
    point = next((p for p in candidates if cell_id(p) == picked[0]), None)
    if point is not None:
        qi_path.move_armament(ctx.engine, ctx.actor, point, ctx.source, distance_ft=distance_ft)
        return qi_path.armament_point(ctx.actor) == (int(point.x), int(point.y))
    return False


def _apply_rider(ctx: Any, target: Any, rider: str) -> None:
    from .. import typed_executor as te

    ctx = ctx.with_source(DEVIL_QI_AUGMENT + "." + rider)
    if rider == "no_reactions":
        te.run_effects(ctx.on_hit_context(target), [{"type": "condition", "applies_to": "target",
                                                     "condition": "reaction_denied",
                                                     "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    elif rider in ("push", "pull"):
        te.run_effects(ctx.on_hit_context(target), [{"type": "forced_movement", "applies_to": "target",
                                                     "distance_ft": 5, "direction": "away" if rider == "push" else "toward"}])
    elif rider == "speed":
        te.run_effects(ctx.on_hit_context(target), [{"type": "speed", "applies_to": "target", "flat": -10, "source_owned": True,
                                                     "expires_on": "START_OF_SOURCE_NEXT_TURN"}])
    elif rider == "temp_hp":
        te.run_effects(ctx.on_hit_context(ctx.actor), [{"type": "temp_hp", "applies_to": "self", "formula": "pb", "flat": 0}])
    elif rider == "armament":
        move_armament_choice(ctx, target)


@hook("damage_packet_selection")
def augment_packet_selection(ctx: Any, target: Any, packet_kinds: tuple[str, ...]) -> None:
    """Select a mixed hit's delivery before damage; a decline never spends the use."""
    ctx.damage_cache.pop("_devil_qi_packet", None)
    actor = ctx.actor
    if (len(packet_kinds) < 2
            or not _owns_augment(ctx.engine, actor) or not _qualifying_source(ctx)
            or actor.turn_flags.get(USED_AUGMENT) or int(actor.resources.get(DEVIL_QI, 0)) < 1):
        return
    selected = _ask(ctx, target, "packet", list(packet_kinds),
        {"weapon": "Add Devil-Qi Augment to the weapon damage only",
         "technique": "Add Devil-Qi Augment to the technique damage only"},
        f"Devil-Qi Augment: {ctx.action.display_name} hits {target.display_name}. Choose which damage "
        "receives the extra dice and rider (1 Devil Qi if you accept after it deals damage).")
    if selected:
        ctx.damage_cache["_devil_qi_packet"] = selected[0]


@hook("damage_dealt")
def devil_qi_augment(ctx: Any, target: Any, amount: int) -> None:
    """Offer one printed augment after eligible damage, once on each creature's turn."""
    engine, actor = ctx.engine, ctx.actor
    pending = (ctx.damage_cache or {}).get("_devil_qi_augment_pending")
    if pending and target is not None and target.entity_id == pending.get("target_id"):
        if amount > 0 and not pending.get("save_success"):
            _apply_rider(ctx, target, str(pending["rider"]))
        return
    if (amount <= 0 or target is None or not target.active
            or not _owns_augment(engine, actor) or not _qualifying_source(ctx)
            or int(actor.resources.get(DEVIL_QI, 0) or 0) < 1
            or actor.turn_flags.get(USED_AUGMENT)):
        return
    selected = ctx.damage_cache.get("_devil_qi_packet")
    if selected and selected != ctx.damage_packet_kind:
        return
    cl = int(ctx.numbers.get("cl") or 1)
    dice = 4 if cl >= 17 else 3 if cl >= 11 else 2
    ask_prompt = (f"Spend 1 Devil Qi to add {dice}d8 necrotic, psychic, or force damage and a rider to "
                  f"{target.display_name}?")
    offer = _ask(ctx, target, "offer", ["augment", "skip"],
                 {"augment": "Spend 1 Devil Qi to add damage and choose a rider", "skip": "Save your Devil Qi"},
                 ask_prompt, allow_decline=True)
    if not offer or offer[0] != "augment":
        ctx.damage_cache.pop("_devil_qi_packet", None)
        return

    damage_type = _ask(ctx, target, "damage_type", ["necrotic", "psychic", "force"],
                       {"necrotic": "Necrotic damage", "psychic": "Psychic damage", "force": "Force damage"},
                       f"Devil-Qi Augment: choose the extra damage type against {target.display_name}.")[0]
    rider_options = ["no_reactions", "push", "pull", "speed", "temp_hp"]
    rider_labels = {
        "no_reactions": f"{target.display_name} cannot take Reactions until its next turn starts",
        "push": f"Push {target.display_name} 5 feet", "pull": f"Pull {target.display_name} 5 feet",
        "speed": f"Reduce {target.display_name}'s Speed by 10 feet until your next turn starts",
        "temp_hp": f"Gain Temporary Hit Points equal to your Proficiency Bonus",
    }
    if _armament_present(actor):
        rider_options.append("armament")
        rider_labels["armament"] = "Move your Domain Armament up to 15 feet"
    rider = _ask(ctx, target, "rider", rider_options, rider_labels,
                 f"Devil-Qi Augment: choose one rider for damaging {target.display_name}.")[0]

    from .. import typed_executor as te

    consecrated_cl = _consecrated_source_cl(ctx, target)
    damage_effect = {"type": "damage", "applies_to": "target", "dice": {"count": dice, "sides": 8},
                     "damage_types": [damage_type], "evidence": f"Devil-Qi Augment: add {dice}d8 {damage_type.title()} damage"}
    if consecrated_cl >= cl and consecrated_cl > 0:
        # Consecrated Resistance: the protected creature MAY make the CON save; its owner decides (AI decides automatically).
        choice = _ask(ctx, target, "consecrated", ["save", "decline"],
                      {"save": f"Make a Constitution save against {actor.display_name}'s Cultivation Save DC "
                               f"{int(ctx.numbers.get('save_dc') or 10)}: on success take half the extra damage and ignore the rider",
                       "decline": "Skip the save: take the full extra damage and the rider"},
                      f"Devil-Qi Augment: {target.display_name} is protected by a consecrated effect. "
                      f"Make a Constitution save against {actor.display_name}'s Cultivation Save DC "
                      f"{int(ctx.numbers.get('save_dc') or 10)}?",
                      allow_decline=True, chooser=target)
        if choice and choice[0] == "save":
            damage_effect = {"type": "save", "applies_to": "target", "ability": "CON",
                             # This save resolves bonus damage belonging to the
                             # selected hit, so its failure keeps that hit's
                             # critical and attack-only defense context.
                             "inherit_attack_damage_context": True,
                             "on_success": [{"type": "half_damage"}],
                             "on_fail": [damage_effect]}

    actor.turn_flags[USED_AUGMENT] = True
    engine._spend_resource(actor, DEVIL_QI, 1, "passive:" + DEVIL_QI_AUGMENT)
    cache = ctx.damage_cache
    cache["_devil_qi_augment_pending"] = {"target_id": target.entity_id, "rider": rider}
    try:
        te.run_effects(ctx.on_hit_context(target).with_source(DEVIL_QI_AUGMENT + ".damage"), [damage_effect])
    finally:
        cache.pop("_devil_qi_augment_pending", None)


@hook("after_save_resolved")
def devil_qi_consecrated_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Mark the in-flight augment save outcome so a successful save cannot apply its rider."""
    pending = (ctx.damage_cache or {}).get("_devil_qi_augment_pending")
    if pending and subject is not None and subject.entity_id == pending.get("target_id") and ability.upper() == "CON":
        pending["save_success"] = not bool(failed)


@hook("compile_block")
def devil_heart_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "devil_heart_second_furnace":
        return None
    return [{**row, "block": "devil_heart_second_furnace", "kind": spec.get("kind")}]


@hook("compile_actions")
def demon_seed_choices(info: dict[str, Any]) -> list[Any] | None:
    if DEMON_SEED_OVERDRAW not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..action_variants import choice, with_variant

    # One Seed-Fed Reinforcement setting with a reinforcement axis.
    return [with_variant(ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.demon_seed_overdraw.{key}", display_name=f"Seed-Fed Reinforcement: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "demon_seed_overdraw_choice", "choice": key}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True}),
        f"action:typed.{info['short']}.demon_seed_overdraw", "Seed-Fed Reinforcement", [choice("reinforcement", key, label)])
        for key, label in OPTIONS.items()]


@effect("demon_seed_overdraw_choice")
def demon_seed_overdraw_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Seed-Fed Reinforcement: {OPTIONS.get(str(eff.get('choice')), '')}"})


@hook("technique_used")
def demon_seed_overdraw(ctx: Any) -> None:
    actor = ctx.actor
    if not _rows(ctx.engine, actor) or actor.turn_flags.get("demon_seed_overdraw"):
        return
    paid = sum(int(amount) for resource, amount in (ctx.action.costs or ()) if resource == QI)
    if paid < 1 or QI not in actor.resources:
        return
    actor.turn_flags["demon_seed_overdraw"] = True
    engine = ctx.engine
    pb = int(ctx.numbers.get("pb") or 2)
    from ..technique_costs import refund
    refund(engine, actor, ctx.source, ctx.action.costs, QI, min(pb, paid), f"passive:{DEMON_SEED_OVERDRAW}")
    if CORRUPTION in actor.resources:
        engine._gain_resource(actor, CORRUPTION, 1, f"passive:{DEMON_SEED_OVERDRAW}")
    if DEVIL_QI not in actor.resources:
        return
    engine._gain_resource(actor, DEVIL_QI, 1, f"passive:{DEMON_SEED_OVERDRAW}")
    choice = next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == CHOICE), "temp_hp")
    from .. import typed_executor

    sub = typed_executor.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [actor], actor, {})
    if choice == "temp_hp":
        typed_executor.run_effects(sub, [{"type": "temp_hp", "applies_to": "self", "flat": 0, "formula": "pb",
                                          "evidence": "Seed-Fed Reinforcement: Temporary Hit Points equal to PB"}])
    elif choice == "move":
        typed_executor.run_effects(sub, [{"type": "movement", "applies_to": "self", "distance_ft": 5,
                                          "evidence": "Seed-Fed Reinforcement: move 5 feet without provoking"}])
    elif choice == "advantage":
        typed_executor.run_effects(sub, [{"type": "advantage", "applies_to": "self", "on": "one Intimidation or Cultivation Check",
                                          "expires_on": "START_OF_SOURCE_NEXT_TURN",
                                          "evidence": "Seed-Fed Reinforcement: Advantage on one Intimidation or Cultivation Check"}])
    else:
        sub.rider("Seed-Fed Reinforcement: move your Domain Armament up to 10 feet (GM-adjudicated positioning).")
