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
    finally:
        engine._state_event_depth = depth
