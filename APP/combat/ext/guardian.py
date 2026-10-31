"""Guardian sphere: Challenge (rider lane C2, 2026-09-30: "i want everything we can automated").  Rules text: the owner's Sphere Compendium,
"Challenge Practice" and the Challenge talents (authority/typed_mechanics/rules_text.json).

Shared public row lookup is used by guardian_chassis.py and guardian_patrol.py
to read the same owned Guardian features; Challenge state remains owned here.

``guardian_challenge`` (the failed save of Challenge): the creature is Challenged by you ("condition:typed.challenged", filed under you, for
the Challenge's minute); your previous Challenge ends ("when you successfully Challenge another creature, your previous Challenge ends");
other guardians' Challenges stay ("A creature may be affected by Challenges from multiple cultivators").

``before_attack`` (typed and legacy attacks alike): a Challenged creature attacking a creature that has not Challenged it has
Disadvantage when at least one of its challengers could legally have been this attack's target
("if it cannot legally perceive, reach, or target you, it does not suffer Disadvantage"); attacking one of its
challengers it has Advantage ("attack rolls targeting only you").

Owned rows (combat/rules/feature_blocks.d/riders_c2.json, block "guardian"; inert without the row):
  punishing_challenge   that Disadvantage costs the attacker Psychic or Radiant damage equal to your CL, once per turn per creature.
  flush_of_victory      a creature Challenged by you drops to 0 HP: Temporary HP equal to your CL.
  inescapable_challenge a creature Challenged by you teleporting farther from you makes a Wisdom save; on a failure the teleport fails.
  swift_guardian        "Challenge (Swift Guardian: no action)": Challenge for Martial Focus without spending the Bonus Action.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .challenge_conditions import is_deed_challenge

BLOCK = "guardian"
CHALLENGED = "condition:typed.challenged"
CHALLENGE = "GUARDIAN_BASE_CHALLENGE_PRACTICE"


def row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    from .passive_rows import row_of

    return row_of(engine, actor.entity_id, BLOCK, kind)


def challengers(engine: Any, creature: Any) -> list[Any]:
    """Active Guardian challengers; Deed Follows Word owns its separate rules."""
    ids = {c.source_actor_id for c in creature.conditions.values()
           if c.condition_id == CHALLENGED and not is_deed_challenge(c)}
    return [engine.state.actors[i] for i in sorted(ids) if i in engine.state.actors and engine.state.actors[i].active]


@hook("save_mode")
def mageguard(engine: Any, target: Any, ability: str, dc: int, source_id: str, roll_context: dict[str, Any]) -> str | None:
    """Owned Mageguard affects actual Concentration saves only, within melee reach."""
    if source_id != "system:combat.concentration" or ability.upper() != "CON":
        return None
    from ..typed_reactions import physical_melee_reach

    if any(row(engine, guardian, "mageguard") is not None
           and engine._distance_actor_to_actor(guardian, target) <= (physical_melee_reach(engine, guardian) or 0)
           for guardian in challengers(engine, target)):
        return {"mode": "DISADVANTAGE", "effect": "Mageguard", "owner": next(guardian for guardian in challengers(engine, target)
                                                     if row(engine, guardian, "mageguard") is not None),
                "why": "a Challenged ally within a guardian’s melee reach helps guard this Concentration save"}
    return None


@hook("compile_block")
def guardian_block(block: str, spec: dict[str, Any], row_: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row_, "block": BLOCK, "kind": spec.get("kind"), "cl": int(numbers.get("cl") or 1), "pb": int(numbers.get("pb") or 2),
             **({"maneuver_focus": True} if spec.get("maneuver_focus") else {}),
             **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]


@effect("guardian_challenge")
def challenge(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import effect_expiry
    from .creature_kinds import matches

    engine, me = ctx.engine, ctx.actor
    for subject in ctx.targets or ([ctx.target] if ctx.target else []):
        if subject is None or not subject.active or matches(subject, "mindless"):
            continue
        for other in engine.state.actors.values():  # the previous Challenge ends
            for condition in list(other.conditions.values()):
                if (condition.condition_id == CHALLENGED and not is_deed_challenge(condition)
                        and condition.source_actor_id == me.entity_id):
                    engine._remove_condition(other, CHALLENGED, condition.source_definition_id)
        engine._apply_condition(subject, CHALLENGED, ctx.source, me.entity_id,
                                expires_on=effect_expiry(ctx, {"duration": "one_minute"}, subject, condition=True),
                                data={"label": f"Challenged by {me.display_name}: Disadvantage on attacks that do not include {me.display_name}; "
                                               f"Advantage on attacks against only {me.display_name}. The penalty applies only when {me.display_name} "
                                               "is a legal target for the attack. Lasts up to 1 minute"})


@hook("before_attack")
def challenged_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    chall = challengers(engine, attacker)
    if not chall or defender is None:
        return None
    if any(c.entity_id == defender.entity_id for c in chall):
        return {"mode": "ADVANTAGE", "effect": "Challenge (Guardian)",
                "owner": next(c for c in chall if c.entity_id == defender.entity_id),
                "why": "you attack a creature that has itself Challenged you"}
    from ..attack_declaration import can_target

    counting = [c for c in chall if can_target(engine, attacker, c, context["source_id"],
        action=context.get("action"), typed=context.get("typed"), effect=context.get("effect"),
        index=context.get("attack_index", 1))]
    if not counting:
        return None
    _punish(engine, attacker, counting, intent)
    return {"mode": "DISADVANTAGE", "effect": "Challenge (Guardian)",
            "owner": counting[0],
            "why": "you are Challenged and this target has not Challenged you"}


def _punish(engine: Any, attacker: Any, guardians: list[Any], intent: Any) -> None:
    """Punishing Challenge: "it takes your choice of Psychic or Radiant damage equal to your Cultivation Level" (once per turn per creature)."""
    from ..typed_reactions import triggered_context
    from .. import typed_executor as te

    turn = int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)
    for guardian in guardians:
        owned = row(engine, guardian, "punishing_challenge")
        if owned is None:
            continue
        key = f"guardian_round_punish:{attacker.entity_id}"
        if guardian.turn_flags.get(key) == turn:
            continue
        guardian.turn_flags[key] = turn
        ctx = triggered_context(engine, guardian, attacker, {"feature_id": str(owned.get("feature_id")), "name": "Punishing Challenge",
                                                           "numbers": {"cl": int(owned.get("cl") or 1), "pb": int(owned.get("pb") or 2)}, "effects": []}, intent)
        te.run_effects(ctx, [{"type": "damage", "applies_to": "target", "formula": "cl", "damage_types": ["psychic", "radiant"],
                              "evidence": "Punishing Challenge: Psychic or Radiant damage equal to your Cultivation Level"}])


@hook("event")
def flush_of_victory(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Flush of Victory: "When a creature Challenged by you is reduced to 0 HP, gain Temporary HP equal to your Cultivation Level\"."""
    if event_type != "DAMAGE_COMMITTED" or int((kwargs.get("payload") or {}).get("remaining_hp", 1) or 0) > 0:
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is None:
            continue
        for me in challengers(engine, target):
            owned = row(engine, me, "flush_of_victory")
            if owned is None or not me.active:
                continue
            engine._grant_temp_hp(me, int(owned.get("cl") or 1), str(owned.get("feature_id")), me.entity_id)


@hook("teleport_gate")
def inescapable(ctx: Any, start: Any, destination: Any) -> bool | None:
    """Inescapable Challenge: teleporting farther from you -- a Wisdom save; a failure prevents the movement (the Action is spent)."""
    engine, actor = ctx.engine, ctx.actor
    for guardian in challengers(engine, actor):
        if row(engine, guardian, "inescapable_challenge") is None:
            continue
        if engine.grid.distance_ft(destination, guardian.position) <= engine.grid.distance_ft(start, guardian.position):
            continue
        from .needle import save_dc

        dc = save_dc(engine, guardian)
        roll = engine._roll_save(actor, "WIS", dc, "TAL_GUARDIAN_INESCAPABLE_CHALLENGE")
        if roll is not None and int(roll.total) < dc:
            from . import note

            note(engine, "TAL_GUARDIAN_INESCAPABLE_CHALLENGE", guardian, f"Inescapable Challenge: {actor.display_name} cannot teleport away from "
                 f"{guardian.display_name} (Wisdom save {roll.total} against {dc}); the Action is spent.", (actor,))
            return False
    return None


@hook("movement_attempt")
def inescapable_walk(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """Inescapable Challenge, ordinary movement: "When a creature Challenged by you willingly attempts to move
    farther away from you, it makes a Wisdom saving throw. Failed Save: Its attempted movement ends before carrying it
    farther away." The seam rolls before the step is paid for, so a refusal leaves the mover where it was and the rest
    of its path untouched. Forced movement has its own seams and is not stopped here ("Inescapable Challenge does not
    stop forced movement caused by another creature")."""
    for guardian in challengers(engine, mover):
        if row(engine, guardian, "inescapable_challenge") is None:
            continue
        if engine.grid.distance_ft(nxt, guardian.position) <= engine.grid.distance_ft(previous, guardian.position):
            continue
        from . import note
        from .needle import save_dc

        dc = save_dc(engine, guardian)
        roll = engine._roll_save(mover, "WIS", dc, "TAL_GUARDIAN_INESCAPABLE_CHALLENGE")
        if roll is not None and int(roll.total) < dc:
            note(engine, "TAL_GUARDIAN_INESCAPABLE_CHALLENGE", guardian,
                 f"Inescapable Challenge: {mover.display_name} fails the Wisdom save and does not move farther from "
                 f"{guardian.display_name} ({roll.total} against {dc}).", (mover.entity_id,))
            return {"stop": True, "source_id": "TAL_GUARDIAN_INESCAPABLE_CHALLENGE",
                    "label": f"Inescapable Challenge: {mover.display_name} cannot walk away from {guardian.display_name}"}
    return None


@hook("compile_actions")
def swift_challenge(info: dict[str, Any]) -> list[Any] | None:
    """Swift Guardian: "activate Challenge without spending an Action during your turn" for Martial Focus."""
    import copy

    from ..gate2_runtime_models import EconomyKind

    if "TAL_GUARDIAN_SWIFT_GUARDIAN" not in set(info.get("owned_ids") or ()):
        return None
    base = next((a for a in info.get("actions") or () if ((a.parameters or {}).get("typed") or {}).get("source") == CHALLENGE
                 and "#" not in a.source_definition_id), None)
    if base is None:
        return None
    return [base.model_copy(update={"source_definition_id": base.source_definition_id + "#swift", "economy": EconomyKind.NONE,
                                    "display_name": "Challenge (Swift Guardian: no action; spend Martial Focus, your readiness point)",
                                    "costs": (*tuple(base.costs or ()), ("resource:core.martial_focus", 1)),
                                    "parameters": copy.deepcopy(base.parameters)})]
