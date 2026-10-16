"""Body-path martial Insights that ride a hit, a fall, a save or a blow taken (OPUS1 batch 1).

Each Insight is sealed into one passive row of block ``martial_insights`` (kind = the Insight id), so
every hook below returns at once for a creature without that row.

Sword-Line Meridian       once per turn, an unarmed or sword hit made right after at least 10 feet of the
                          attacker's own voluntary movement (no teleport, no forced move, no other attack or action in
                          between) adds Proficiency Bonus damage to that hit (confirmed_hit_roll_bonus); after
                          the attack the attacker may move up to 5 feet without provoking.
Avalanche Shoulder        once per turn, a melee hit on a creature the attacker walked at least 10 feet toward
                          this turn (approach.approached_ft) may spend 1 Stamina: 2d6 Bludgeoning, then a
                          Strength save against the attacker's Cultivation Save DC or pushed up to 10 feet
                          (distance chosen) and knocked Prone.
Ashura Furnace            while below half its maximum Hit Points: once per turn an unarmed hit adds Proficiency
                          Bonus Fire or Necrotic damage (chosen for that hit), ordinary (map) Difficult Terrain
                          costs no extra movement, and saves against Frightened have Advantage.
Heaven-Lifting Grip       a creature the owner grapples is also Restrained for as long as that grapple lasts (a
                          linked_holds child: it ends with the grapple, and escaping the grapple frees both); the
                          size limit ("up to two sizes larger") is the effective_size passive trait in the feature block.
Corpse-Tempered Body      Grave Tempering, once per fight (a fight is one scene): the first time the owner activates a
                          Death talent or would take Necrotic damage, it gains Resistance to Necrotic damage for 1 minute;
                          when damage triggered it, that packet is already resisted (before_damage_defenses).
Iron Shirt Adept          while holding Martial Focus and wearing no Heavy armor: falling damage is reduced by
                          5 x Proficiency Bonus; once per scene the owner may take Advantage on a Constitution
                          save against poison, a physical shock (Stunned) or bodily disruption; a hostile
                          creature that damages the owner with an Unarmed Strike or natural weapon takes
                          Proficiency Bonus Bludgeoning damage.

Turn flags hold only strings/integers. Once-per-turn flags carry the "<round>:<actor>" stamp and are
cleared at the owner's turn start anyway; the once-per-scene flag uses the retained ``_round_`` namespace
so it lasts the whole fight (a fight is one scene) and survives reload.
"""
from __future__ import annotations

from typing import Any

from . import hook, note
from .passive_rows import row_of

BLOCK = "martial_insights"
SWORD_LINE = "insight.sword-line-meridian"
AVALANCHE = "insight.legacy-avalanche-shoulder"
ASHURA = "insight.ashura-furnace"
IRON_SHIRT = "insight.iron-shirt-adept"
HEAVEN_GRIP = "insight.legacy-heaven-lifting-grip"
CORPSE = "insight.corpse-tempered-body"
OUTCOMES = {
    SWORD_LINE: "Once per turn, an unarmed or sword hit right after you voluntarily move at least 10 feet deals extra damage equal to "
                "your Proficiency Bonus; afterwards you may move up to 5 feet without provoking Opportunity Attacks",
    AVALANCHE: "Once per turn, after walking at least 10 feet toward a creature and hitting it in melee, you may spend "
               "1 Stamina: it takes 2d6 extra Bludgeoning damage and must pass a Strength save against your Cultivation "
               "Save DC or be pushed up to 10 feet and knocked Prone",
    ASHURA: "While you are below half your maximum Hit Points: once per turn one unarmed hit deals extra Fire or Necrotic "
            "damage equal to your Proficiency Bonus (you choose), ordinary Difficult Terrain costs you no extra "
            "movement, and you have Advantage on saves against being Frightened",
    IRON_SHIRT: "While you hold Martial Focus and wear no Heavy armor: falling damage is reduced by 5 times your "
                "Proficiency Bonus; once per scene you may take Advantage on a Constitution save against poison, a "
                "physical shock or bodily disruption; a hostile creature that damages you with an Unarmed Strike or "
                "natural weapon takes Bludgeoning damage equal to your Proficiency Bonus",
    HEAVEN_GRIP: "A creature you grapple is also Restrained until the grapple ends; escaping your grapple frees it from both",
    CORPSE: "Grave Tempering: once per fight, the first time you use a Death talent or would take Necrotic damage, you gain "
            "Resistance to Necrotic damage for 1 minute (including that damage)",
}
FOCUS = "resource:core.martial_focus"
STAMINA = "resource:core.stamina"
# What a failed Constitution save would do, for Iron Shirt Adept's "physical shock, poison, or bodily
# disruption": the save's named consequences (typed_executor plug_in_named) and printed save categories.
IRON_SHIRT_SAVES = frozenset({"poisoned", "damage:poison", "stunned", "disease", "category:poison", "category:disease",
                              "category:bodily_corruption", "category:mutation", "category:forced_transformation",
                              "category:physical_shock"})


def owned(engine: Any, actor: Any, feature: str) -> dict[str, Any] | None:
    return row_of(engine, actor.entity_id, BLOCK, feature) if actor is not None else None


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _turn_used(engine: Any, actor: Any, feature: str) -> bool:
    return actor.turn_flags.get("martial_insights:" + feature) == _stamp(engine)


def _use_turn(engine: Any, actor: Any, feature: str) -> None:
    actor.turn_flags["martial_insights:" + feature] = _stamp(engine)


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    feature = row["feature_id"]
    return [{**row, "kind": feature, "player_outcome": OUTCOMES[feature], "pb": int(numbers["pb"]), "cl": int(numbers["cl"]),
             "armor": str(numbers.get("armor") or "")}]


def _child(ctx: Any, target: Any, feature: str) -> Any:
    """A context for damage that belongs to this hit, named for the Insight."""
    return ctx.on_hit_context(target, effect_source=feature, damage_cache={"_bonus": True, "_potency_used": True})


def _sword_like(ctx: Any) -> bool:
    from .integrated_weapons import in_group
    from .reach_bonus import is_unarmed

    return is_unarmed(ctx.action) or in_group(ctx.typed, "sword")


# ------------------------------------------------------------------------------------------ Sword-Line Meridian
@hook("confirmed_hit_roll_bonus")
def sword_line_damage(engine: Any, attacker: Any, target: Any, spec: Any, intent: Any, source: Any) -> int | None:
    row = owned(engine, attacker, SWORD_LINE)
    if not row or _turn_used(engine, attacker, SWORD_LINE):
        return None
    from .attack_scope import current
    from .approach import moved_before_attack_ft

    frame = current(engine)
    ctx = (frame or {}).get("context")
    if ctx is None or ctx.actor is not attacker or not _sword_like(ctx) or moved_before_attack_ft(engine, attacker) < 10:
        return None
    _use_turn(engine, attacker, SWORD_LINE)
    ctx.damage_cache["_sword_line_step"] = target.entity_id
    note(engine, f"passive:{SWORD_LINE}", attacker,
         f"Sword-Line Meridian: {attacker.display_name} struck right after moving at least 10 feet, so the hit deals "
         f"{row['pb']} extra damage (Proficiency Bonus, once per turn).", (target,))
    return int(row["pb"])


@hook("after_hit")
def sword_line_step(ctx: Any, target: Any, kind: str) -> None:
    if ctx.damage_cache.get("_sword_line_step") != target.entity_id or not owned(ctx.engine, ctx.actor, SWORD_LINE):
        return
    ctx.damage_cache.pop("_sword_line_step", None)
    if not ctx.actor.active:
        return
    from . import ai_controlled
    from .granted_moves import commit, destinations
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    routes = [row for row in destinations(engine, actor, 5, lambda cell: cell != actor.position) if row[2] <= 5]
    if ai_controlled(engine, actor):
        from ..senses import perceives_cell
        routes = [row for row in routes if all(perceives_cell(engine, actor, cell) for cell in row[1][1:])]
    paths = {f"cell:{cell.x},{cell.y},{cell.z}": (cell, path) for cell, path, _cost in routes}
    if not paths:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, SWORD_LINE, "step", target.entity_id), actor,
                 "choice:needle.insights8_step", sorted(paths), allow_decline=True,
                 name="Sword-Line Meridian", feature_id=SWORD_LINE, target_id=actor.entity_id,
                 labels={key: f"Move to {cell.x},{cell.y} at {cell.z * 5} feet altitude"
                         for key, (cell, _path) in paths.items()},
                 prompt=(f"Sword-Line Meridian: your {ctx.action.display_name} hit {target.display_name} after your run-up. "
                         "Move up to 5 feet without provoking Opportunity Attacks, or stay put. No action or resource cost."))
    if picked:
        commit(engine, actor, paths[picked[0]][1], f"passive:{SWORD_LINE}",
               budget_ft=5, provokes=False, intent=ctx.intent)


# ------------------------------------------------------------------------------------------- Avalanche Shoulder
def _melee(ctx: Any, kind: str) -> bool:
    from ..typed_executor import ranged_attack_now

    if kind == "unarmed":
        return True
    return kind == "weapon" and not ranged_attack_now(ctx) and not str(ctx.action.source_definition_id).endswith("#thrown")


@hook("after_hit_choice")
def avalanche(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    row = owned(engine, actor, AVALANCHE)
    if not row or not target.active or _turn_used(engine, actor, AVALANCHE) or not _melee(ctx, kind):
        return
    from .approach import approached_ft
    from .choice_costs import payable
    from .needle import ask, checkpoint_id

    if approached_ft(engine, actor, target) < 10:
        return
    payment = payable(actor, STAMINA, 1)
    if payment is None:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, AVALANCHE, target.entity_id), actor, "choice:needle.martial_insights",
                 ["use"], allow_decline=True, name="Avalanche Shoulder", feature_id=AVALANCHE, target_id=target.entity_id,
                 payment=payment, prompt_context=payment.context(),
                 labels={"use": f"Spend 1 Stamina: 2d6 Bludgeoning to {target.display_name}, then a Strength save or pushed and Prone"},
                 prompt=(f"Avalanche Shoulder: you charged at least 10 feet toward {target.display_name} and hit it with "
                         f"{ctx.action.display_name}. Spend 1 Stamina for 2d6 extra Bludgeoning damage; it must then pass a "
                         f"Strength saving throw against your Cultivation Save DC or be pushed up to 10 feet and knocked "
                         f"Prone. Once per turn."))
    if not picked:
        return
    _use_turn(engine, actor, AVALANCHE)
    payment.pay(engine, actor, AVALANCHE)
    from ..typed_executor import run_effects

    run_effects(_child(ctx, target, AVALANCHE), [
        {"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 6}, "flat": 0, "formula": "none",
         "damage_types": ["bludgeoning"], "evidence": "Avalanche Shoulder: an additional 2d6 bludgeoning damage"},
        {"type": "save", "ability": "str", "basis": "cultivation", "on_success": [], "on_fail": [
            {"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "optional_distance_ft": True},
            {"type": "condition", "condition": "prone", "applies_to": "target", "duration": "instant",
             "evidence": "Avalanche Shoulder: knocked prone"}]}])


# ----------------------------------------------------------------------------------------------- Ashura Furnace
def _furnace_lit(engine: Any, actor: Any) -> dict[str, Any] | None:
    row = owned(engine, actor, ASHURA)
    if not row or not actor.active or actor.maximum_hp <= 0 or actor.current_hp * 2 >= actor.maximum_hp:
        return None
    return row


@hook("after_hit_choice")
def ashura_strike(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    row = _furnace_lit(engine, actor)
    if not row or kind != "unarmed" or not target.active or _turn_used(engine, actor, ASHURA):
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, ASHURA, target.entity_id), actor, "choice:needle.martial_insights",
                 ["FIRE", "NECROTIC"], name="Ashura Furnace", feature_id=ASHURA, target_id=target.entity_id,
                 labels={"FIRE": f"Add {row['pb']} Fire damage", "NECROTIC": f"Add {row['pb']} Necrotic damage"},
                 prompt=(f"Ashura Furnace: you are below half your Hit Points and your {ctx.action.display_name} hit "
                         f"{target.display_name}. Choose the type of its {row['pb']} extra damage (once per turn, no cost)."))
    _use_turn(engine, actor, ASHURA)
    from ..typed_executor import _deal

    _deal(_child(ctx, target, ASHURA), target, int(row["pb"]), (picked or ["FIRE"])[0])


@hook("difficult_exempt")
def ashura_footing(engine: Any, actor: Any) -> Any:
    if not _furnace_lit(engine, actor):
        return None
    from .. import motion, zones

    cells = frozenset(zones.nonmagical_difficult_cells(engine, actor))
    return motion.TerrainExemption(cells, nonmagical_only=True) if cells else None


@hook("save")
def ashura_courage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if "frightened" in set(named or ()) and _furnace_lit(ctx.engine, subject):
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("save_mode")
def ashura_courage_native(engine: Any, subject: Any, ability: str, dc: int, source_id: str, context: dict[str, Any]) -> str | None:
    if "frightened" in set((context or {}).get("named") or ()) and _furnace_lit(engine, subject):
        return "ADVANTAGE"
    return None


# --------------------------------------------------------------------------------------------- Iron Shirt Adept
def _shirt(engine: Any, actor: Any) -> dict[str, Any] | None:
    row = owned(engine, actor, IRON_SHIRT)
    if not row or row.get("armor") == "heavy" or int(actor.resources.get(FOCUS, 0)) < 1:
        return None
    return row


@hook("falling_damage")
def iron_shirt_fall(engine: Any, target: Any, defended: int, fall: Any, intent: Any) -> dict[str, Any] | None:
    row = _shirt(engine, target)
    if not row or defended <= 0:
        return None
    cut = 5 * int(row["pb"])
    note(engine, f"passive:{IRON_SHIRT}", target,
         f"Iron Shirt Adept: {target.display_name} takes {min(cut, defended)} less falling damage (5 times Proficiency Bonus).")
    return {"amount": max(0, defended - cut)}


SCENE_FLAG = "_round_martial_insights:iron_shirt_save"


@hook("save")
def iron_shirt_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    mode = _shirt_save(ctx.engine, ctx.intent, subject, ability, named,
                       f"{ctx.actor.display_name}'s {ctx.action.display_name}")
    return {"bonus": 0, "modes": [mode]} if mode else None


@hook("save_mode")
def iron_shirt_native_save(engine: Any, subject: Any, ability: str, dc: int, source_id: str,
                           context: dict[str, Any]) -> str | None:
    """Native saves share the typed save's consent and retained scene allowance."""
    action = engine.action_catalog.get(source_id)
    source = engine.state.actors.get((context or {}).get("source_actor_id"))
    trigger = action.display_name if action is not None else "the triggering effect"
    if source is not None:
        trigger = f"{source.display_name}'s {trigger}"
    return _shirt_save(engine, getattr(engine, "_active_intent", None), subject, ability,
                       (context or {}).get("named"), trigger)


def _shirt_save(engine: Any, intent: Any, subject: Any, ability: str, named: Any, trigger: str) -> str | None:
    if str(ability or "").upper()[:3] != "CON" or not (set(named or ()) & IRON_SHIRT_SAVES):
        return None
    row = _shirt(engine, subject)
    if not row or subject.turn_flags.get(SCENE_FLAG):
        return None
    from .needle import ask, checkpoint_id

    picked = ask(engine, intent, checkpoint_id(engine, IRON_SHIRT, "save", subject.entity_id), subject,
                 "choice:needle.martial_insights", ["use"], allow_decline=True, name="Iron Shirt Adept", feature_id=IRON_SHIRT,
                 target_id=subject.entity_id, labels={"use": "Roll this Constitution save with Advantage"},
                 prompt=(f"Iron Shirt Adept: {trigger} calls for {subject.display_name}'s Constitution "
                         f"saving throw against poison, a physical shock or bodily disruption. Use your once-per-scene "
                         f"Advantage on it? No action or resource cost."))
    if not picked:
        return None
    subject.turn_flags[SCENE_FLAG] = 1
    note(engine, f"passive:{IRON_SHIRT}", subject, f"Iron Shirt Adept: {subject.display_name} rolls this Constitution save with Advantage.")
    return "ADVANTAGE"


@hook("damage_dealt")
def iron_shirt_rebound(ctx: Any, subject: Any, amount: int) -> None:
    engine, striker = ctx.engine, ctx.actor
    if amount <= 0 or striker is subject or not striker.active or striker.team_id == subject.team_id:
        return
    row = _shirt(engine, subject)
    from .reach_bonus import is_unarmed

    if not row or not subject.active or not is_unarmed(ctx.action):
        return
    from ..gate2_runtime_models import ActionDefinition
    from ..typed_executor import Context, _deal

    action = ActionDefinition(source_definition_id=IRON_SHIRT, display_name="Iron Shirt Adept", owner_id=subject.entity_id,
                              economy="NONE", resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    rebound = Context(engine, subject, action, ctx.intent, {"source": IRON_SHIRT, "numbers": {"pb": row["pb"], "cl": row["cl"]}},
                      [striker], striker, {})
    note(engine, f"passive:{IRON_SHIRT}", subject,
         f"Iron Shirt Adept: {striker.display_name} struck {subject.display_name}'s iron-hard body and takes {row['pb']} "
         f"Bludgeoning damage.", (striker,))
    _deal(rebound, striker, int(row["pb"]), "BLUDGEONING")


# ------------------------------------------------------------------------------------------ Heaven-Lifting Grip
RESTRAINED = "condition:typed.restrained"


def _gripped_by_owner(engine: Any, target: Any, instance_id: str) -> Any:
    from .passive_traits import is_grapple

    hold = target.conditions.get(instance_id) if target is not None else None
    if hold is None or not is_grapple(hold):
        return None
    holder = engine.state.actors.get(str(hold.source_actor_id or ""))
    return holder if owned(engine, holder, HEAVEN_GRIP) else None


@hook("event")
def heaven_grip(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED":
        return
    payload = kwargs.get("payload") or {}
    instance_id = str(payload.get("instance_id") or "")
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        holder = _gripped_by_owner(engine, target, instance_id)
        if holder is None or any(c.data.get("parent_hold") == instance_id for c in target.conditions.values()):
            continue
        engine._apply_condition(target, RESTRAINED, HEAVEN_GRIP, holder.entity_id, expires_on="UNTIL_REMOVED",
                                data={"parent_hold": instance_id, "label": "Heaven-Lifting Grip"})
        note(engine, f"passive:{HEAVEN_GRIP}", holder,
             f"Heaven-Lifting Grip: {target.display_name} is Restrained for as long as {holder.display_name}'s grapple holds.",
             (target,))


@hook("hold_companions")
def heaven_grip_companions(engine: Any, actor: Any, instance_id: str) -> list[str] | None:
    """Escaping (or ending) the grapple also ends its linked Restrained, and the other way round."""
    condition = actor.conditions.get(instance_id)
    if condition is None:
        return None
    linked = [iid for iid, c in actor.conditions.items()
              if c.source_definition_id == HEAVEN_GRIP and c.data.get("parent_hold") == instance_id]
    if linked:
        return linked
    if condition.source_definition_id == HEAVEN_GRIP and condition.data.get("parent_hold") in actor.conditions:
        return [condition.data["parent_hold"]]
    return None


# ------------------------------------------------------------------------------------- Corpse-Tempered Body
DEATH = "tianxia.sphere.death"
GRAVE = "condition:typed.grave_tempering"
GRAVE_FLAG = "_round_martial_insights:grave_tempering"


def _temper(engine: Any, owner: Any, why: str) -> bool:
    if owned(engine, owner, CORPSE) is None or not owner.active or owner.turn_flags.get(GRAVE_FLAG):
        return False
    from ..typed_executor import clock_expiry

    owner.turn_flags[GRAVE_FLAG] = 1
    engine._apply_condition(owner, GRAVE, CORPSE, owner.entity_id, expires_on=clock_expiry(engine, "one_minute") or "UNTIL_REMOVED",
                            data={"rule": {"damage_resistances": ["NECROTIC"]},
                                  "label": "Grave Tempering: Resistance to Necrotic damage for 1 minute"})
    note(engine, f"passive:{CORPSE}", owner, f"Grave Tempering: {owner.display_name} {why} and gains Resistance to Necrotic damage "
                                           f"for 1 minute (once per fight).")
    return True


@hook("technique_start")
def grave_tempering_on_death_talent(engine: Any, actor: Any, action: Any) -> None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("sphere") == DEATH:
        _temper(engine, actor, f"activates {action.display_name}")
    return None


@hook("before_damage_defenses")
def grave_tempering_on_necrotic(engine: Any, target: Any, amount: int, damage_type: Any, source_id: Any, source_actor_id: Any) -> None:
    if str(damage_type or "").upper() == "NECROTIC" and amount > 0:
        _temper(engine, target, "is about to take Necrotic damage")
    return None
