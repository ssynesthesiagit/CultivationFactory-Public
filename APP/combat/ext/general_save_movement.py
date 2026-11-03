"""Opt-in immediate rider steps with bounded native movement and sight.

``general_rider_step`` reuses the shared rider_step effect's player choice,
ordinary-pool isolation, native hazards and no-opportunity-attack scope.  A row
may additionally require a visible destination.  That restriction is applied
only while this effect enumerates its own movement candidates, through the
existing candidate_allowed hook.  It never changes a character's later moves.

Repeat-save rider data needs no new runtime listener: condition/ongoing rows
already store a save DC and the locked native end-turn checkpoint removes
exactly the successful condition instance.  No saved-fight format is changed.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from . import effect, hook

_VISIBLE_STEP: ContextVar[tuple[int, str, str] | None] = ContextVar(
    "general_rider_visible_step", default=None
)


@effect("general_rider_step")
def step(ctx: Any, row: dict[str, Any]) -> None:
    """Execute a new typed self step; old ``movement`` and ``rider_step`` rows are inert here."""
    from .rider_step import step as native_step

    token = None
    try:
        if row.get("visible_destination"):
            token = _VISIBLE_STEP.set((id(ctx.engine), ctx.actor.entity_id, ctx.source))
        native_step(ctx, row)
    finally:
        if token is not None:
            _VISIBLE_STEP.reset(token)


@hook("candidate_allowed")
def visible_destination(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    scope = _VISIBLE_STEP.get()
    if scope != (id(engine), actor.entity_id, candidate.source_definition_id) \
            or action is not None or candidate.kind != "MOVE" or candidate.destination is None:
        return None
    from .. import senses, zones

    p = candidate.destination
    if not engine._line_of_sight_actor_to_cell(actor, p):
        return False
    # Restrict only visibility. Native granted candidates already preserve
    # altitude, footprint, path and observed occupancy. Re-enumerating teleport
    # destinations would flatten flight and disclose an unseen occupant.
    seen = actor.model_copy(update={"position": p, "conditions": {}})
    blinded_conditions = set(senses.rules().get("blinded_conditions") or [])
    blinded = any(c.condition_id in blinded_conditions for c in actor.conditions.values())
    if blinded and not senses.perceives_without_sight(engine, actor, seen):
        return False
    return False if zones.hidden_from(engine, actor, seen) else None
