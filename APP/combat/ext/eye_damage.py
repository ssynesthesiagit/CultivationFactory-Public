"""Hidden Eye talents that add damage to one of the character's own attacks (eye, 2026-09-28): Deadly Strike, Exploit
Weakness. combat/ext/mind_hidden_eye.py has the sphere's Analyze/Analyzed foundation this builds on.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .eye_common import analyzed_by, has

DEADLY_STRIKE = "TAL_THE_HIDDEN_EYE_DEADLY_STRIKE"
DEADLY_STRIKE_CHOICE = "condition:typed.deadly_strike_choice"
# Labels say what the choice gives you (owner playtest 2026-10-22: "off" read as the talent being switched
# off, but the flat +PB damage while hidden is the talent's normal effect and stays on either way).
DEADLY_STRIKE_OPTIONS = {"empowered": "first hidden attack: spend Martial Focus before rolling; on hit, +PBd6 instead of +PB",
                         "off": "normal (+PB damage while hidden, no Martial Focus)"}


# ---------------------------------------------------------------- Deadly Strike
@hook("compile_actions")
def deadly_strike_toggle(info: dict[str, Any]) -> list[Any] | None:
    """"Choose one" made ahead of a hit, kept until changed (the Black-Vein Palm/Pressure-Point Strike pattern):
    whether the first hidden melee-or-ranged hit each turn spends Martial Focus for 1d6/PB instead of the flat +PB
    the talent always gives. Default "normal" -- never invented power, never a forced spend."""
    if DEADLY_STRIKE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    from ..action_variants import choice, with_variant
    rows = [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.deadly_strike.{key}", display_name=f"Deadly Strike: {label}",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "typed": {"effects": [{"type": "deadly_strike_choice", "choice": key}], "numbers": info["numbers"],
                              "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})
        for key, label in DEADLY_STRIKE_OPTIONS.items()]
    return [with_variant(row, f"action:typed.{info['short']}.deadly_strike", "Deadly Strike", [choice("mode", key, label)])
            for row, (key, label) in zip(rows, DEADLY_STRIKE_OPTIONS.items())]


@effect("deadly_strike_choice")
def deadly_strike_choice(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._remove_condition(ctx.actor, DEADLY_STRIKE_CHOICE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, DEADLY_STRIKE_CHOICE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": eff.get("choice"), "label": f"Deadly Strike: {DEADLY_STRIKE_OPTIONS.get(str(eff.get('choice')), '')}"})


@hook("after_hit")
def deadly_strike_bonus(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if kind not in ("weapon", "unarmed") or not target.active or not has(engine, actor.entity_id, "deadly_strike"):
        return
    from .. import stealth

    from .riders14_eye import stalker_active

    from .riders14_eye import has as rider_has

    paid_before_roll = rider_has(engine, actor, "deadly_timing") and actor.turn_flags.get("eye_deadly_paid")
    if not paid_before_roll and not stalker_active(engine, actor):
        return
    weapon = ctx.typed.get("weapon") or {}
    damage_type = str(weapon.get("damage_type") or "UNTYPED")
    pb = int(ctx.numbers.get("pb") or 0)
    choice = next((str((c.data or {}).get("choice")) for c in actor.conditions.values() if c.condition_id == DEADLY_STRIKE_CHOICE), "off")
    from ..gate2_runtime_models import DiceSpec
    from ..typed_executor import _roll

    legacy = not rider_has(engine, actor, "deadly_timing") and choice == "empowered" and \
        not actor.turn_flags.get("deadly_strike_empowered_used") and actor.resources.get("resource:core.martial_focus", 0) >= 1
    if paid_before_roll or legacy:
        actor.turn_flags["eye_deadly_paid"] = False
        if legacy:
            actor.turn_flags["deadly_strike_empowered_used"] = True
            engine._spend_resource(actor, "resource:core.martial_focus", 1, ctx.source)
        amount = _roll(ctx, DiceSpec(count=pb, sides=6, modifier=0), "DAMAGE")
        engine._commit_damage(target, amount, damage_type, f"{ctx.source}.deadly_strike_empowered", actor.entity_id, ctx.intent, reaction_depth=0)
        ctx.rider(f"Deadly Strike: spent Martial Focus for {amount} extra {damage_type.lower()} damage ({pb}d6).")
        return
    if pb > 0:
        engine._commit_damage(target, pb, damage_type, f"{ctx.source}.deadly_strike", actor.entity_id, ctx.intent, reaction_depth=0)


# ---------------------------------------------------------------- Exploit Weakness
EXPLOIT_WEAKNESS = "TAL_THE_HIDDEN_EYE_EXPLOIT_WEAKNESS"
EXPLOIT_CHOICE = "choice:needle.eye_exploit_weakness"
EXPLOIT_TURN = "_round_exploit_weakness"


@hook("compile_actions")
def exploit_choice_owner(info: dict[str, Any]) -> None:
    """An owner's special-attack choices also belong to them on AI turns."""
    for row in info.get("passives") or []:
        if row.get("block") == "hidden_eye" and row.get("kind") == "exploit_weakness":
            row["choice_owner"] = True


@hook("match_start")
def saved_exploit_choice_owner(engine: Any) -> None:
    """Also expose consent for owned rows compiled before the choice-owner marker.

    Runtime metadata only: no changes to saved bundle bytes, fight state or events.
    """
    for rows in (getattr(engine, "typed_passive_rows", {}) or {}).values():
        for row in rows:
            if row.get("block") == "hidden_eye" and row.get("kind") == "exploit_weakness":
                row["choice_owner"] = True


@hook("before_attack")
def declare_exploit(engine: Any, actor: Any, target: Any, intent: Any, context: dict[str, Any]) -> dict | None:
    """Choose before the d20; declaring the special attack uses its turn allowance even on a miss."""
    if not has(engine, actor.entity_id, "exploit_weakness") or not analyzed_by(target, actor.entity_id):
        return None
    from .attack_scope import current
    from .choice_prompt import action_context
    from .needle import ask, checkpoint_id

    frame = current(engine)
    if frame is None or frame["actor_id"] != actor.entity_id or frame["target_id"] != target.entity_id:
        return None
    if (frame["effect"] or {}).get("attack_kind") != "weapon":
        return None
    current_actor = engine.state.actors[engine.state.current_actor_id]
    turn = f"{engine.state.round_number}:{engine.state.current_slot_index}:{current_actor.entity_id}:{current_actor.turns_started}"
    if actor.turn_flags.get(EXPLOIT_TURN) == turn or (EXPLOIT_TURN not in actor.turn_flags and actor.turn_flags.get("exploit_weakness_used")):
        return None
    source = str(context["source_id"])
    action = engine.action_catalog.get(source)
    action_name = action.display_name if action else "weapon attack"
    picked = ask(engine, intent, checkpoint_id(engine, "EYE_EXPLOIT", actor.entity_id, target.entity_id, context["attack_index"]), actor,
                 EXPLOIT_CHOICE, ["exploit"], labels={"exploit": "Make this attack as Exploit Weakness"},
                 minimum=0, maximum=1, allow_decline=True, preferred=["exploit"],
                 name="Exploit Weakness", feature_id=EXPLOIT_WEAKNESS,
                 prompt=f"Exploit Weakness: make {actor.display_name}'s {action_name} against {target.display_name} a special attack?",
                 target_id=target.entity_id, prompt_context=action_context(engine, actor, source, target))
    if not picked:
        return None
    actor.turn_flags[EXPLOIT_TURN] = turn
    actor.turn_flags["exploit_weakness_used"] = 1
    frame["eye_exploit"] = True
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                         payload={"attack_index": context["attack_index"], "trigger": "Exploit Weakness declared",
                                  "log": f"{actor.display_name} declares Exploit Weakness for {action_name} against {target.display_name}; once-per-turn use spent, no additional cost."})
    return {}


@hook("attack_roll_finished")
def exploit_finished(ctx: Any, target: Any, effect: dict[str, Any], roll_id: str) -> None:
    """Bind consent to this strike only, including nested attack and reaction scopes."""
    if not has(ctx.engine, ctx.actor.entity_id, "exploit_weakness"):
        return
    from .attack_scope import current

    frame = current(ctx.engine)
    ctx.damage_cache["eye_exploit"] = (roll_id, target.entity_id, bool(frame and frame.get("eye_exploit")))


@hook("decision_text")
def exploit_reading(engine: Any, context: dict, printed_rules: dict) -> dict | None:
    if context.get("reaction_source_id") != EXPLOIT_CHOICE or not has(engine, context.get("reactor_id"), "exploit_weakness"):
        return None
    return {"feature_id": EXPLOIT_WEAKNESS,
            "summary": "Declare this weapon attack as Exploit Weakness before rolling. On a hit, the enemy makes a Constitution save against your Cultivation Save DC; on failure it takes an extra 1d10 of the weapon's damage type.",
            "cost": "No additional action, Reaction or resource cost; uses your once-per-turn special attack even if it misses.",
            "limits": "Once per turn against a creature Analyzed by you. Decline to keep the opportunity for a later attack this turn.",
            "option_descriptions": {"exploit": "Use this turn's Exploit Weakness opportunity on this attack. Normal damage and effects still apply; the extra damage requires a hit and a failed Constitution save."}}


@hook("after_hit")
def exploit_weakness(ctx: Any, target: Any, kind: str) -> None:
    """Only a declared special attack's hit gets the Constitution save and bonus damage."""
    engine, actor = ctx.engine, ctx.actor
    if kind != "weapon" or not target.active or not has(engine, actor.entity_id, "exploit_weakness"):
        return
    declared = ctx.damage_cache.get("eye_exploit")
    if not declared or not declared[0] or declared[:2] != ((ctx.attack_result or {}).get("roll_id"), target.entity_id) or not declared[2]:
        return
    dc = int(ctx.numbers.get("save_dc") or 10)
    source = f"{ctx.source}.exploit_weakness"
    roll = engine._roll_save(target, "CON", dc, source)
    if roll.total < dc:
        weapon = ctx.typed.get("weapon") or {}
        damage_type = str(weapon.get("damage_type") or "UNTYPED")
        from ..gate2_runtime_models import DiceSpec
        from ..typed_executor import _roll

        amount = _roll(ctx, DiceSpec(count=1, sides=10, modifier=0), "DAMAGE")
        engine._commit_damage(target, amount, damage_type, f"{ctx.source}.exploit_weakness", actor.entity_id, ctx.intent, reaction_depth=0)
        ctx.rider(f"Exploit Weakness: {target.display_name} failed its Constitution save (DC {dc}), +{amount} {damage_type.lower()} damage.")
    else:
        ctx.rider(f"Exploit Weakness: {target.display_name} made its Constitution save (DC {dc}), no additional damage.")
