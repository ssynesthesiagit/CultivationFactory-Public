"""Transient trigger transport shared by d20 consent and service previews.

The scope covers one consent call, including exceptions; no fight state or
events change. Providers without an active scope keep their original request.
"""
from contextlib import contextmanager


def current_trigger(engine):
    """Pure snapshot of the actual nested native trigger, or None.

    Forced-movement callers may publish source_cl and ignores_bodily_anchoring
    from their resolving Context. Consumers must not infer those facts from a
    creature's name, team, or an unrelated active action.
    """
    current = getattr(engine, "_reaction_trigger", None)
    return dict(current) if current is not None else None


@contextmanager
def trigger_scope(engine, checkpoint, *, actor_id=None, target_id=None, source_id=None, roll_kind=None, action_name=None, **details):
    previous = getattr(engine, "_reaction_trigger", None)
    engine._reaction_trigger = {
        "checkpoint": checkpoint, "actor_id": actor_id, "target_id": target_id,
        "source_definition_id": source_id, "roll_kind": roll_kind, **details,
    }
    if action_name:
        engine._reaction_trigger['action_name'] = str(action_name)
    try:
        yield
    finally:
        if previous is None:
            engine.__dict__.pop("_reaction_trigger", None)
        else:
            engine._reaction_trigger = previous


def contextual_request(engine, request):
    """Enrich only the currently scoped checkpoint, preserving answer keys."""
    trigger = getattr(engine, "_reaction_trigger", None)
    if not trigger or request["checkpoint"].split("@", 1)[0] not in (
            trigger["checkpoint"], "TYPED:" + trigger["checkpoint"]):
        return request
    return {**request, "attacking_actor_id": trigger["actor_id"],
            "protected_target_id": trigger["target_id"],
            "choice_trigger": {**(request.get("choice_trigger") or {}), **trigger,
                               "action_actor_id": trigger["actor_id"]}}
