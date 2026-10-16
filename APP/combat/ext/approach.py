"""Moved toward the target this turn (owner 2026-09-28: "make sure all the talents ... is applied"). Forward Cut (Sabers,
12 characters): "If you moved at least 10 feet toward the target this turn, add your Proficiency Bonus to the damage roll." It was
a GM line ("the table does not track approach distance"); the table does log every move, so it is counted here.

Effect {"type": "if_approached", "min_ft": 10, "add_pb_to_weapon_damage": true, "effects": [...]}: for this activation's
own target, when the actor's own willing movement this turn (MOVEMENT_COMMITTED since its TURN_STARTED; forced moves
don't count) brought it closer to that target by at least min_ft -- counted square by square: each square stepped that
ended nearer to the target's current place adds that square's feet -- deals + PB of the weapon's damage type
(add_pb_to_weapon_damage) and runs its effects.

Shared public readers: ``approached_ft`` (feet closed on a target this turn) and ``moved_before_attack_ft`` (feet walked right
before the attack resolving now). Used by combat/ext/martial_insights.py (Avalanche Shoulder, Sword-Line Meridian).
"""

from __future__ import annotations

from typing import Any

from . import effect


def approached_ft(engine: Any, actor: Any, target: Any) -> int:
    from ..gate2_runtime_models import Position

    moves = []
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED" and event.actor_id == actor.entity_id:
            break
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and not (event.payload or {}).get("forced"):
            moves.append(event.payload or {})
    total = 0
    for payload in reversed(moves):
        path = [Position(**cell) for cell in payload.get("path") or [] if isinstance(cell, dict)]
        for before, after in zip(path, path[1:]):
            if engine._distance_actor_to_actor(actor, target, actor_position=after) < engine._distance_actor_to_actor(actor, target, actor_position=before):
                total += engine.grid.square_size_ft
    return total


def moved_before_attack_ft(engine: Any, actor: Any) -> int:
    """Feet the actor walked immediately before the attack now resolving ("when you voluntarily move at least 10 feet
    immediately before an ... attack": Sword-Line Meridian, combat/ext/martial_insights.py).

    Read back from the end of the log: the actor's own willing MOVEMENT_COMMITTED steps (not forced, not teleport)
    count until the actor's previous attack roll, a non-movement intent before the current one, or its TURN_STARTED.
    The current attack's own roll and intent are skipped, so a run-up then a strike counts, while a strike, a move and a
    second strike counts only the move between them. Pure read of recorded events; no state."""
    total, attacks, intents = 0, 0, 0
    for event in reversed(engine.events):
        if event.actor_id != actor.entity_id:
            continue
        payload = event.payload or {}
        if event.event_type == "TURN_STARTED":
            break
        if event.event_type == "ATTACK_ROLLED":
            attacks += 1
            if attacks > 1:
                break
        elif event.event_type == "INTENT_ACCEPTED" and payload.get("kind") != "MOVE":
            intents += 1
            if intents > 1:
                break
        elif event.event_type == "MOVEMENT_COMMITTED" and not payload.get("forced") and not payload.get("teleport"):
            total += max(0, len(payload.get("path") or []) - 1) * engine.grid.square_size_ft
    return total


@effect("if_approached")
def if_approached(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    need = int(eff.get("min_ft") or 10)
    for subject in ([ctx.target] if ctx.target is not None else list(ctx.targets)):
        if subject is None or not subject.active or approached_ft(ctx.engine, ctx.actor, subject) < need:
            continue
        inner = typed_executor.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject, ctx.damage_cache)
        if eff.get("add_pb_to_weapon_damage"):  # "add your Proficiency Bonus to the damage roll": the weapon's own type
            weapon = ctx.typed.get("weapon") or {}
            kind = typed_executor.choose_damage_type(inner, typed_executor.damage_choices({}, weapon), [subject])
            ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                                     payload={"trigger": f"moved {need}+ feet toward the target: + Proficiency Bonus damage"})
            typed_executor._deal(inner, subject, int(ctx.numbers.get("pb") or 2), kind)
        typed_executor.run_effects(inner, eff.get("effects") or [])
