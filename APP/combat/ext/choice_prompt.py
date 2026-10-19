"""Display-only choice context shared by Needle, Footwork, Thread correction, soul-return consent and rider menus."""
from contextlib import contextmanager
from typing import Any


def action_context(engine: Any, actor: Any, source_id: str, target: Any, *, action: Any = None) -> dict[str, str]:
    """Identify the actual triggering action, its actor and affected creature.

    Explicit action supports a reaction Context whose action is built at resolution
    time and absent from the sealed catalog (Drunken Style hit-rider prompts).
    Strings only; no decision, cost or event changes. Callers with a reaction
    action must pass that action rather than the outer turn's intent.
    """
    action = action if action is not None else engine.action_catalog.get(source_id)
    return {"source_definition_id": source_id,
            "action_name": str(action.display_name if action else ""),
            "action_actor_id": str(actor.entity_id if actor else ""),
            "affected_id": str(target.entity_id)}


def resource_gain_context(engine: Any, source_id: str, affected: Any) -> dict[str, str]:
    """Display provenance for a gain, including suffixed payment/upkeep sources.

    A gain scoped by its caller keeps that caller's actual action. Otherwise
    resolve the longest catalog source prefix; never guess from the outer intent.
    """
    scoped = getattr(engine, "_resource_gain_context", None)
    if scoped is not None and scoped[0] == source_id:
        return {**scoped[1], "affected_id": str(affected.entity_id)}
    action = max((a for key, a in engine.action_catalog.items()
                  if source_id == key or source_id.startswith(key + ".")),
                 key=lambda a: len(a.source_definition_id), default=None)
    actor = engine.state.actors.get(action.owner_id) if action else None
    return action_context(engine, actor, action.source_definition_id if action else source_id, affected)



@contextmanager
def resource_gain_scope(ctx: Any, source_id: str):
    """Keep nested gain provenance local to the actual action; restore on pause."""
    engine = ctx.engine
    previous = getattr(engine, "_resource_gain_context", None)
    engine._resource_gain_context = (source_id, action_context(engine, ctx.actor, ctx.action.source_definition_id, ctx.actor))
    try:
        yield
    finally:
        if previous is None:
            del engine._resource_gain_context
        else:
            engine._resource_gain_context = previous
