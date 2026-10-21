"""Native state-event delivery for Gate2 and its Gate3/Gate4 consumers.

Condition lifecycle plug-ins use this checkpoint without depending on Gate4's
separate controller event notifications. No subscribers means no effects.
"""
from . import ext


def dispatch(engine, event):
    """Deliver a recorded event exactly once; strict nested calls are bounded."""
    depth = getattr(engine, '_state_event_depth', 0)
    if depth >= 8:
        raise ext.CheckpointError('An effect repeated too many times; the action was cancelled.')
    engine._state_event_depth = depth + 1
    try:
        ext.run_checkpoint('state_event', engine, event)
        if event.event_type == 'REACTION_RESOLVED':
            actor = engine.state.actors.get(event.actor_id)
            if actor is not None:
                reaction_completed(engine, actor, event.source_definition_id)
    finally:
        engine._state_event_depth = depth


def reaction_completed(engine, actor, source_definition_id):
    """Strict completion for native receipts and finalized d20 reactions.

    Call after the reaction's result and riders resolve, never at payment.
    Does not publish another receipt or spend economy. Choice pauses roll back
    the enclosing transaction; absent subscribers leave resolution unchanged.
    """
    ext.run_checkpoint('reaction_completed', engine, actor, source_definition_id)
