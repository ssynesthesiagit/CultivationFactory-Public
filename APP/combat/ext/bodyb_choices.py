"""Flowing River Response talents that say "choose one" AFTER their own trigger resolves (bodyb 2026-09-29, wave-2
follow-up: Athletics/Music/Flowing River/Smoke spheres for the characters the first body worker did not reach).

Return the Grip (CL7+, on a failed Grapple/Shove save) and Turn the Foot (on a failed save) each read "Failed Save:
choose one: ...". Each is modeled the same way Crawling Fever's own choose-one result is (combat/ext/disease_court.py):
a free player toggle kept until changed ("<Talent>: <choice>"), defaulting to its first listed option for the
built-in AI, with an "Off"-equivalent not needed since these always fire once their own save fails -- there is
nothing to turn off, only which branch to take.

(Soft Body, Hard Floor's own "choose one" -- whenever a creature within reach fails a save against ANY Response
talent -- could not use this same shape: its printed trigger needs the "any_save" modifier scope, which only scans
the compiled ACTION catalog, not Flowing Response's own REACTION where every Response talent's save actually lives;
left a GM-only rider instead, see reviewed_final.d/bodyb.json.)

The generic named modifier-attachment system (combat/factory_compiler.py's _attach_reaction_modifiers) inserts one
placeholder effect ({"type": "bodyb_response_choice", "group": <key>}) into Flowing Response's own effects, in the
on_fail branch of the save Return the Grip/Turn the Foot itself added; the placeholder runs the chosen branch's real
effects against the same target the failed save already picked out.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

RETURN_THE_GRIP = "TAL_FLOWING_RIVER_RETURN_THE_GRIP"
TURN_THE_FOOT = "TAL_FLOWING_RIVER_TURN_THE_FOOT"

GROUPS: dict[str, dict[str, Any]] = {
    "return_the_grip": {
        "mechanic": RETURN_THE_GRIP, "label": "Return the Grip", "condition": "condition:typed.return_the_grip_choice",
        "options": [
            ("push", "Push 10 feet", [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10,
                                       "evidence": "the creature is pushed 10 feet away from you"}]),
            ("prone", "Knock Prone", [{"type": "condition", "applies_to": "target", "condition": "prone",
                                      "evidence": "the creature falls Prone"}]),
            ("grapple", "Grapple", [{"type": "condition", "applies_to": "target", "condition": "grappled", "expires_on": "START_OF_SELF_NEXT_TURN",
                                     "evidence": "the creature gains the Grappled condition until the start of your next turn, if you have a free hand or another eligible grappling body part"}]),
        ],
    },
    "turn_the_foot": {
        "mechanic": TURN_THE_FOOT, "label": "Turn the Foot", "condition": "condition:typed.turn_the_foot_choice",
        "options": [
            ("slow", "Speed -10 feet", [{"type": "speed", "applies_to": "target", "flat": -10, "expires_on": "START_OF_SELF_NEXT_TURN",
                                        "evidence": "the creature's Speed is reduced by 10 feet until the start of its next turn"}]),
            ("oa", "Disadvantage on its next Opportunity Attack", [{"type": "disadvantage", "applies_to": "target", "on": "the next Opportunity Attack it makes",
                                                                    "expires_on": "START_OF_SELF_NEXT_TURN",
                                                                    "evidence": "the creature has Disadvantage on the next Opportunity Attack it makes before the start of its next turn"}]),
            ("prone", "Prone (if it moved 10+ feet)", [{"type": "condition", "applies_to": "target", "condition": "prone",
                                                        "evidence": "the creature falls Prone if it moved at least 10 feet immediately before triggering Flowing Response (not separately checked here)"}]),
        ],
    },
}


@hook("compile_actions")
def choice_actions(info: dict[str, Any]) -> list[Any] | None:
    out = []
    for key, group in GROUPS.items():
        if group["mechanic"] not in info["owned_ids"]:
            continue
        from ..gate2_runtime_models import ActionDefinition, EconomyKind

        for option_key, label, _effects in group["options"]:
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.{key}.{option_key}", display_name=f"{group['label']}: {label}",
                owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "typed": {"effects": [{"type": "bodyb_choice_pick", "group": key, "choice": option_key}],
                                      "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                            "expected_damage": 0, "player_only": True}))
    return out or None


@effect("bodyb_choice_pick")
def choice_pick(ctx: Any, eff: dict[str, Any]) -> None:
    group = GROUPS.get(str(eff.get("group")))
    if group is None:
        return
    choice = str(eff.get("choice"))
    label = next((label for key, label, _ in group["options"] if key == choice), choice)
    ctx.engine._remove_condition(ctx.actor, group["condition"], ctx.source)
    ctx.engine._apply_condition(ctx.actor, group["condition"], ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": choice, "label": f"{group['label']}: {label}"})


@effect("bodyb_response_choice")
def response_choice(ctx: Any, eff: dict[str, Any]) -> None:
    """Runs the chosen branch's effects against the same target/actor the failed save already picked (block_save
    builds a fresh Context per subject and calls run_effects(inner, fail_effects) -- this effect is one of those
    fail_effects, so ``ctx`` already has the right actor/target for the chosen branch to run against)."""
    group = GROUPS.get(str(eff.get("group")))
    if group is None or ctx.target is None or not ctx.target.active:
        return
    chosen = next((c.data.get("choice") for c in ctx.actor.conditions.values() if c.condition_id == group["condition"]), None)
    branch = next((effects for key, _label, effects in group["options"] if key == chosen), group["options"][0][2])
    from ..typed_executor import run_effects

    run_effects(ctx, branch)


# ------------------------------------------------------------------------------------------------------- Turning Guard
TURNING_GUARD = "TAL_FLOWING_RIVER_TURNING_GUARD"


def _has_turning_guard(engine: Any, actor: Any) -> bool:
    return any((row.get("block") == "flowing_river" and row.get("kind") == "turning_guard")
               or (row.get("block") == "rider_named_dodge" and row.get("feature_id") == TURNING_GUARD)
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


@hook("attack_resolved")
def turning_guard(ctx: Any, target: Any, hit: bool, attack: dict[str, Any]) -> None:
    """"When you take the Dodge Action, choose one creature you can see. Until the start of your next turn, when
    that creature misses you with a melee attack, you may move 5 feet without provoking Opportunity Attacks from
    it." Approximated (see reviewed_final.d/bodyb.json's rider): any qualifying melee miss while Dodging, once a
    turn, rather than tracking which single creature was named at Dodge-time."""
    engine, attacker = ctx.engine, ctx.actor
    melee = not (ctx.typed.get("range_ft") is not None and int(ctx.typed.get("range_ft") or 0) > 5)
    if hit or not melee or not target.active or attacker.team_id == target.team_id or not _has_turning_guard(engine, target):
        return
    if not any(c.condition_id == "condition:core.dodge" for c in target.conditions.values()):
        return
    from .river_riders import named_guard

    named, chosen = named_guard(engine, target)
    if named and chosen != attacker.entity_id:
        return
    flag = "bodyb_turning_guard_round_"
    turn_key = engine.state.round_number * 1000 + engine.state.current_slot_index
    if not named and target.turn_flags.get(flag) == turn_key:
        return
    target.turn_flags[flag] = turn_key
    from ..typed_executor import Context, run_effects

    inner = Context(engine, target, ctx.action, ctx.intent, ctx.typed, [attacker], attacker, ctx.damage_cache)
    run_effects(inner, [{"type": "reaction_move", "distance_ft": 5, "direction": "away",
                         "evidence": "you may move 5 feet without provoking Opportunity Attacks from it"}])
