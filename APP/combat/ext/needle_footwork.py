"""The Piercing Needle's Footwork, Crane-Wing Advance, Lunge and Court/Sovereign's Footwork benefits (task F, 2026-09-29).
Rules text: the owner's Sphere Compendium, "The Piercing Needle" (authority/typed_mechanics/rules_text.json).

  Footwork         "Cost: Expend Martial Focus. Move up to 10 feet. This movement: requires no Action or Reaction; may occur even
                   when it is not your turn; does not provoke Opportunity Attacks; must end in a legal unoccupied space you can
                   reach. You may use Footwork after an attack is declared against you but before its attack roll is made. If you
                   do, the triggering attack roll has Disadvantage. If your movement makes you an illegal target for the
                   triggering attack, the attack misses instead. You may also use Footwork after an effect that allows a
                   Dexterity saving throw includes you as a target but before you make the saving throw. If your movement does
                   not remove you from the effect, you have Advantage on the Dexterity saving throw."
                   -- the lock round's before_attack / before_dex_save checkpoints (combat/ext/__init__.py): a choice among the
                   squares (or none), the step, and the roll mode; the core rechecks the geometry (a miss, or out of the effect).
                   On your own turn the same step is a free "Footwork" action.
  Crane-Wing       "move up to 15 feet instead of 10. If you end this movement within 5 feet of a creature, your movement does not
                   provoke Opportunity Attacks from that creature for the rest of the current turn."
  Lunge            "While holding Martial Focus, you may increase your reach for melee attacks by 5 feet until the end of the current
                   turn. If you use Lunge, take a -2 penalty to attack rolls against targets within 5 feet of you until the start of
                   your next turn. Lunge does not increase your reach for Opportunity Attacks." -- a "Lunge" variant of each melee
                   weapon attack (combat/factory_compiler.py) with reach + 5 feet, offered only against a target beyond the weapon's own
                   reach; using it puts the penalty on until the start of the fencer's next turn.
  Court            "once per round when you use Footwork, regain Martial Focus after completing the movement"
  Sovereign        "once per round, you may use Footwork without expending Martial Focus"
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .choice_prompt import action_context
from .needle import (CHOICE, ask, checkpoint_id, condition, court, focus, free_cells, incapacitated, owns, position_of, regain_focus,
                     sovereign, spend_focus, step_to, timed_condition, cell_id, cell_id as _cell_id, say as _say)

LUNGE = "condition:typed.needle_lunge"
FREE_ROUND = "needle_round_free_footwork"  # the round the free Sovereign Footwork was used in
COURT_ROUND = "needle_round_court_regain"
CRANE = "needle_round_crane"  # {"slot": [round, slot], "ids": [creature ids]}: no Opportunity Attacks from them this turn


def _reach(engine: Any, actor: Any) -> int:
    return 15 if owns(engine, actor, "crane_wing") else 10


def _free_available(engine: Any, actor: Any) -> bool:
    return sovereign(actor) and actor.turn_flags.get(FREE_ROUND) != engine.state.round_number


def can_footwork(engine: Any, actor: Any) -> bool:
    return (owns(engine, actor, "footwork") and actor.active and not incapacitated(actor) and engine._effective_speed(actor) > 0
            and (focus(actor) >= 1 or _free_available(engine, actor)))


def _slot(engine: Any) -> list[int]:
    return [int(engine.state.round_number), int(engine.state.current_slot_index)]


def take_footwork(engine: Any, actor: Any, intent: Any, source: str, checkpoint: str, *, prompt: str, target_id: str | None = None,
                  preferred: list[str] | None = None, automatic: bool = False, avoid_from: Any | None = None,
                  prompt_context: dict[str, str] | None = None) -> bool:
    """One use of Footwork by ``actor``: the choice of square (or none), the cost, the step, Crane-Wing and Court. True when it
    was used (the actor has stepped or at least paid: staying put is a legal use)."""
    cells = free_cells(engine, actor, _reach(engine, actor))
    ordered = [cell_id(cell) for cell in sorted(cells, key=lambda cell: (cells[cell], cell.y, cell.x))]
    options = list(dict.fromkeys([*[p for p in preferred or [] if p in ordered], *ordered]))[:49]  # the preferred square is always among them
    labels = {cell_id(cell): (f"Step to {cell.x},{cell.y} ({cells[cell]} ft)" if cells[cell] else "Stay put (still Footwork)") for cell in cells}
    picked = ask(engine, intent, checkpoint, actor, CHOICE + "footwork", options, labels=labels, preferred=preferred or [], allow_decline=True,
                 automatic=automatic, prompt=prompt, target_id=target_id or actor.entity_id, default="decline", prompt_context=prompt_context)
    if not picked or picked[0] not in options:
        return False
    free = _free_available(engine, actor)
    if free:
        actor.turn_flags[FREE_ROUND] = engine.state.round_number
        _say(engine, source, actor, f"{actor.display_name} uses Footwork without expending Martial Focus (Sovereign Needle Incarnation).")
    elif not spend_focus(engine, actor, source, "Footwork"):
        return False
    destination = position_of(picked[0])
    moved = destination != actor.position
    step_to(engine, actor, destination, source)
    _say(engine, source, actor, f"{actor.display_name} uses Footwork" + (f" to {destination.x},{destination.y}." if moved else " (staying put)."))
    if owns(engine, actor, "crane_wing"):
        near = [other.entity_id for other in engine.state.actors.values() if other.active and other.entity_id != actor.entity_id
                and engine.grid.distance_ft(actor.position, other.position) <= 5]
        if near:
            actor.turn_flags[CRANE] = {"slot": _slot(engine), "ids": near}
    if court(actor) and actor.turn_flags.get(COURT_ROUND) != engine.state.round_number and regain_focus(engine, actor, source, "Court of Measured Openings: Footwork"):
        actor.turn_flags[COURT_ROUND] = engine.state.round_number
    return True


def _escape_cells(engine: Any, actor: Any, attacker: Any, reach: int) -> list[str]:
    cells = free_cells(engine, actor, _reach(engine, actor))
    return [cell_id(cell) for cell in sorted(cells, key=lambda c: (-engine.grid.distance_ft(attacker.position, c), c.y, c.x))
            if engine.grid.distance_ft(attacker.position, cell) > reach]


# ------------------------------------------------------------------------------------------------ reactions: before an attack, before a Dexterity save
@hook("before_attack")
def footwork_before_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """"After an attack is declared against you but before its attack roll is made": Disadvantage on the roll, or a miss when the
    step leaves you an illegal target. The AI takes it when a melee attacker can be stepped out of reach."""
    if defender is None or attacker is None or defender.team_id == attacker.team_id or not can_footwork(engine, defender):
        return None
    reach = int(context.get("range_ft") or 5)
    escapes = _escape_cells(engine, defender, attacker, reach) if reach <= 10 else []
    used = take_footwork(engine, defender, intent, f"reaction:footwork:{defender.entity_id}",
                         checkpoint_id(engine, "FOOTWORK_ATTACK", attacker.entity_id, defender.entity_id, context.get("attack_index", 1)),
                         prompt=f"Footwork against {attacker.display_name}'s attack? (Disadvantage on it, or it misses if you leave its reach)",
                         target_id=attacker.entity_id, preferred=escapes[:1] or [_cell_id(defender.position)], automatic=bool(escapes),
                         prompt_context=action_context(engine, attacker, str(context.get("source_id") or ""), defender))
    return {"mode": "DISADVANTAGE"} if used else None


@hook("before_dex_save")
def footwork_before_dex_save(engine: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """"After an effect that allows a Dexterity saving throw includes you as a target": Advantage on the save if the step does not
    take you out of the effect (the core skips the save when it does)."""
    if defender is None or not can_footwork(engine, defender):
        return None
    source_actor = engine.state.actors.get(str(getattr(intent, "actor_id", "") or ""))
    if source_actor is not None and source_actor.team_id == defender.team_id:
        return None
    # Preserve the action-phase guard above. A retained end-turn intent transports
    # answers only; neither its actor nor the hazard's team excludes turn-start saves.
    source_id = str(context.get("source_id") or "")
    action = engine.action_catalog.get(source_id)
    source_name = action.display_name if action else source_id.rsplit(":", 1)[-1].rsplit(".", 1)[-1].replace("_", " ").title()
    used = take_footwork(engine, defender, intent, f"reaction:footwork:{defender.entity_id}",
                         checkpoint_id(engine, "FOOTWORK_SAVE", defender.entity_id, context.get("source_id", "")),
                         prompt=f"Footwork: {defender.display_name} faces {source_name or 'the effect'}'s Dexterity save? (Advantage on it, or leave the effect)",
                         target_id=defender.entity_id, preferred=[_cell_id(defender.position)], automatic=False,
                         prompt_context=action_context(engine, source_actor, str(context.get("source_id") or ""), defender))
    return {"mode": "ADVANTAGE"} if used else None


# ------------------------------------------------------------------------------------------------ on your own turn
@effect("needle_footwork")
def footwork_effect(ctx: Any, eff: dict[str, Any]) -> None:
    take_footwork(ctx.engine, ctx.actor, ctx.intent, ctx.source, checkpoint_id(ctx.engine, "FOOTWORK", ctx.actor.entity_id),
                  prompt="Footwork: where do you step?", automatic=False)


@hook("compile_actions")
def footwork_actions(info: dict[str, Any]) -> list[Any] | None:
    if "TAL_FENCING_FOOTWORK" not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.footwork", display_name="Footwork", owner_id=info["actor_id"],
                             economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                             parameters={"typed": {"effects": [{"type": "needle_footwork"}], "numbers": info["numbers"],
                                                   "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True})]


@hook("ai_candidate_allowed")
def footwork_ai(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The built-in AI has no use for a free step on its own turn; it takes Footwork as a reaction (before_attack) instead."""
    return False if str(getattr(action, "source_definition_id", "")).endswith(".footwork") else None


@hook("candidate_allowed")
def footwork_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    source = str(getattr(action, "source_definition_id", ""))
    if source.endswith(".footwork"):
        return None if can_footwork(engine, actor) else False
    parameters = getattr(action, "parameters", None) or {}
    if parameters.get("lunge"):  # only worth taking against a target beyond the weapon's own reach
        if focus(actor) < 1:
            return False
        reach = int(getattr(action, "range_ft", 5) or 5) - 5
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
        return False if target is None or engine.grid.distance_ft(actor.position, target.position) <= reach else None
    return None


# ------------------------------------------------------------------------------------------------ Crane-Wing, Lunge
@hook("opportunity_allowed")
def crane_wing_no_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """"... does not provoke Opportunity Attacks from that creature for the rest of the current turn.\""""
    row = mover.turn_flags.get(CRANE)
    if isinstance(row, dict) and row.get("slot") == _slot(engine) and reactor.entity_id in (row.get("ids") or []):
        return False
    return None


@hook("technique_used")
def lunge_used(ctx: Any) -> None:
    """Using Lunge puts the -2 on until the start of the fencer's next turn."""
    if not (getattr(ctx.action, "parameters", None) or {}).get("lunge"):
        return
    from .effect_durations import token

    actor = ctx.actor
    timed_condition(ctx.engine, actor, LUNGE, ctx.source, actor.entity_id, token("start", actor.entity_id, int(actor.turns_started) + 1),
                    {"label": "Lunge: -2 to attack rolls against targets within 5 feet"})
    _say(ctx.engine, ctx.source, actor, f"{actor.display_name} lunges: -2 to attack rolls against targets within 5 feet until the start of their next turn.")


@hook("attack_bonus")
def lunge_penalty(ctx: Any, actor: Any) -> int | None:
    target = getattr(ctx, "target", None)
    if condition(actor, LUNGE) is None or target is None or ctx.engine.grid.distance_ft(actor.position, target.position) > 5:
        return None
    return -2
