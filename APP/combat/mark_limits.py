"""Capacity eviction shared by typed creature marks and Thread object marks.

Each condition instance occupies one slot, even when multiple object connections
live on one bearer. Placement callers remove their refreshed instances first.
"""


def reserve_mark_slot(engine, condition_ids, capacity, source):
    """End the oldest excess instances before adding one mark; no cap is inert.

    ``condition_ids`` is the caller's source-owned mark family. Exact-instance
    removal preserves newer marks of that family on the same bearer and journals
    the ordinary removal event for lifecycle subscribers and replay.
    """
    if not capacity:
        return
    placed = sorted(((c.applied_sequence, bearer, c)
                     for bearer in engine.state.actors.values()
                     for c in bearer.conditions.values() if c.condition_id in condition_ids),
                    key=lambda row: row[0])
    for _, bearer, oldest in placed[:max(0, len(placed) - int(capacity) + 1)]:
        engine._remove_condition_instance(bearer, oldest.instance_id, source)
