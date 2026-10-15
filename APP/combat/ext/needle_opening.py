"""The One Opening Beneath Heaven (rider lane 10, 2026-09-29; the Piercing Needle's CL 17 inheritance). Rules text: the owner's Sphere
Compendium, "The Piercing Needle" (authority/typed_mechanics/rules_text.json and the compendium's Creature / Object / Miss sections).

  "Cost: Expend Martial Focus. Use Limit: Once per week. Move up to your Speed without provoking Opportunity Attacks. End this movement
   with one creature ... within the reach of a melee attack you can make. Make one melee attack against the target with Advantage. ...
   This attack does not receive a Weapon Mastery property. If it hits, resolve its normal damage and then apply the appropriate effect
   below."
  Creature: "The target takes additional damage equal to twelve rolls of the attack's normal damage die. This additional damage uses one
   damage type normally dealt by the attack ... Then choose three consequences" (no Reactions / Speed 0 / Disadvantage on attack rolls /
   loses Resistance to Bludgeoning, Piercing, and Slashing -- each until the end of your next turn -- / end one Stance, Guard, Domain ...
   subject to GM approval / apply one Exploit ... / move the target up to 20 feet along the ground if it is Huge or smaller).
  Miss: "you complete the movement but deal no damage and apply no consequences."

Each melee weapon attack of its owner gets a variant (the ``maneuvers`` hook, like Vacuum Cut): "<weapon> attack: The One Opening Beneath
Heaven", offered against a creature within the user's Speed plus the weapon's reach, once per fight (a week is longer than any fight),
while Martial Focus is held. The ``needle_one_opening`` row moves the user toward the creature (square by square, provoking nothing), then
makes the attack if the creature is within reach. The owner chooses three consequences after a hit; standing menu values are AI preferences. The two
the GM approves or picks (a Stance ending, an Exploit) print as GM lines when picked. The object branch stays the GM's: the variant is
aimed at creatures.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from .needle import FOCUS
from .weapon_profiles import melee_weapon_attack

OPENING = "TAL_FENCING_THE_ONE_OPENING_BENEATH_HEAVEN"
MENU = "needle_one_opening"
USED = "_round_needle_one_opening"  # a "_round_" flag lasts the fight


MENU_ROW = {"type": "menu", "id": MENU, "name": "The One Opening Beneath Heaven", "label": "Choose three consequences", "count": 3, "cast_only": True,
            "options": ["No Reactions", "Speed 0", "Disadvantage on attack rolls", "Lose weapon Resistance", "End a Stance or Guard",
                        "Apply an Exploit", "Move 20 feet"],
            "default": ["No Reactions", "Speed 0", "Disadvantage on attack rolls"],
            "gm": {"End a Stance or Guard": "end one Stance, Guard, Domain, or comparable temporary martial effect affecting the target, subject to GM approval.",
                   "Apply an Exploit": "apply one Exploit talent you know that can legally affect the target without expending Martial Focus or "
                                       "counting against your Exploit limit (the GM applies it)."}}


def _mastery_row(row: dict[str, Any]) -> bool:
    """A Weapon Mastery property's on-hit row (factory_compiler._mastery_effects)."""
    kind = row.get("type")
    return kind in ("cleave", "vex") or (kind == "forced_movement" and row.get("max_size_cells") == 2 and row.get("distance_ft") == 10) or \
        (kind == "disadvantage" and row.get("on") == "its next attack roll") or (kind == "speed" and row.get("amount") == -10) or \
        (kind == "save" and str(row.get("ability")).upper() == "CON" and
         any(r.get("condition") == "prone" for r in row.get("on_fail") or []))


def _consequences() -> list[dict[str, Any]]:
    until = {"duration": {"kind": "until_end_of_your_next_turn"}}
    tag = lambda option, row: {**row, "menu": MENU, "option": option}  # noqa: E731
    return [
        tag("No Reactions", {"type": "reaction_denied", "applies_to": "target", **until, "evidence": "the target cannot take Reactions until the end of your next turn"}),
        tag("Speed 0", {"type": "speed", "applies_to": "target", "becomes": 0, **until, "evidence": "each of the target's Speeds becomes 0 until the end of your next turn"}),
        tag("Disadvantage on attack rolls", {"type": "disadvantage", "applies_to": "target", "on": "attack rolls", **until,
                                             "evidence": "the target has Disadvantage on attack rolls until the end of your next turn"}),
        tag("Lose weapon Resistance", {"type": "suppress_resistance", "applies_to": "target", "damage_types": ["bludgeoning", "piercing", "slashing"], **until,
                                       "evidence": "the target loses Resistance to Bludgeoning, Piercing, and Slashing damage until the end of your next turn"}),
        tag("Move 20 feet", {"type": "forced_movement", "applies_to": "target", "distance_ft": 20, "direction": "away", "max_size_cells": 3,
                             "evidence": "move the target up to 20 feet along the ground if it is Huge or smaller"}),
    ]


@hook("maneuvers")
def one_opening(info: dict[str, Any]) -> dict[str, Any] | None:
    if OPENING not in set(info.get("owned") or ()):
        return None
    made = []
    for action in info.get("actions") or ():
        if not melee_weapon_attack(action):
            continue
        parameters = copy.deepcopy(action.parameters)
        typed = parameters["typed"]
        attack = next(e for e in typed["effects"] if isinstance(e, dict) and e.get("type") == "attack")
        weapon = typed.get("weapon") or {}
        sides = int((weapon.get("damage") or {}).get("sides") or 1)  # "no normal damage die: treat it as d1"
        kind = str(weapon.get("damage_type") or "piercing").lower()
        extra = {"type": "damage", "applies_to": "target", "dice": {"count": 12, "sides": max(1, sides)}, "damage_types": [kind],
                 "evidence": "The target takes additional damage equal to twelve rolls of the attack's normal damage die."}
        strike = {**attack, "count": 1, "on_miss": [],
                  "on_hit": [*[r for r in attack.get("on_hit") or [] if not _mastery_row(r)], extra,
                             {"type": "needle_opening_consequences"}]}
        strike.pop("count_by_cl", None)
        typed["effects"] = [copy.deepcopy(MENU_ROW), {"type": "spend_resource", "resource_id": FOCUS, "flat": 1, "applies_to": "self"},
                            {"type": "needle_one_opening", "attack": strike}]
        typed.update({"option_of": action.source_definition_id, "option_label": "The One Opening Beneath Heaven", "needle_one_opening": True})
        parameters.update({"requires_resource": {FOCUS: 1}, "needle_one_opening": True, "normal_reach_ft": int(action.range_ft or 5)})
        made.append(type(action)(source_definition_id=f"{action.source_definition_id}#one_opening", display_name=f"{action.display_name}: The One Opening Beneath Heaven",
                                 owner_id=action.owner_id, economy=action.economy, resolution_kind=action.resolution_kind,
                                 target_kind=action.target_kind, range_ft=120, parameters=parameters))
    return {"actions": made} if made else None


@hook("candidate_allowed")
def opening_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = getattr(action, "parameters", None) or {}
    if not parameters.get("needle_one_opening"):
        return None
    if actor.turn_flags.get(USED) or int(actor.resources.get(FOCUS, 0)) < 1:
        return False
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    reach = int(parameters.get("normal_reach_ft") or 5) + int(engine._effective_speed(actor))
    return None if target is not None and engine._distance_actor_to_actor(actor, target) <= reach else False


@hook("attack_mode")
def opening_advantage(ctx: Any, target: Any) -> str | None:
    return "ADVANTAGE" if (ctx.typed or {}).get("needle_one_opening") else None


@effect("needle_one_opening")
def run_opening(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import block_reaction_move, run_effects

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    actor.turn_flags[USED] = True
    block_reaction_move(ctx, {"type": "reaction_move", "direction": "toward", "distance_ft": "speed"})
    reach = int((ctx.action.parameters or {}).get("normal_reach_ft") or 5)
    if not target.active or engine._distance_actor_to_actor(actor, target) > reach:
        ctx.rider(f"The One Opening Beneath Heaven: {actor.display_name} could not end its movement within reach of {target.display_name}.")
        return
    run_effects(ctx, [eff["attack"]])


@effect("needle_opening_consequences")
def choose_consequences(ctx: Any, eff: dict[str, Any]) -> None:
    """Choose three consequences after the inheritance hits, separately for this target."""
    from . import menus
    from .rider_choices import pick
    from ..typed_executor import run_effects
    target = ctx.target
    if target is None:
        return
    chosen = pick(ctx.engine, ctx.actor, MENU, "The One Opening Beneath Heaven", list(MENU_ROW["options"]),
                  subject=target, trigger=f"{ctx.action.display_name} hits {target.display_name}",
                  preferred=menus.picks(ctx.engine, ctx.actor, MENU) or list(MENU_ROW["default"]),
                  minimum=3, maximum=3, optional=False, intent=ctx.intent)
    rows = [{k: v for k, v in row.items() if k not in ("menu", "option")} for row in _consequences() if row["option"] in chosen]
    run_effects(ctx, rows)
    for option in chosen:
        if option in MENU_ROW["gm"]:
            ctx.rider(f"The One Opening Beneath Heaven: {target.display_name}: {MENU_ROW['gm'][option]}")
