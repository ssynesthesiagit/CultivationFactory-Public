"""Samsara Wheel Cultivator, "Echoes of Former Lives" (Qi subpath, CL3; owner 2026-09-29: "i want everything we can automated").

Source: LocalSources/03_paths/Qi/Tianxia_Qi_Cultivation_Subpath_Compendium_R19.md, "### CL3 -- Echoes of Former Lives" and
"### Former-Life Mantles".  The rules text, as the table runs it:

    "Choose three Former-Life Mantles from the list below."                  a choose-N menu of the eight (combat/ext/menus.py):
        character preparation records the three known Mantles (first three if no selection was recorded).
        Combat cannot replace them: replacement requires a long rest or Full Cultivation Session and meditation.
    "At the start of each scene, choose one known Mantle to become active."  a fight is a scene: the native initiative/setup
        checkpoint asks manual owners before round one; AI chooses its first known Mantle. The choice is free and does not
        grant Arrival benefits (those follow switching). Old saves without setup tasks retain their turn-start fallback.
    "Turn the Memory -- Bonus Action, Cost 1 Qi: Switch to another known Mantle.  After switching, gain that Mantle's Arrival
        benefit.  A Mantle remains active until changed."                    one action "Turn the Memory: <Mantle>" for each Mantle,
        legal only for a known one that is not the active one (``candidate_allowed``).  Player-only: the built-in AI keeps the
        Mantle it began with, as it does every free choice.

The active Mantle is one condition on the fighter ("condition:typed.mantle"; ``data.mantles`` lists the active ones, so a feature
that makes them all active at once -- Ten Thousand Lives Domain -- needs no second mechanism).  What each Mantle does while
active is read from the table below, where the engine can run it, and said as a plain log line where it cannot:

    Warrior of a Fallen Age      once per turn a weapon hit adds Proficiency Bonus damage (of the weapon's type)      -- automated
    Wandering Sword-Saint        Speed +10 ft; Opportunity Attacks against you have Disadvantage; after a weapon hit,
                                 once per turn, move 5 ft without provoking                                          -- automated
    Road-Born Wanderer           ignores nonmagical difficult terrain (the rule row ``ignore_difficult``)              -- automated
    Court Diplomat               Advantage on saving throws against Charmed                                           -- automated
    Arrival benefits             Sword-Saint: move 10 ft without provoking; Road-Born: stand from Prone and move 5 ft
                                 without provoking; Battlefield Physician: Temporary Hit Points equal to Proficiency Bonus to
                                 one creature within reach (the action asks for that creature)                        -- automated
    everything else              skills and tools, Cultivation Check dice, Analyze Qi, healing riders, Climb/Swim Speed, repairs,
                                 spirit sensing, one healing roll +PB, "+2 AC for an Asset" -- a GM line, said when the Mantle
                                 becomes active (the table has no skill checks or objects to run them on)
"""

from __future__ import annotations

import re
from typing import Any

from . import effect, hook, menus

FEATURE = "tianxia.subpath.qi.samsara_wheel_cultivator.feature.echoes_of_former_lives"
BLOCK = "samsara_mantles"
MENU_ID = "former_life_mantles"
ACTIVE = "condition:typed.mantle"
QI = "resource:core.qi"

# name -> {"arrival": typed effects, "speed": feet, "rule": condition rule row, "gm_arrival": text, "gm_while": [text]}
MANTLES: dict[str, dict[str, Any]] = {
    "Warrior of a Fallen Age": {
        "gm_while": ["Proficiency with one weapon group chosen when this Mantle becomes active."],
        "gm_arrival": "Draw, stow, or call one weapon or Domain Armament without using an action.",
    },
    "Wandering Sword-Saint": {
        "speed": 10,
        "arrival": [{"type": "movement", "applies_to": "self", "distance_ft": 10, "no_opportunity_attacks": True,
                     "evidence": "Arrival: Move 10 feet without provoking Opportunity Attacks."}],
    },
    "Forgotten Scholar": {
        "gm_while": ["Proficiency in one Intelligence- or Wisdom-based skill chosen when activated (+2 to checks using it if already proficient).",
                     "Once per turn, add 1d4 to one Cultivation Check or knowledge check after rolling."],
        "gm_arrival": "Analyze one visible active cultivation effect as though using Analyze Qi without spending an Action.",
    },
    "Battlefield Physician": {
        "arrival": [{"type": "temp_hp", "applies_to": "ally", "flat": 0, "formula": "pb",
                     "evidence": "Arrival: One creature within reach gains Temporary Hit Points equal to your Proficiency Bonus."}],
        "reach": True,
        "gm_while": ["Once per turn, increase one healing roll by your Proficiency Bonus.",
                     "Proficiency in Medicine, or +2 if already proficient.",
                     "Stabilizing a creature requires no Action once per turn when within reach."],
    },
    "Road-Born Wanderer": {
        "rule": {"ignore_difficult": True},
        "arrival": [{"type": "stand", "applies_to": "self"},
                    {"type": "movement", "applies_to": "self", "distance_ft": 5, "no_opportunity_attacks": True,
                     "evidence": "Arrival: Stand from Prone and move 5 feet without provoking Opportunity Attacks."}],
        "gm_while": ["A Climb Speed and a Swim Speed equal to your walking Speed.", "Advantage on navigation and environmental Survival checks."],
    },
    "Court Diplomat": {
        "gm_while": ["Proficiency in Insight or Persuasion, chosen when activated (+2 if already proficient).",
                     "Once per round, when a creature within 30 feet succeeds on a social, command, oath, or emotion-based saving throw, "
                     "it gains Temporary Hit Points equal to your Proficiency Bonus."],
        "gm_arrival": "One willing creature within 30 feet immediately repeats a saving throw against Charmed or Frightened with Advantage.",
    },
    "Formation Artisan": {
        "gm_while": ["Proficiency with one tool or cultivation craft.",
                     "+2 AC for one Cultivation Asset, Anchor, or Domain Armament you control.",
                     "Once per turn, move one controlled Cultivation Asset or Domain Armament 10 feet."],
        "gm_arrival": "Repair one object, Construct, Anchor, or Cultivation Asset within reach for Hit Points equal to twice your Proficiency Bonus.",
    },
    "Spirit Medium of a Previous Life": {
        "gm_while": ["Qi Sensing detects active spirits, possession tethers, and soul traces at twice its normal range.",
                     "Advantage on Cultivation Checks involving spirits, souls, possession, or reincarnation.",
                     "You may communicate simple ideas with a spirit that does not share a language when it is willing."],
        "gm_arrival": "Reveal the direction of the nearest active spirit or soul disturbance within 300 feet.",
    },
}

MENU_ROW = {"type": "menu", "id": MENU_ID, "name": "Former-Life Mantles", "label": "Choose three Former-Life Mantles", "count": 3,
            "options": list(MANTLES), "default": list(MANTLES)[:3], "cast_only": True}

# Scene-start labels distinguish automated benefits from GM-applied ones, never Arrival.
START_SUMMARIES = {
    "Warrior of a Fallen Age": "Once per turn, a weapon hit adds your Proficiency Bonus to damage",
    "Wandering Sword-Saint": "Speed +10 feet; Opportunity Attacks against you have Disadvantage; once per turn after a weapon hit, move 5 feet without provoking",
    "Road-Born Wanderer": "Ignore nonmagical difficult terrain",
    "Court Diplomat": "Advantage on saves against Charmed",
}


def _starting_gm_benefits(name: str) -> str:
    """Use the existing GM-only rules in both setup options and committed notices."""
    return " ".join(MANTLES[name].get("gm_while") or []).replace(
        "Cultivation Checks", "checks about cultivation").replace(
        "Cultivation Check", "check about cultivation").replace(
        "Cultivation Asset, Anchor, or Domain Armament", "cultivation object, anchor, or summoned weapon").replace(
        "Cultivation Asset or Domain Armament", "cultivation object or summoned weapon").replace(
        "Qi Sensing", "Your ability to sense Qi (cultivation energy)")


def _starting_description(name: str) -> str:
    automated = START_SUMMARIES.get(name)
    gm = _starting_gm_benefits(name)
    return " ".join(part for part in (
        f"Automated: {automated}." if automated else "",
        f"GM applies (not automated): {gm}" if gm else "",
    ) if part)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _has_feature(engine: Any, actor: Any) -> bool:
    return any(row.get("block") == BLOCK for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


def active(actor: Any) -> list[str]:
    """The Mantles active on the fighter now (one, or every known one under Ten Thousand Lives Domain)."""
    for condition in actor.conditions.values():
        if condition.condition_id == ACTIVE:
            return list((condition.data or {}).get("mantles") or [])
    return []


def known(engine: Any, actor: Any) -> list[str]:
    return menus.picks(engine, actor, MENU_ID)


def _rule(names: list[str]) -> dict[str, Any]:
    rule: dict[str, Any] = {}
    for name in names:
        rule.update(MANTLES[name].get("rule") or {})
    return rule


def _set_active(engine: Any, actor: Any, names: list[str], source: str) -> None:
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id == ACTIVE:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid})
    engine._apply_condition(actor, ACTIVE, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"mantles": list(names), "rule": _rule(names), "label": f"Former-Life Mantle: {'; '.join(names)}"})


# ------------------------------------------------------------------------------------------------ compile


@hook("compile_block")
def mantle_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind")}]


@hook("compile_actions")
def mantle_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if FEATURE not in info["owned_ids"]:
        return None
    out = menus.toggle_actions(info, MENU_ROW, carry=True)
    for action in out:
        action.parameters['description'] = (
            'Known Former-Life Mantles are fixed during this scene. After a long rest or Full Cultivation Session, '
            'meditate on a relevant memory, relic, dream or historical trace to replace one known Mantle.')
    for name, mantle in MANTLES.items():
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.mantle.{_slug(name)}", display_name=f"Turn the Memory: {name}",
            owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED",
            target_kind="ALLY_OR_SELF" if mantle.get("reach") else "SELF", range_ft=5 if mantle.get("reach") else None, costs=((QI, 1),),
            parameters={"typed": {"effects": [{"type": "mantle_switch", "mantle": name}], "numbers": info["numbers"],
                                  "duration": {"kind": "instant"}, "riders": []},
                        "expected_damage": 0, "player_only": True, "mantle": name,
                        "description": f"Switch to the {name} Mantle (Bonus Action, 1 Qi) and gain its Arrival benefit: "
                                       f"it stays active until you change it. Only a Mantle you know, other than the active one."}))
    return out


@hook("candidate_allowed")
def turn_the_memory_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    # Retain the catalog/menu row for old saves and known() defaults, but never
    # offer the old free learning toggles as combat actions. Rest-bound learning
    # belongs to character preparation, not scene activation or paid switching.
    if (getattr(action, "parameters", None) or {}).get("menu_toggle") == MENU_ID:
        return False
    name = (getattr(action, "parameters", None) or {}).get("mantle")
    if not name:
        return None
    return name in known(engine, actor) and name not in active(actor)


# ------------------------------------------------------------------------------------------------ switching


@effect("mantle_switch")
def run_switch(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te

    name = str(eff.get("mantle"))
    mantle = MANTLES.get(name)
    if mantle is None:
        return
    before = speed(ctx.engine, ctx.actor)
    _set_active(ctx.engine, ctx.actor, [name], ctx.source)
    change = speed(ctx.engine, ctx.actor) - before
    if change:  # a Speed gained or lost in mid-turn moves the movement left this turn by as much (as Encumbered does)
        ctx.actor.movement_remaining_ft = max(0, int(ctx.actor.movement_remaining_ft) + change)
        ctx.engine._append_event("MOVEMENT_GRANTED", ctx.source, actor_id=ctx.actor.entity_id, payload={"distance_ft": change})
    ctx.rider(f"Former-Life Mantle: {name} is now active.")
    if mantle.get("arrival"):
        te.run_effects(ctx, [dict(row) for row in mantle["arrival"]])
    if mantle.get("gm_arrival"):
        ctx.rider(f"{name}, Arrival: {mantle['gm_arrival']}")
    for text in mantle.get("gm_while") or []:
        ctx.rider(f"{name}, while active: {text}")


@effect("stand")
def run_stand(ctx: Any, eff: dict[str, Any]) -> None:
    """"Stand from Prone" for free (Road-Born Wanderer's Arrival): the Prone condition ends."""
    for iid, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == "condition:typed.prone":
            del ctx.actor.conditions[iid]
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid})


@hook("fight_setup_tasks")
def initial_mantle_tasks(engine: Any) -> list[dict[str, str]]:
    """Pure discovery for new scenes; loading an old save never backfills tasks."""
    return [{"actor_id": actor.entity_id, "source_id": FEATURE} for actor in engine.state.actors.values()
            if actor.active and _has_feature(engine, actor) and not active(actor) and known(engine, actor)]


@hook("fight_setup")
def choose_initial_mantle(engine: Any, actor: Any, source_id: str, intent: Any) -> bool | None:
    """Free scene-start selection, atomically recorded before round/turn one."""
    if source_id != FEATURE or not _has_feature(engine, actor):
        return None
    from ..choice_checkpoints import dynamic_choice

    options = known(engine, actor)
    if not options:
        raise ValueError("Former-Life Mantle setup requires a known Mantle")
    _, answer = dynamic_choice(engine, intent, f"INITIAL_MANTLE:{actor.entity_id}", actor.entity_id, FEATURE,
                              {"name": "Former-Life Mantle", "feature_id": FEATURE,
                               "actor_id": actor.entity_id, "target_id": actor.entity_id, "affected_id": actor.entity_id,
                               "action_name": "Fight setup", "cost": "None",
                               "prompt": f"{actor.display_name}: choose one known Former-Life Mantle before the first turn. "
                                         "It stays active until you switch it. This choice costs no Action, Reaction or Qi "
                                         "and activates the Mantle for you. Benefits labelled 'GM applies' are not automated; "
                                         "ask the GM to apply them while this Mantle is active. The immediate benefits from switching Mantles "
                                         "(Arrival) do not apply to this starting choice.",
                               "labels": {name: f"{name}: {_starting_description(name)}" for name in options}},
                              spec_override={"option_ids": tuple(options), "allow_decline": False,
                                             "automatic_use": True, "preferred_option_ids": (options[0],)})
    # Direct engine callers have no controller; use the same deterministic AI
    # default. Persistent table transactions always install a choice provider.
    chosen = list(answer.option_ids) if answer is not None else options[:1]
    _set_active(engine, actor, chosen, f"passive:{FEATURE}")
    for name in chosen:
        gm = _starting_gm_benefits(name)
        if gm:
            engine._append_event("GM_RIDER", f"passive:{FEATURE}", actor_id=actor.entity_id,
                                 target_ids=(actor.entity_id,),
                                 payload={"adjudication_text": True,
                                          "rider": f"Former-Life Mantle: {name} for {actor.display_name}. "
                                          f"Until you switch Mantles, the GM applies these benefits (not automated): {gm}"})
    return True


@hook("turn_start")
def start_of_scene(engine: Any, actor: Any) -> None:
    """Legacy saves without setup tasks retain their original first-turn default."""
    if getattr(engine.state, "setup_tasks", ()) or not actor.active or active(actor) or not _has_feature(engine, actor):
        return
    chosen = known(engine, actor)
    if chosen:
        _set_active(engine, actor, chosen[:1], f"passive:{FEATURE}")


# ------------------------------------------------------------------------------------------------ while active


@hook("speed")
def speed(engine: Any, actor: Any) -> int:
    return sum(int(MANTLES[name].get("speed") or 0) for name in active(actor) if name in MANTLES)


@hook("attack_mode")
def opportunity_attacks_against_the_saint(ctx: Any, target: Any) -> str | None:
    """Wandering Sword-Saint: "Opportunity Attacks against you have Disadvantage." """
    if getattr(ctx.engine, "_typed_oa_attacker", None) == ctx.actor.entity_id and "Wandering Sword-Saint" in active(target):
        return "DISADVANTAGE"
    return None


@hook("save")
def court_diplomat(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Court Diplomat: "Gain Advantage on saving throws against Charmed." """
    if "Court Diplomat" in active(subject) and "charmed" in {str(value).lower() for value in named or ()}:
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("after_hit")
def after_a_weapon_hit(ctx: Any, target: Any, kind: str) -> None:
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    names = active(actor)
    if kind != "weapon" or not names or not target.active or target.team_id == actor.team_id:
        return
    sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    if "Warrior of a Fallen Age" in names and not actor.turn_flags.get("mantle_warrior"):
        actor.turn_flags["mantle_warrior"] = True  # "Once per turn, one weapon attack ... deals additional damage equal to your Proficiency Bonus."
        kinds = [str(kind_).lower() for kind_ in te.damage_choices({}, ctx.typed.get("weapon") or {})]
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": 0, "formula": "pb", "damage_types": kinds,
                              "evidence": "Warrior of a Fallen Age: additional damage equal to your Proficiency Bonus"}])
    if "Wandering Sword-Saint" in names and not actor.turn_flags.get("mantle_saint") and actor.active:
        actor.turn_flags["mantle_saint"] = True  # "Once per turn after hitting with a weapon ..., move 5 feet without provoking Opportunity Attacks."
        te.run_effects(sub, [{"type": "movement", "applies_to": "self", "distance_ft": 5, "no_opportunity_attacks": True,
                              "evidence": "Wandering Sword-Saint: move 5 feet without provoking Opportunity Attacks"}])
