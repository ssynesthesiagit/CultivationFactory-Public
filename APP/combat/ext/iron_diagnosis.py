"""Eight-Gate Diagnosis: ``iron_diagnosis`` action effect.

Choose any perceived creature within 30 feet without hostile-target gates.
Compile the three printed check bonuses from the sheet, choose one before a
single d20, then choose two information categories on success. Bloodied and
weakest physical save use actual actor state; resistance, condition immunity
and an ongoing bodily or martial enhancement are answered by the same readers
the engine itself resolves a defense or a condition with, and only for what
they can actually confirm. A question the fight record cannot answer -- nothing
on the fight is not nothing on the creature -- is told to the player as unknown
and raised as a GM line rather than guessed. The successful diagnosis grants one
target-specific Unarmed Strike Advantage, consumed by its roll (including a
miss), ending with the user's next turn. All state changes use existing evented
conditions and choice transport.
"""
from __future__ import annotations

import json
from typing import Any

from . import effect, hook
from .iron_fist_riders import choose, weakest_physical_saves

SOURCE = "TAL_IRON_FIST_EIGHT_GATE_DIAGNOSIS"
WINDOW = "condition:typed.iron_diagnosis."
FACTS = ["Bloodied", "Resistances", "Immunities", "Bodily or martial enhancement", "Weakest physical save"]


def is_diagnosis(action: Any) -> bool:
    if action is None:
        return False
    return any(row.get("type") == "iron_diagnosis"
               for row in (action.parameters.get("typed") or {}).get("effects") or [])


@hook("compile_actions")
def compile_diagnosis(info: dict[str, Any]) -> list[Any]:
    stats = info["owner_sheet"]["ability_scores_and_statistics"]
    skills = stats.get("skills") or []
    if isinstance(skills, str):
        skills = json.loads(skills)
    bonuses = {row["skill"]: int(row["bonus"]) for row in skills if isinstance(row, dict) and row.get("bonus") is not None}
    checks = {"Wisdom (Medicine)": bonuses.get("Medicine", info["mods"].get("WIS", 0)),
              "Intelligence (Investigation)": bonuses.get("Investigation", info["mods"].get("INT", 0)),
              "Cultivation Check": int(info["numbers"]["pb"]) + int(info["numbers"]["key_mod"])}
    for action in info["actions"]:
        if not is_diagnosis(action):
            continue
        action.parameters["diagnosis_checks"] = checks
        action.parameters["diagnosis_key_ability"] = str((info["owner_sheet"].get("identity") or {}).get("key_ability") or "INT").upper()[:3]
    return []


def perceives(engine: Any, actor: Any, target: Any) -> bool:
    from .. import senses, stealth
    from ..typed_executor import condition_rules

    if actor is target:
        return True
    if senses.perceives_without_sight(engine, actor, target) or senses.pinpoints(engine, actor, target):
        return True
    if any(row.get("cant_see") for row in condition_rules(actor)):
        return False
    hidden = any(c.condition_id in ("condition:typed.hidden", "condition:typed.invisible") for c in target.conditions.values())
    return senses.sees_hidden(engine, actor, target) if hidden else stealth.sees(engine, actor, target)


def subjects(engine: Any, actor: Any, distance: int) -> list[Any]:
    return [target for target in engine.state.actors.values() if target.active
            and engine._distance_actor_to_actor(actor, target) <= distance and perceives(engine, actor, target)]


PHYSICAL = ("BLUDGEONING", "PIERCING", "SLASHING")
DAMAGE_NAMES = {"BLUDGEONING": "Bludgeoning", "PIERCING": "Piercing", "SLASHING": "Slashing", "FORCE": "Force"}
CONDITION_NAMES = (("prone", "Prone"), ("grappled", "Grappled"), ("stunned", "Stunned"))


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def unknown_fact(ctx: Any, target: Any, question: str, subject: str) -> str:
    """The answer when the table holds no fact about one printed question, and the GM's line to supply it.

    "Nothing in the fight" is not "nothing on the creature": equipment, a sheet fact and a defense that only
    answers a particular attack are all real and none of them are in the fight record. The player is told the
    table cannot see it and the GM is asked, rather than the table guessing a negative.
    """
    ctx.rider(f"Eight-Gate Diagnosis: GM reveal {question} for {target.display_name}.")
    return f"The table cannot show {subject} on {target.display_name}; the GM answers."


def resist_text(engine: Any, target: Any) -> str | None:
    """The printed "whether it has Resistance to Bludgeoning, Force, or nonmagical physical damage" fact.

    Only the damage types the table confirms are named: Resistance to Piercing says nothing about Bludgeoning
    or Slashing. None means nothing is confirmed, which is not the same as "none": a resistance the table cannot
    see (equipment, a sheet fact, a source-conditioned defense) may still exist, so the caller keeps that a GM
    answer.
    """
    from ..typed_reactions import resistance_profile

    parts = []
    profiles = [("", {}), ("nonmagical ", {"mundane": True}),
                ("nonmagical weapon attack ", {"mundane": True, "effects": [{"type": "attack", "attack_kind": "weapon"}]}),
                ("nonmagical unarmed attack ", {"mundane": True, "effects": [{"type": "attack", "attack_kind": "unarmed"}]})]
    confirmed = set()
    next_confirmed = set()
    next_parts = []
    for qualifier, profile in profiles:
        defenses = {kind: resistance_profile(engine, target, kind, profile) for kind in (*PHYSICAL, "FORCE")}
        kinds = [kind for kind in (*PHYSICAL, "FORCE") if kind not in confirmed
                 and defenses[kind]["ordinary"]]
        confirmed.update(kinds)
        if kinds:
            parts.append(f"{qualifier}{_join([DAMAGE_NAMES[kind] for kind in kinds])} damage")
        next_kinds = [kind for kind in (*PHYSICAL, "FORCE") if kind not in confirmed
                      and kind not in next_confirmed and defenses[kind]["next_only"]]
        next_confirmed.update(next_kinds)
        if next_kinds:
            next_parts.append(f"{qualifier}{_join([DAMAGE_NAMES[kind] for kind in next_kinds])} damage")
    if not parts and not next_parts:
        return None
    answers = [f"{target.display_name} has Resistance to {_join(parts)}."] if parts else []
    if next_parts:
        answers.append(f"{target.display_name} has Resistance to {_join(next_parts)} only for the next matching damage instance "
                       "before the benefit expires. Each benefit is used up for every damage type it covers "
                       "when matching damage would be dealt.")
    return " ".join(answers) + " Resistance halves that damage."


def immune_text(engine: Any, target: Any) -> str | None:
    """The printed "whether it is immune to Prone, Grappled, Stunned, or forced movement" fact.

    ``typed_executor.condition_immune`` is the reader the engine asks before imposing a condition, so a
    standing or temporary benefit, a condition's own rule, a passive row and every plug-in's
    ``condition_immune`` hook all count. Immunity to one of those conditions is never immunity to forced
    movement -- a push is resolved by the movement hooks, not by this list -- so forced movement is named as
    a GM answer in ``diagnose`` rather than claimed from here. None means nothing is confirmed.
    """
    from ..typed_executor import condition_immune

    immune = [label for name, label in CONDITION_NAMES if condition_immune(engine, target, name)]
    if not immune:
        return None
    return (f"{target.display_name} is immune to {_join(immune)}: those conditions cannot be put on it. "
            "Whether it can be pushed, pulled or moved against its will is a separate question; "
            "the GM answers it.")


def enhancement_text(engine: Any, target: Any) -> str | None:
    """The printed "whether it is maintaining an ongoing bodily or martial enhancement" fact.

    Reuses end_effect's public ``found``/``describe`` with Internal Hammer's own ``bodily_only`` eligibility
    (combat/ext/source_eligibility.py), so the answer is the same set Internal Hammer could suppress: a stance,
    guard, body enhancement, rage-like state, mobility technique or temporary damage reduction that ends by
    itself. A Domain, a Secret Inheritance, a permanent transformation, an artifact or an effect the table
    cannot attribute is not one of them. None means nothing is confirmed.
    """
    from .end_effect import found, describe
    from .ability_source import source_label

    rows = found(engine, target, {"select": "beneficial", "bodily_only": True})
    if not rows:
        return None
    sources: dict[str, list[str]] = {}
    for kind, _, item in rows:
        label = source_label(engine, item.source_definition_id)
        sources.setdefault(label, []).append(describe(engine, kind, item))
    return (f"{target.display_name} is maintaining: "
            + "; ".join(f"{label}: {_join(benefits)}" for label, benefits in sources.items()) + ".")


@effect("iron_diagnosis")
def diagnose(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from . import floored, run
    from .eye_common import numbers_of
    from .placed import note

    targets = subjects(ctx.engine, ctx.actor, int(row["range_ft"]))
    picked_target = choose(ctx, "Eight-Gate Diagnosis creature", [target.entity_id for target in targets])
    if not picked_target:
        return
    target = next(target for target in targets if target.entity_id == picked_target[0])
    ctx = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache)
    dc = numbers_of(ctx.engine, target).get("save_dc")
    if dc is None:
        ctx.rider("Eight-Gate Diagnosis: target Cultivation Save DC is not represented; GM check required.")
        return
    checks = ctx.action.parameters["diagnosis_checks"]
    picked = choose(ctx, "Eight-Gate Diagnosis check", list(checks))
    if not picked:
        return
    label = picked[0]
    ability, skill = {"Wisdom (Medicine)": ("WIS", "Medicine"),
                     "Intelligence (Investigation)": ("INT", "Investigation"),
                     "Cultivation Check": (None, None)}[label]
    mode = te.check_mode(ctx.actor, ability or ctx.action.parameters["diagnosis_key_ability"], skill, engine=ctx.engine)
    bonus = checks[label] + sum(run("check_bonus", ctx, ctx.actor))
    roll = ctx.engine.roller.d20(modifier=bonus, actor_id=ctx.actor.entity_id,
                                reason=f"CHECK:{ctx.source}:{label}", mode=mode)
    ctx.engine._record_roll(roll)
    roll = floored(ctx.engine, ctx.actor, roll, int(dc))
    success = roll.total >= int(dc)
    ctx.engine._append_event("CHECK_ROLLED", ctx.source, actor_id=ctx.actor.entity_id,
                             target_ids=(target.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": int(dc), "success": success, "skill": skill, "check": label})
    if not success:
        return
    for fact in choose(ctx, "Eight-Gate Diagnosis information", FACTS, count=2):
        if fact == "Bloodied":
            text = f"{target.display_name} is {'Bloodied' if target.current_hp * 2 <= target.maximum_hp else 'not Bloodied'}."
        elif fact == "Weakest physical save":
            weakest = weakest_physical_saves(target)
            text = f"{target.display_name}'s weakest physical saving throw: {', '.join(weakest)}{' (tied)' if len(weakest) > 1 else ''}."
        elif fact == "Resistances":
            text = resist_text(ctx.engine, target) or unknown_fact(
                ctx, target, "whether it has Resistance to Bludgeoning, Force or nonmagical physical damage",
                "any Resistance to Bludgeoning, Force or nonmagical physical damage")
        elif fact == "Immunities":
            text = immune_text(ctx.engine, target)
            if text is None:
                text = unknown_fact(
                    ctx, target, "whether it is immune to Prone, Grappled, Stunned or forced movement",
                    "any immunity to Prone, Grappled, Stunned or forced movement")
            else:
                ctx.rider(f"Eight-Gate Diagnosis: GM reveal whether {target.display_name} is immune to forced "
                          "movement (being pushed, pulled or moved against its will).")
        elif fact == "Bodily or martial enhancement":
            text = enhancement_text(ctx.engine, target) or unknown_fact(
                ctx, target, "whether it is maintaining an ongoing bodily or martial enhancement",
                "any ongoing bodily or martial enhancement")
        else:
            ctx.rider(f"Eight-Gate Diagnosis success: GM reveal {fact} for {target.display_name}.")
            continue
        note(ctx.engine, ctx.source, ctx.actor, "Eight-Gate Diagnosis: " + text, targets=(target,))
    name = WINDOW + target.entity_id
    ctx.engine._remove_condition(ctx.actor, name, ctx.source)
    ctx.engine._apply_condition(ctx.actor, name, ctx.source, ctx.actor.entity_id,
                                expires_on=te.effect_expiry(ctx, {"duration": "until_end_of_next_turn"}, ctx.actor, condition=True),
                                data={"target": target.entity_id, "label": "Eight-Gate Diagnosis: first Unarmed Strike Advantage"})


def unarmed(action: Any) -> bool:
    return any(e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
               for e in (action.parameters.get("typed") or {}).get("effects") or [])


@hook("attack_mode")
def diagnosis_advantage(ctx: Any, target: Any) -> str | None:
    attack = ctx.attack_effect or {}
    if attack.get("attack_kind") == "unarmed" and any(c.condition_id == WINDOW + target.entity_id for c in ctx.actor.conditions.values()):
        return "ADVANTAGE"
    return None


@hook("event")
def consume_window(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "ATTACK_ROLLED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    from .attack_scope import capture_roll

    attack = capture_roll(engine, kwargs)
    if (actor is None or attack is None or attack["actor_id"] != actor.entity_id
            or attack["roll_id"] != (kwargs.get("payload") or {}).get("roll_id")
            or attack["effect"].get("attack_kind") != "unarmed"):
        return
    for target_id in kwargs.get("target_ids") or ():
        name = WINDOW + target_id
        if any(c.condition_id == name for c in actor.conditions.values()):
            engine._remove_condition(actor, name, SOURCE)
