"""Shared skill query API for effect_transfer, eye_common, tabik_dark and trap. skill is a creature's skill bonus and
modifier is one ability score's bonus, used by every Scoundrel Check; those two public names are the entry points, never an
underscore-prefixed one.

The Scoundrel sphere's maneuvers (owner 2026-09-28: "we need to automate every aspect before another playtest"; Tabik
Damu's kit). Dirty Trick and Steal were compiled with every result at once and no roll.

Scoundrel Check (Sphere Compendium, Core Scoundrel Rules): Dexterity (Sleight of Hand); a creature that actively opposes
the maneuver rolls Strength (Athletics) or Dexterity (Acrobatics), its better one; the higher result wins and a tie goes to
the defender. Steal against a creature that is unaware of the thief (it is hidden from it) is Sleight of Hand against the
creature's Passive Perception instead; Disadvantage when the object is held in two hands.

effect scoundrel_check   the check; ``on_success`` runs on the target when it wins, then the talents below
  hook  scoundrel_object_choice
                            the printed "Choose one accessible object" that comes BEFORE this check on the Steal
                            family: (engine, actor, target, source, effect row), where source is the ability's own
                            typed source -> {"difficult": bool, "on_success": [effect rows]}, asked before the
                            roll, with the rows run only when the check succeeds and replacing the row's own
                            on_success (a declined or unanswered question leaves the table's own default object
                            alone). None from every provider keeps the row's own behaviour, which is what a saved
                            fight from before the seam replays
  effect exploited_opening Exploited Opening until the start of its next turn: the target can't make Opportunity Attacks
                            against it, and the next attack roll against the target -- or its next Scoundrel Check against
                            the target, whichever comes first -- has Advantage; one at a time per Scoundrel
  effect steal_weapon      Steal as the local Scoundrel disarm: the target's best weapon into the thief's free hand
  block scoundrel_talent   what a success adds (feature_blocks.d/tabik.json):
                             twist         Twist the Knife: once per turn, one melee weapon attack or Unarmed Strike
                                           against a target within reach, as part of the same Action
                             cut_and_run   Cut and Run: while holding Martial Focus, a success with its Action lets it move
                                           up to half its Speed more, and the target makes no Opportunity Attack on it
                                           for the rest of the turn
                             focus         Focusing Thievery: "Focusing Thievery: regain Martial Focus", a Bonus Action
                                           offered for the rest of a turn in which it succeeded
                             filthy        Filthy Distraction: against a creature that was unaware of it, Disadvantage on
                                           Perception and Passive Perception -5 until the end of its next turn (a real
                                           condition, applied by combat/ext/scoundrel_riders.py)
  hook  steal_check_waiver Scoundrel Check only: (engine, actor, target, source, effect row) -> True waives the printed
                          Disadvantage for this roll (Master Thief, for 1 Martial Focus), False forces it on, None keeps
                          the printed reading. The row carries ``object_difficult``, whether the object actually chosen
                          is one the printed Disadvantage names. Asked before the check is rolled; nothing spent unless
                          it is waived
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook
from . import run as _run
from .condition_events import drop_condition as _drop
from .eye_common import passive_perception
from ..ability_checks import ability_modifier

EXPLOITED = "condition:typed.exploited_opening"
SUCCESS_FLAG = "scoundrel_success"
FOCUS = "resource:core.martial_focus"
FILTHY = "filthy"  # Filthy Distraction, as combat/rules/feature_blocks.d/tabik.json names its kind


def _talents(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("kind")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == "scoundrel_talent"}


def modifier(score: int) -> int:
    return (int(score) - 10) // 2


def skill(engine: Any, creature: Any, name: str, fallback: int) -> int:
    """A fighter's skill bonus: its sheet's (a compiled character's bundle "skills"), else the fallback."""
    from ..ability_checks import skill_bonus

    return skill_bonus(engine, creature, name, fallback)


def _exploited_by(target: Any, actor_id: str) -> list[str]:
    return [iid for iid, condition in target.conditions.items() if condition.condition_id == EXPLOITED and condition.source_actor_id == actor_id]


def _end_exploit(engine: Any, target: Any, actor_id: str, source: str) -> None:
    for iid in _exploited_by(target, actor_id):
        _drop(engine, target, iid, source)
    for mid, modifier in list(target.modifiers.items()):
        if modifier.target_field == "incoming_attack_mode" and modifier.source_definition_id == f"exploit:{actor_id}":
            del target.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=actor_id, target_ids=(target.entity_id,),
                                 payload={"modifier_id": mid, "reason": "CONSUMED"})


# ------------------------------------------------------------------------------------------------ the check
def check_against_dc(engine, actor, target, source, dc):
    """Shared Scoundrel check for Steal Momentum: skill, Exploit and check modes."""
    from ..typed_executor import check_modes
    from . import floored
    bonus = max(skill(engine, actor, 'Sleight of Hand', 0), modifier(actor.dexterity_score) + int(actor.proficiency_bonus))
    exploited = bool(_exploited_by(target, actor.entity_id))
    modes = check_modes(actor, 'DEX', 'Sleight of Hand', engine=engine, against_creature=target)
    if exploited:
        modes.add('ADVANTAGE')
    if exploited:
        _end_exploit(engine,target,actor.entity_id,source)
    roll = engine.roller.d20(modifier=bonus,actor_id=actor.entity_id,reason=f'CHECK:{source}:SLEIGHT_OF_HAND',
                             mode=modes.pop() if len(modes)==1 else 'NORMAL')
    engine._record_roll(roll)
    roll = floored(engine,actor,roll,dc)
    success = roll.total >= dc
    engine._append_event('CHECK_ROLLED',source,actor_id=actor.entity_id,target_ids=(target.entity_id,),
        payload={'actor':roll.model_dump(mode='json'),'dc':dc,'success':success,'skill':'Sleight of Hand',
                 'against':'Cultivation Save DC'})
    return success


def _object_choice(ctx: Any, eff: dict[str, Any]) -> dict[str, Any] | None:
    """The Steal family's printed "Choose one accessible object", asked before the check that depends on it.

    Every provider is consulted; the first that owns this check's row answers. None (no provider, an ability
    that steals no object, or an engine with no choice transport) leaves the row's own behaviour untouched, so
    a fight saved before the seam resolves exactly as it did.
    """
    for choice in _run("scoundrel_object_choice", ctx.engine, ctx.actor, ctx.target,
                       str(getattr(ctx.typed, "get", lambda _k: None)("source") or ctx.source or ""), eff):
        if isinstance(choice, dict):
            return choice
    return None


@effect("scoundrel_check")
def scoundrel_check(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    from .. import stealth

    # Scoundrel Training: "When you learn Scoundrel: gain proficiency in Dexterity (Sleight of Hand)" -- every Scoundrel is
    # proficient, whether or not the sheet lists the skill.
    bonus = max(skill(engine, actor, "Sleight of Hand", 0), modifier(actor.dexterity_score) + int(actor.proficiency_bonus))
    advantage = bool(_exploited_by(target, actor.entity_id))
    # "Choose one accessible object" comes first on the Steal family: the printed difficulty and the printed result
    # are both about that object, so it is chosen before the roll.
    chosen = _object_choice(ctx, eff)
    difficult = bool(chosen.get("difficult")) if chosen is not None else _two_handed(engine, target)
    printed = bool(eff.get("two_handed_disadvantage")) and difficult
    disadvantage = printed
    for waived in _run("steal_check_waiver", engine, actor, target, ctx.source, {**eff, "object_difficult": printed}):
        if waived is not None:  # a talent that waives (Master Thief) or adds to the printed Disadvantage owns this roll
            disadvantage = not bool(waived)
    from ..typed_executor import check_mode, check_modes

    # Steal Equipment's own Disadvantage is one more source of this roll, not an overwrite: "Master Thief does not
    # remove this" means no talent may take it away, not that Advantage never cancels it.
    sources = [("ADVANTAGE" if advantage else None), ("DISADVANTAGE" if disadvantage else None),
               ("DISADVANTAGE" if eff.get("disadvantage") else None),
               *check_modes(actor, "DEX", "Sleight of Hand", engine=engine, against_creature=target)]
    modes = {m for m in sources if m in ("ADVANTAGE", "DISADVANTAGE")}
    mode = modes.pop() if len(modes) == 1 else "NORMAL"
    if advantage:
        _end_exploit(engine, target, actor.entity_id, ctx.source)  # the benefit is used
    unseen = not stealth.sees(engine, target, actor)
    unaware = bool(eff.get("unaware_uses_passive")) and unseen
    mine = engine.roller.d20(modifier=bonus, actor_id=actor.entity_id, reason=f"CHECK:{ctx.source}:SLEIGHT_OF_HAND", mode=mode)
    engine._record_roll(mine)
    payload: dict[str, Any] = {"actor": mine.model_dump(mode="json"), "skill": "Sleight of Hand"}
    from . import floored  # Complete Mandala Auspice (combat/ext/d20_floor.py)

    if unaware:
        dc = passive_perception(engine, target, actor)  # the shared Passive Perception (Scoundrel riders' -5 included)
        mine = floored(engine, actor, mine, dc)
        payload["actor"] = mine.model_dump(mode="json")
        success = mine.total >= dc
        payload.update({"dc": dc, "against": "Passive Perception"})
    else:
        athletics = skill(engine, target, "Athletics", ability_modifier(target, "STR"))
        acrobatics = skill(engine, target, "Acrobatics", modifier(target.dexterity_score))
        skill_ = ("STR", "Athletics") if athletics >= acrobatics else ("DEX", "Acrobatics")
        theirs = engine.roller.d20(modifier=max(athletics, acrobatics), actor_id=target.entity_id, reason=f"CHECK:{ctx.source}:OPPOSE",
                                   mode=check_mode(target, *skill_, engine=engine, against_creature=actor))
        engine._record_roll(theirs)
        mine = floored(engine, actor, mine, theirs.total + 1)
        payload["actor"] = mine.model_dump(mode="json")
        success = mine.total > theirs.total  # a tie goes to the defender
        payload.update({"target": theirs.model_dump(mode="json"), "target_skill": skill_[1], "against": skill_[1]})
    payload["success"] = success
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload=payload)
    if not success:
        return
    from .. import typed_executor

    sub = typed_executor.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    if chosen:
        # The fighter named the object, so the printed result is theirs: a chosen object replaces the row's own
        # default (Steal's local disarm of the best weapon in hand), and nothing moves if the check failed.
        typed_executor.run_effects(sub, copy.deepcopy(chosen.get("on_success") or []))
    else:
        typed_executor.run_effects(sub, copy.deepcopy(eff.get("on_success") or []))
    actor.turn_flags[SUCCESS_FLAG] = True
    talents = _talents(engine, actor)
    economy = getattr(ctx.action.economy, "value", ctx.action.economy)
    if FILTHY in talents and eff.get("dirty_trick") and unseen:
        # "it has Disadvantage on Wisdom (Perception) checks ... Its Passive Perception is reduced by 5 for the same
        # duration": a real condition (combat/ext/scoundrel_riders.py), not a line for the GM.
        from .scoundrel_riders import filthy_distraction

        filthy_distraction(ctx, target)
    if "cut_and_run" in talents and economy == "ACTION" and actor.resources.get(FOCUS, 0) >= 1:
        engine_speed = engine._effective_speed(actor)
        actor.movement_remaining_ft = int(actor.movement_remaining_ft) + engine_speed // 2
        actor.turn_flags["cut_and_run_from"] = target.entity_id
        ctx.rider(f"Cut and Run: {actor.display_name} may move up to {engine_speed // 2} feet more; {target.display_name} makes no Opportunity Attack on it.")
    if "twist" in talents and target.active and not actor.turn_flags.get("twist_the_knife") and not ctx.damage_cache.get("twist"):
        _twist(ctx, target)


def _two_handed(engine: Any, target: Any) -> bool:
    from .. import typed_executor

    weapon = typed_executor._best_weapon_action(engine, target)
    typed = ((engine.action_catalog[weapon].parameters or {}).get("typed") or {}) if weapon and weapon in engine.action_catalog else {}
    return "two-handed" in str((typed.get("weapon") or {}).get("properties") or "").lower()


def _twist(ctx: Any, target: Any) -> None:
    """Twist the Knife: one melee weapon attack or Unarmed Strike, its best, within reach."""
    engine, actor = ctx.engine, ctx.actor
    own = [action for action in engine.action_catalog.values() if action.owner_id == actor.entity_id and action.source_definition_id in actor.action_ids
           and ((action.parameters or {}).get("typed") or {}).get("weapon") and "#" not in action.source_definition_id
           and not ((action.parameters or {}).get("typed") or {}).get("range_ft")]
    usable = [action for action in own if engine._distance_actor_to_actor(actor, target) <= int(action.range_ft or 5)]
    pick = max(usable, key=lambda action: (int((action.parameters or {}).get("expected_damage") or 0), action.source_definition_id), default=None)
    if pick is None:
        return
    typed = copy.deepcopy(pick.parameters["typed"])
    attack = next((row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "attack"), None)
    if attack is None:
        return
    actor.turn_flags["twist_the_knife"] = True
    ctx.damage_cache["twist"] = True
    typed["effects"] = [{**attack, "count": 1}]
    from .. import typed_executor

    engine._append_event("PASSIVE_TRIGGERED", "passive:TAL_SCOUNDREL_TWIST_THE_KNIFE", actor_id=actor.entity_id, target_ids=(target.entity_id,),
                         payload={"trigger": "Twist the Knife", "with": pick.display_name})
    typed_executor.run_effects(typed_executor.Context(engine, actor, pick, ctx.intent, typed, [target], target, {}), typed["effects"])


# ------------------------------------------------------------------------------------------------ results
@effect("exploited_opening")
def exploited_opening(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    _end_exploit(engine, target, actor.entity_id, ctx.source)  # one at a time from the same Scoundrel
    engine._apply_condition(target, EXPLOITED, ctx.source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": f"Exploited Opening: no Opportunity Attacks against {actor.display_name}; the next attack roll against it has Advantage"})
    engine._add_modifier(target, f"exploit:{actor.entity_id}", "incoming_attack_mode", "SET", "ADVANTAGE", "NEXT_ATTACK",
                         expires_on="START_OF_SOURCE_NEXT_TURN", spend_on_roll=True)


@effect("steal_weapon")
def steal_weapon(ctx: Any, eff: dict[str, Any]) -> None:
    """The weapon comes away into the thief's free hand: its owner has lost it until it disarms the thief (the same state
    as "Take a dropped weapon")."""
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    from .. import typed_executor

    weapon = typed_executor._best_weapon_action(engine, target)
    if weapon is None:
        ctx.rider(f"Steal: {target.display_name} holds no weapon; another object is the GM's.")
        return
    engine._apply_condition(target, typed_executor.CONDITION_PREFIX + "disarmed", ctx.source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"disables_action": weapon, "held_by": actor.entity_id})
    typed_executor._reweigh(ctx)


@hook("event")
def exploit_used(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The Advantage on the next attack roll against the target was used: the Exploited Opening ends."""
    if event_type != "MODIFIER_REMOVED" or "exploit:" not in str((kwargs.get("payload") or {}).get("modifier_id") or ""):
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is None:
            continue
        for iid, condition in list(target.conditions.items()):
            if condition.condition_id == EXPLOITED and not any(
                    modifier.source_definition_id == f"exploit:{condition.source_actor_id}" for modifier in target.modifiers.values()):
                _drop(engine, target, iid, f"exploit:{condition.source_actor_id}")


@hook("opportunity_allowed")
def no_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    if _exploited_by(reactor, mover.entity_id):
        return False  # Exploited Opening: "the target cannot make Opportunity Attacks against you"
    if mover.turn_flags.get("cut_and_run_from") == reactor.entity_id:
        return False  # Cut and Run
    return None


# ------------------------------------------------------------------------------------------------ talents
@hook("compile_block")
def scoundrel_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "scoundrel_talent":
        return None
    # "keeps_compiling": the feature is more than this ownership row (Bob and Weave is its own Bonus Action), so the
    # compiler still builds the action its typed record describes (combat/typed_reactions.py compile_blocks).
    return [{**row, "block": "scoundrel_talent", "kind": spec.get("kind"),
             **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]


@hook("compile_actions")
def focusing_thievery(info: dict[str, Any]) -> list[Any] | None:
    if not any(row.get("block") == "scoundrel_talent" and row.get("kind") == "focus" for row in info["passives"]):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.focusing_thievery", display_name="Focusing Thievery: regain Martial Focus",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "gain_resource", "applies_to": "self", "resource_id": FOCUS, "flat": 1,
                                           "evidence": "Whenever you succeed on Dirty Trick or Steal, regain Martial Focus as a Bonus Action."}],
                              "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": "TAL_SCOUNDREL_FOCUSING_THIEVERY"},
                    "expected_damage": 0, "focusing_thievery": True})]


@hook("candidate_allowed")
def focusing_thievery_now(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get("focusing_thievery"):
        return None
    return bool(actor.turn_flags.get(SUCCESS_FLAG)) and actor.resources.get(FOCUS, 0) < 1 and FOCUS in actor.resources
