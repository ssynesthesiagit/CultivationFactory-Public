"""Opt-in timed concentration: shared by explicit limit_concentration_duration effects
and new bundles' sealed unlimited-capacity contract (technique_used).

The deadline uses the existing slot clock and records the concentration copy's
start sequence. Only that copy ends at its deadline, including held copies; its
normal concentration cleanup removes dependent effects. Early loss removes the
deadline too. Old bundles without either opt-in retain their existing behavior.
"""
from typing import Any

from . import effect, hook
from .. import concentration

DEADLINE = "condition:typed.concentration_deadline"


@hook("history_event_metadata")
def deadline_history(event: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Hide this plug-in's timer, including legacy and transient journal rows.

    This is a presentation adapter only: it never changes stored events or the
    reducer's transient reconstruction. Real Concentration effects stay visible.
    """
    if event.get("event_type") in {"CONDITION_APPLIED", "CONDITION_REMOVED"} and (
            event.get("payload") or {}).get("condition_id") == DEADLINE:
        return {"history_hidden": True}
    return None


@hook("status_description")
def deadline_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    if row.get("condition_id") != DEADLINE:
        return None
    return {"text": "Tracks the maximum duration of this copy of a Concentration technique. When due, that copy and its dependent effects end.",
            "handling": "The table ends this copy automatically at its deadline or when its Concentration ends."}


def remove(engine, actor, iid):
    row = actor.conditions.get(iid)
    if row is not None:
        engine._remove_condition_instance(actor, iid, row.source_definition_id, actor_id=actor.entity_id,
            payload={"condition_id": row.condition_id, "instance_id": iid,
                     "gate3_condition_before": row.model_dump(mode="json")}, expected=row)


@effect("limit_concentration_duration")
def limit_duration(ctx: Any, effect_row: dict[str, Any]) -> None:
    """Shared application path for the explicit effect and the new-bundle hook."""
    from ..typed_executor import duration_expiry

    current = ctx.actor.concentration
    if current is None or current.source_definition_id != ctx.source:
        return
    if any(row.condition_id == DEADLINE and row.data.get("started_sequence") == current.started_sequence
           for row in ctx.actor.conditions.values()):
        return
    deadline = duration_expiry(ctx.engine, ctx.typed.get("duration") or {})
    if not deadline or deadline == "UNTIL_REMOVED":
        return
    ctx.engine._apply_condition(ctx.actor, DEADLINE, ctx.source, ctx.actor.entity_id,
                                expires_on=deadline, data={"started_sequence": int(current.started_sequence), "hidden": True})


@hook("technique_used")
def timed_copy(ctx: Any) -> None:
    """New contracts enforce each copy's rounds/minutes through the shared slot clock."""
    duration = ctx.typed.get("duration") or {}
    if not duration.get("concentration") or duration.get("kind") not in {"rounds", "minutes"}:
        return
    bundle = next((row for row in getattr(ctx.engine, "typed_bundle_documents", ()) or ()
                   if row.get("actor_id") == ctx.actor.entity_id), None)
    if (bundle or {}).get("concentration_rules", {}).get("capacity") == "unlimited":
        limit_duration(ctx, {})


@hook("event")
def concentration_ended(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONCENTRATION_ENDED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None:
        return
    started = (kwargs.get("payload") or {}).get("started_sequence")
    for iid, row in list(actor.conditions.items()):
        if row.condition_id == DEADLINE and row.data.get("started_sequence") == started:
            remove(engine, actor, iid)


@hook("effect_expiring")
def expire(engine: Any, owner: Any, row: Any) -> None:
    if getattr(row, "condition_id", None) != DEADLINE:
        return
    started = row.data.get("started_sequence")
    if started is not None:
        # The shared ending dispatcher delivers the normal subscribers for
        # current and held copies, including when a turn hook reaches this timer.
        concentration.end_copy(engine, owner, int(started), "DURATION_ENDED")
