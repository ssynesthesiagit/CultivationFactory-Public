"""General source-scoped temporary suppression of one named resource pool.

Consumers: every source whose printed text suppresses a counted pool for a
stated time instead of removing it -- Bell Purifying Peal suppresses one point of
temporary Corruption until scene end, and any later source may use the same seam.
A provider names the exact pool it suppresses; nothing here is keyed on a pool or
an ability id, and there is no provider at all until a source opts in.

``resource_suppressed(engine, actor, resource_id) -> int | None``
    Default-inert pure hook. A provider returns the nonnegative number of points
    suppressed from ``resource_id`` for ``actor`` while its own printed grant is
    live. ``None`` means "no opinion". A malformed reply fails closed by raising,
    because a bad suppression would silently change a printed consequence.

``effective_value(engine, actor, resource_id) -> int | None``
    The number a consequence must read: the stored amount minus every live
    suppression, never below zero. A pool the actor does not carry returns None;
    a pool nobody suppresses returns the stored amount unchanged.

Suppression deliberately never writes ``actor.resources``. The stored amount stays
the truth and only the value consequences observe is lowered, so ending a grant
restores the printed amount without an invented refund or a hidden second ledger.
"""
from . import run_strict


def suppressed_points(engine, actor, resource_id):
    """Total live suppression for one pool; strict so a bad provider cannot lie."""
    total = 0
    for reply in run_strict('resource_suppressed', engine, actor, resource_id):
        if type(reply) is not int or reply < 0:
            raise ValueError('resource_suppressed must return a nonnegative integer or None')
        total += reply
    return total


def effective_value(engine, actor, resource_id):
    """Stored pool minus live suppression, floored at zero; None when uncarried."""
    stored = actor.resources.get(resource_id)
    if stored is None:
        return None
    return max(0, int(stored) - suppressed_points(engine, actor, resource_id))
