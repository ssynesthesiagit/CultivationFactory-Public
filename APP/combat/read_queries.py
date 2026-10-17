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
_PASS = ContextVar('combat_enumeration_queries', default=None)
_PRESENTATION = ContextVar('combat_presentation_queries', default=None)


@contextmanager
def presentation_pass(engine):
    """Share pure answers during one read-only snapshot projection.

    The caller must keep state, actors, catalog and map unchanged. Never wrap
    candidate generation, execution or speculative positions with this scope.
    Nothing survives the projection or an exception; other engines are isolated.
    Existing pure-query callers outside this explicit scope are unchanged.
    """
    owner = _PRESENTATION.set(engine)
    try:
        frame = _FRAME.get()
        if frame is not None and frame[0] is engine and not frame[2]:
            yield
            return
        token = _FRAME.set((engine, {}, False))
        try:
            yield
        finally:
            _FRAME.reset(token)
    finally:
        _PRESENTATION.reset(owner)


def presentation_active(engine):
    """Whether this exact engine owns the explicit immutable presentation scope."""
    return _PRESENTATION.get() is engine


def presentation_memo(engine, key, compute):
    """Memoize immutable geometry only inside an explicit presentation pass.

    Used by zone membership and terrain rays. Native AI, execution, candidate
    enumeration and ordinary pure calls retain their existing query lifetimes.
    """
    return memo(engine, key, compute) if presentation_active(engine) else compute()


def presentation_grid_memo(grid, key, compute):
    """The same opt-in seam for geometry APIs that receive a grid, not an engine."""
    engine = _PRESENTATION.get()
    if engine is None or getattr(engine, 'grid', None) is not grid:
        return compute()
    return presentation_memo(engine, ('grid', id(grid), key), lambda: (grid, compute()))[1]


@contextmanager
def candidate_pass(engine):
    """Scope a read-only candidate pass through action_legality.observe.

    Only queries inside a shot_geometry action/origin frame share answers;
    setup/loadout/terrain phases outside those frames remain independent.
    Explicit invariant_memo/file_snapshot consumers have separate pass-wide
    caches and must obey their narrower invariant-input contracts.
    Never wrap execution or keep this scope across a recorded choice.
    """
    token = _FRAME.set((engine, {}, True))
    pass_token = _PASS.set((engine, {}, {}))
    try:
        yield
    finally:
        _PASS.reset(pass_token)
        _FRAME.reset(token)


def enumeration_cache(engine):
    """Transient cache for declared enumeration-invariant queries, or None.

    Unlike memo(), this spans action/origin frames. Consumers MUST be pure and
    include every temporarily projected input in their key, or depend only on
    unchanged catalog/map objects. Recorded changes and state replacement clear
    the cache. Unrecorded edits are observed by the next pass. No cache survives
    a menu, exception, transaction, reload, or crosses engine/preview identities.
    """
    frame = _PASS.get()
    if frame is None or frame[0] is not engine:
        return None
    state = engine.state
    revision = (id(state), state.state_version, state.event_sequence,
                id(engine.action_catalog))
    cache = frame[1]
    if cache.get('revision') != revision:
        cache.clear()
        cache['revision'] = revision
        # Retain identity-keyed inputs until invalidation: replacement followed
        # by collection must not let Python recycle a cached state/catalog ID.
        cache['state'] = state
        cache['catalog'] = engine.action_catalog
    return cache


def invariant_memo(engine, key, compute):
    """Memoize one explicitly invariant query within candidate_pass only.

    Never caches errors. Mutable results are private to the pure pass; consumers
    must copy containers before exposing them or use immutable query results.
    """
    cache = enumeration_cache(engine)
    if cache is None:
        return compute()
    if key not in cache:
        cache[key] = compute()
    return cache[key]


def file_snapshot(key, compute):
    """Read editable source once per enumeration/presentation; refresh next pass.

    Outside either explicit scope the reader retains its file-change checks.
    Files cannot change the rules halfway through a single menu. Path identity
    belongs in the key so isolated fixtures and changed reader paths stay apart.
    """
    frame = _PASS.get()
    if frame is None:
        engine = _PRESENTATION.get()
        if engine is not None:
            return presentation_memo(engine, ('file_snapshot', key), compute)
        return compute()
    cache = frame[2]
    if key not in cache:
        cache[key] = compute()
    return cache[key]


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
