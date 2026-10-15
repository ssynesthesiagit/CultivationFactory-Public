"""Shared helper module (consumers: states.py). Standing still (auto/lane2 2026-09-29): Shift Position (Sniper) and Rest Hold (Wrestling).

Shared public helper ``moved_ft(engine, actor)`` reads current-turn willing
movement events for Shift Position and sniper_lines' Breath-Held Shot. Reloaded
history, teleports and free steps count; forced displacement does not.

The shared moved_ft helper also serves charm_rules' one-activity restriction.

The owner's text for both is a Bonus Action that regains Martial Focus in return for keeping still:

Shift Position -- "If you move no more than 5 feet during your turn, you may regain Martial Focus as a Bonus Action."
  ``candidate_allowed``: offered only while the moves you have made this turn (the table's MOVEMENT_COMMITTED events since
  your TURN_STARTED; a push or a pull is not your move, a teleport counts as the distance it crossed) come to 5 feet or
  less. ``hold_position`` (effect, {"max_ft": 5}) then takes what movement is left down to what keeps the whole turn inside
  the limit, so a later step cannot break the condition the text puts on it. A Prone user stands up at the start of its
  turn (gate2_engine STAND_UP), so the "while Prone" line needs nothing here.

Rest Hold -- Bonus Action, "While grappling one creature ... reduce your Speed to 0 until the start of your next turn ...
  the Grappled creature grants you Half Cover against attacks made by creatures other than itself ... If you possess
  Athletics sphere Close Quarters Training ... Three-Quarters Cover instead."
  ``rest_hold`` (effect): a "condition:typed.rest_hold" on the user until the start of its next turn (Speed 0 through the
  rule ``rest_hold`` in combat/rules/typed_conditions.json, and what is left of this turn's movement goes too) that
  carries the cover (2, or 5 with Close Quarters Training, which is the fighter owning that talent's action).
  ``cover`` hook: the cover counts while the user is still grappling that creature, against every attacker but it. The
  table's cover bonus applies to ranged attacks only (Gate4ControllerEngine._cover_bonus_actor_to_actor), so a melee attack
  against the user ignores it; that is the table's cover rule, not this plug-in's. Pulling the creature into the user's
  space (Close Quarters Training) has no place on the map (two creatures never share a square) and stays a GM line.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

FOCUS = "resource:core.martial_focus"
GRAPPLED = "condition:typed.grappled"
REST_HOLD = "condition:typed.rest_hold"
SHIFT_POSITION = "TAL_SNIPER_SHIFT_POSITION"
REST_HOLD_ID = "TAL_WRESTLING_REST_HOLD"
CLOSE_QUARTERS = "TAL_ATHLETICS_CLOSE_QUARTERS_TRAINING"


def moved_ft(engine: Any, actor: Any) -> int:
    """Willing movement this turn; shared by Shift Position and sniper_lines' Breath-Held Shot."""
    from ..gate2_runtime_models import Position

    total = 0
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED" and event.actor_id == actor.entity_id:
            break
        payload = event.payload or {}
        if event.event_type != "MOVEMENT_COMMITTED" or event.actor_id != actor.entity_id or payload.get("forced"):
            continue
        path = [Position(**cell) for cell in payload.get("path") or [] if isinstance(cell, dict)]
        if payload.get("teleport") and len(path) >= 2:
            total += engine.grid.distance_ft(path[0], path[-1])
        else:
            total += max(0, len(path) - 1) * engine.grid.square_size_ft
    return total


def _typed(action: Any) -> dict[str, Any]:
    return (getattr(action, "parameters", None) or {}).get("typed") or {}


def grappled_by(engine: Any, actor: Any) -> list[Any]:
    """The creatures this one is grappling now."""
    return sorted((other for other in engine.state.actors.values() if other.active and other.entity_id != actor.entity_id
                   and any(c.condition_id == GRAPPLED and c.source_actor_id == actor.entity_id for c in other.conditions.values())),
                  key=lambda other: other.entity_id)


def _has_close_quarters(engine: Any, actor: Any) -> bool:
    catalog = getattr(engine, "action_catalog", {}) or {}
    return any(_typed(catalog.get(action_id)).get("source") == CLOSE_QUARTERS for action_id in actor.action_ids)


@hook("candidate_allowed")
def stillness_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    source = _typed(action).get("source") if action is not None else None
    if source == SHIFT_POSITION:
        return moved_ft(engine, actor) <= 5
    if source == REST_HOLD_ID:
        return bool(grappled_by(engine, actor)) and not any(c.condition_id == REST_HOLD for c in actor.conditions.values())
    return None


@hook("ai_candidate_allowed")
def stillness_ai(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    # Nothing to regain: a Bonus Action the built-in AI would only burn (a player's menu keeps it).
    if action is not None and _typed(action).get("source") in (SHIFT_POSITION, REST_HOLD_ID) and int(actor.resources.get(FOCUS, 0)) >= 1:
        return False
    return None


@effect("hold_position")
def hold_position(ctx: Any, eff: dict[str, Any]) -> None:
    limit = int(eff.get("max_ft") or 5)
    room = max(0, limit - moved_ft(ctx.engine, ctx.actor))
    before = ctx.actor.movement_remaining_ft
    if before > room:
        ctx.actor.movement_remaining_ft = room
        ctx.engine._append_event("MOVEMENT_GRANTED", ctx.source, actor_id=ctx.actor.entity_id, payload={"distance_ft": room - before})
        ctx.rider(f"{ctx.actor.display_name} keeps to {limit} feet of movement this turn (the condition of the talent).")


@effect("rest_hold")
def rest_hold(ctx: Any, eff: dict[str, Any]) -> None:
    actor, engine = ctx.actor, ctx.engine
    held = grappled_by(engine, actor)
    if not held:
        ctx.rider("Rest Hold needs a creature you are grappling.")
        return
    cover = 5 if _has_close_quarters(engine, actor) else 2
    engine._apply_condition(actor, REST_HOLD, ctx.source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": f"Rest Hold ({'Three-Quarters' if cover == 5 else 'Half'} Cover, Speed 0)", "cover": cover,
                                  "held": held[0].entity_id})
    if actor.movement_remaining_ft:
        engine._append_event("MOVEMENT_GRANTED", ctx.source, actor_id=actor.entity_id, payload={"distance_ft": -actor.movement_remaining_ft})
        actor.movement_remaining_ft = 0
    if cover == 5:
        ctx.rider(f"Close Quarters Training: pull {held[0].display_name} into your space without a check (the map keeps them in adjacent "
                  "squares; the cover above is the part the table runs).")


@hook("cover")
def rest_hold_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    for condition in target.conditions.values():
        if condition.condition_id != REST_HOLD:
            continue
        held = engine.state.actors.get(str(condition.data.get("held") or ""))
        if held is None or not held.active or attacker.entity_id == held.entity_id:
            continue  # "against attacks made by creatures other than itself"
        if any(c.condition_id == GRAPPLED and c.source_actor_id == target.entity_id for c in held.conditions.values()):
            return int(condition.data.get("cover") or 2)
    return None
