"""Call-local memoization for pure targeting and perception queries.

Used by target_knowledge, targeting, senses, zones and flight route searches.
An outer pure query
owns the frame; nested queries on the same engine share it. Nothing survives
the outer call, including exceptions. Execution, reactions and later candidate
queries never inherit answers from an earlier call. Providers must obey the
existing pure-query contract (no state/input mutations during a query).
"""
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps

_FRAME = ContextVar('combat_read_queries', default=None)


@contextmanager
def candidate_pass(engine):
    """Scope a read-only candidate pass through the existing unlocked callers.

    action_legality.observe and saved_fight_compat's binding validation use this.
    Only queries inside a shot_geometry action/origin frame share answers;
    setup/loadout/terrain phases outside those frames remain independent.
    Never wrap execution or keep this scope across a recorded choice.
    """
    token = _FRAME.set((engine, {}, True))
    try:
        yield
    finally:
        _FRAME.reset(token)


def pure(function):
    """Give one synchronous pure query a fresh, context-local memo frame."""
    @wraps(function)
    def query(engine, *args, **kwargs):
        frame = _FRAME.get()
        if (frame is not None and frame[0] is engine
                and (not frame[2] or getattr(engine, '_shot_geometry', None) is not None)):
            return function(engine, *args, **kwargs)
        token = _FRAME.set((engine, {}, False))
        try:
            return function(engine, *args, **kwargs)
        finally:
            _FRAME.reset(token)
    return query


def memo(engine, key, compute):
    """Reuse a derived value only inside an active pure call on this engine.

    Keys include the queried actor objects, not just IDs: projected footprints
    with the same ID are different inputs. Mutable containers must be copied
    by the consumer before handing them to its caller.
    """
    frame = _FRAME.get()
    if frame is None or frame[0] is not engine:
        return compute()
    cache = frame[1]
    state = getattr(engine, 'state', None)
    key = (getattr(state, 'state_version', None), getattr(state, 'event_sequence', None), key)
    if frame[2]:
        shot = getattr(engine, '_shot_geometry', None)
        if shot is None:
            return compute()
        # The engine creates a fresh shot frame for every action/origin. Hold
        # it alive to prevent id recycling, and invalidate on recorded changes.
        cache.setdefault(('shot_frame', id(shot)), shot)
        key = (id(shot), key)
    if key not in cache:
        cache[key] = compute()
    return cache[key]
