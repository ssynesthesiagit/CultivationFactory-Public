"""Native state-event delivery for Gate2 and its Gate3/Gate4 consumers.

Condition lifecycle plug-ins use this checkpoint without depending on Gate4's
separate controller event notifications. No subscribers means no effects.
"""
from . import ext
from contextlib import contextmanager


@contextmanager
def restoring_graph(engine):
    """Delay lifecycle validation until an explicitly restored graph is whole.

    Source continuation restores interdependent condition/object identities for
    Ink, Thread and presentation grants. Events are still recorded normally;
    lifecycle observers receive each receipt once, against the complete graph.
    Ordinary action/turn dispatch is unchanged. Nested restorations share the
    outer buffer, and an aborted restoration publishes no lifecycle callbacks.
    """
    if getattr(engine,'_restoring_state_events',None) is not None:
        yield
        return
    engine._restoring_state_events=[]
    try:
        yield
        pending=engine._restoring_state_events
    except BaseException:
        engine.__dict__.pop('_restoring_state_events',None)
        raise
    engine.__dict__.pop('_restoring_state_events',None)
    for event in pending:dispatch(engine,event)


def dispatch(engine, event):
    """Deliver a recorded event exactly once; strict nested calls are bounded."""
    pending=getattr(engine,'_restoring_state_events',None)
    if pending is not None:
        pending.append(event)
        return
    depth = getattr(engine, '_state_event_depth', 0)
    if depth >= 8:
        raise ext.CheckpointError('An effect repeated too many times; the action was cancelled.')
    engine._state_event_depth = depth + 1
    try:
        ext.run_checkpoint('state_event', engine, event)
    finally:
        engine._state_event_depth = depth
