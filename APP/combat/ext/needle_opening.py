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
while Martial Focus is held. The reviewed ``move_then_attack`` row offers native legal attack squares and commits the chosen route
without provoking; the normal attack follows from that square. The owner chooses three consequences after a hit; standing menu values are AI preferences. The two
the GM approves or picks (a Stance ending, an Exploit) print as GM lines when picked.

The object branch (needle-riders-1 2026-10-21) is a second variant, "<weapon> attack: The One Opening Beneath Heaven (at an object)", whose
candidates are map objects (the documented object_targets/object_action hooks). On a hit it resolves the weapon's normal damage and then
adds eighteen rolls of the attack's normal damage die (a d1 when the attack form has no damage die), ignoring the object's ordinary
Damage Threshold and ordinary Resistance to that damage type; Immunity still applies, and the consequences menu is for creatures only.
The eighteen rolls are additional damage from the inheritance, not the attack's own damage dice, so a Critical Hit does not double them.
"Fatal Thrust may apply normally" has nothing to apply: Fatal Thrust has no printed text in the catalog and no typed record.

Save compatibility: this replaced the legacy ``needle_one_opening`` effect with ``needle_opening_use`` plus the shared
``move_then_attack`` row, so the checkpoint id and prompt count of a new use differ from a use recorded before
CHARGEMOVE1. Fights saved by the older code do not replay under this one. That is accepted: the owner's ruling of
2026-10-10 is that old saved fights do not need to load. Fights saved after this change verify and replay (the One
Opening table tests cold-reload and replay them).
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from .needle import FOCUS
from .weapon_profiles import melee_weapon_attack

OPENING = "TAL_FENCING_THE_ONE_OPENING_BENEATH_HEAVEN"
MENU = "needle_one_opening"
OBJECT = "needle_one_opening_object"
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
        reviewed = ((info.get("mechanics") or {}).get(OPENING) or {}).get("effects") or []
        menu = next((row for row in reviewed if row.get("id") == MENU), {})
        movement = menu.get("movement")
        if movement is None:
            # The reviewed row is the movement's only source; without it the
            # variant has no activation geometry, so stay inert.
            return None
        movement = copy.deepcopy(movement)
        typed["effects"] = [copy.deepcopy(MENU_ROW), {"type": "spend_resource", "resource_id": FOCUS, "flat": 1, "applies_to": "self"},
                            {"type": "needle_opening_use"}, movement, strike]
        typed.update({"option_of": action.source_definition_id, "option_label": "The One Opening Beneath Heaven", "needle_one_opening": True})
        parameters.update({"requires_resource": {FOCUS: 1}, "needle_one_opening": True, "normal_reach_ft": int(action.range_ft or 5)})
        made.append(type(action)(source_definition_id=f"{action.source_definition_id}#one_opening", display_name=f"{action.display_name}: The One Opening Beneath Heaven",
                                 owner_id=action.owner_id, economy=action.economy, resolution_kind=action.resolution_kind,
                                 target_kind=action.target_kind, range_ft=action.range_ft, reach_ft=action.reach_ft, parameters=parameters))
        # The object branch: the same move and one melee attack, aimed at a map object; its own row resolves the object.
        parameters = copy.deepcopy(action.parameters)
        typed = parameters["typed"]
        # Focus is paid once, by object_action (after the reach test); a declared spend_resource row would never run.
        typed["effects"] = [{"type": OBJECT, "evidence": "The object takes the attack's normal damage and eighteen further rolls of its normal damage die."}]
        # The ordinary object attack's attack-kind key (objects.attack_group), so a group-keyed plug-in sees the same kind.
        from .objects import attack_group
        typed.update({"option_of": action.source_definition_id, "option_label": "The One Opening Beneath Heaven (at an object)",
                      "needle_one_opening_object": True,
                      "object_weapon_group": attack_group(action, action.parameters["typed"], attack)})
        parameters.update({"requires_resource": {FOCUS: 1}, "needle_one_opening_object": True,
                           "normal_reach_ft": int(action.range_ft or 5)})
        made.append(type(action)(source_definition_id=f"{action.source_definition_id}#one_opening_object",
                                 display_name=f"{action.display_name}: The One Opening Beneath Heaven (at an object)",
                                 owner_id=action.owner_id, economy=action.economy, resolution_kind=action.resolution_kind,
                                 target_kind="OBJECT", range_ft=120, parameters=parameters))
    return {"actions": made} if made else None


@hook("candidate_allowed")
def opening_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = getattr(action, "parameters", None) or {}
    object_aim = bool(parameters.get("needle_one_opening_object"))
    if not (parameters.get("needle_one_opening") or object_aim):
        return None
    if actor.turn_flags.get(USED) or int(actor.resources.get(FOCUS, 0)) < 1:
        return False
    if object_aim:
        return bool(getattr(candidate, "target_ids", None))
    return None  # move_attack proves native route, reach and line of effect.


@hook("object_targets")
def opening_object_targets(engine: Any, actor: Any, action: Any) -> list[str]:
    """Map objects the inheritance can reach this turn: Speed plus the attack's own reach, and the same once-per-fight/Focus gate."""
    from ..object_geometry import target_cells

    parameters = getattr(action, "parameters", None) or {}
    if not parameters.get("needle_one_opening_object") or actor.turn_flags.get(USED) or int(actor.resources.get(FOCUS, 0)) < 1:
        return []
    span = int(parameters.get("normal_reach_ft") or 5) + int(engine._effective_speed(actor))
    return [obj.object_id for obj in engine.state.objects.values()
            if not obj.destroyed and obj.ac is not None and obj.current_hp is not None
            and (cells := target_cells(engine, obj))
            and min(engine._distance_actor_to_cell(actor, cell) for cell in cells) <= span]


def object_damage_die(weapon: dict[str, Any]) -> Any:
    """The attack's normal damage die, or None when the attack form has none."""
    from ..gate2_runtime_models import DiceSpec

    return DiceSpec(**weapon["damage"]) if weapon.get("damage") else None


def object_extra_damage(engine: Any, actor: Any, die: Any, source: str) -> int:
    """Eighteen rolls of the normal damage die. With no damage die the printed rule treats it as d1, so the rolls are a flat 18."""
    from ..gate2_runtime_models import DiceSpec

    if die is None:
        return 18
    extra = engine.roller.roll(DiceSpec(count=18, sides=int(die.sides), modifier=0), actor_id=actor.entity_id,
                               reason=f"DAMAGE:{source}:object:1")
    engine._record_roll(extra)
    return int(extra.total)


@hook("object_action")
def opening_object_action(engine: Any, actor: Any, action: Any, obj: Any, candidate: Any, intent: Any) -> bool | None:
    """One melee attack at the object, with Advantage, after moving toward it: normal damage plus eighteen rolls of its damage die."""
    from ..gate2_runtime_models import DiceSpec
    from ..object_geometry import target_cells
    from ..typed_executor import Context, block_reaction_move
    from .. import object_rules
    from . import objects, run_strict
    from .needle import focus, say, spend_focus

    parameters = getattr(action, "parameters", None) or {}
    if not parameters.get("needle_one_opening_object"):
        return None
    typed = dict(parameters.get("typed") or {})
    ctx = Context(engine, actor, action, intent, typed, [], None)
    first = not actor.turn_flags.get(USED)
    if first and focus(actor) < 1:
        return True  # nothing moves and nothing is spent when the Focus is already gone
    # The inheritance's own movement is part of the Action, not a Reaction (feed label).
    block_reaction_move(ctx, {"type": "reaction_move", "direction": "toward", "distance_ft": "speed", "as_reaction": False,
                              "toward_position": obj.position.model_dump(mode="json")})
    reach = int(parameters.get("normal_reach_ft") or 5)
    cells = target_cells(engine, obj)
    if obj.destroyed or not cells or min(engine._distance_actor_to_cell(actor, cell) for cell in cells) > reach:
        # Reach is tested before anything is paid: no Focus, and the once-per-fight use stays available.
        say(engine, ctx.source, actor, f"The One Opening Beneath Heaven: {actor.display_name} could not end its movement "
                                      f"within reach of {object_rules.label(obj)}.")
        return True
    if first and not spend_focus(engine, actor, ctx.source, "The One Opening Beneath Heaven"):
        return True
    actor.turn_flags[USED] = True
    hit, natural = objects.attack_object_roll(ctx, obj, 0, modes={"ADVANTAGE"})
    if not hit:
        return True
    weapon = typed.get("weapon") or {}
    die = object_damage_die(weapon)
    normal_die = die or DiceSpec(count=1, sides=4, modifier=0)
    group = str(typed.get("object_weapon_group") or "weapon")  # the key objects._attack passes to both hooks
    bonus = objects.object_attack_damage_bonus(ctx, obj, group, normal_die)
    main = engine.roller.roll(normal_die.model_copy(update={"modifier": int(normal_die.modifier) + bonus}),
                              actor_id=actor.entity_id, reason=f"DAMAGE:{ctx.source}:object:1",
                              critical=natural == 20, fixed_damage=weapon.get("fixed_damage"))
    engine._record_roll(main)
    extra = object_extra_damage(engine, actor, die, OBJECT)
    kind = str(weapon.get("damage_type") or "BLUDGEONING").upper()
    objects.deal(engine, actor, obj, [(int(main.total), kind), (extra, kind)], ctx.source,
                 ignore_threshold=True, ignore_resistance=True)
    run_strict("object_hit", ctx, obj, group)
    return True


@effect(OBJECT)
def opening_object_effect(ctx: Any, eff: dict[str, Any]) -> None:
    """Never run through run_effects: an object aim is resolved by object_action (a creature aim gets nothing)."""
    ctx.rider("The One Opening Beneath Heaven at an object needs an object to aim at.")


@hook("attack_mode")
def opening_advantage(ctx: Any, target: Any) -> str | None:
    return "ADVANTAGE" if (ctx.typed or {}).get("needle_one_opening") else None


@effect("needle_opening_use")
def use_opening(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.actor.turn_flags[USED] = True


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
