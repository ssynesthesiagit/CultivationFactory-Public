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


@contextmanager
def read_frame(engine):
    """Open one read-only memo frame for a multi-step pure query.

    Use when one query visits many projected positions of the same creature
    (for example every flight route endpoint) and must share facts that do not
    depend on the position, such as condition rows or flight grants. A caller
    already inside a plain frame for this engine keeps it; a candidate pass'
    shot-scoped frame is not reused. Nothing survives the block.
    """
    frame = _FRAME.get()
    if frame is not None and frame[0] is engine and not frame[2]:
        yield
        return
    token = _FRAME.set((engine, {}, False))
    try:
        yield
    finally:
        _FRAME.reset(token)


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


def shared_query(engine, key, compute, *, refs=()):
    """Share one pure answer across a candidate pass, else within the pure frame.

    Some facts (Speed, flight capability, zone membership) do not depend on the
    action or origin frame at all, but candidate enumeration asks them for every
    square and every option root. Inside a candidate pass this uses the
    pass-wide invariant cache; otherwise it uses the ordinary ``memo`` frame, and
    with neither it simply computes. Consumers must include every projected
    input in ``key`` and pass any projected objects in ``refs``.
    """
    if enumeration_cache(engine) is not None:
        return invariant_query(engine, key, compute, refs=refs)
    return memo(engine, key, compute)


def invariant_query(engine, key, compute, *, refs=()):
    """Share one pure answer across every action/origin frame in a candidate pass.

    ``invariant_memo`` is enough when a query depends only on saved state and the
    catalog. Perception also depends on which creature objects are projected
    where, so callers pass those objects in ``refs`` and include their projected
    positions and identity in ``key``. Holding the objects keeps a short-lived
    projection's identity from being recycled inside the pass. Outside a
    candidate pass, or after a recorded state change, the query computes afresh.
    Consumers must be pure and must name every projected input in ``key``.
    """
    cache = enumeration_cache(engine)
    if cache is None:
        return compute()
    for obj in refs:
        cache.setdefault(('invariant_ref', id(obj)), obj)
    if key not in cache:
        cache[key] = compute()
    return cache[key]


def file_snapshot(key, compute):
    """Read editable source once per enumeration; refresh on the next pass.

    Outside enumeration the reader retains its ordinary file-change checks.
    Files cannot change the rules halfway through a single menu. Path identity
    belongs in the key so isolated fixtures and changed reader paths stay apart.
    """
    frame = _PASS.get()
    if frame is None:
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
