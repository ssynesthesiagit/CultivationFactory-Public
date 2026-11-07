"""Transient physical-collision provenance for nested native damage packets.

Typed forced movement and pending_damage share this context. No rules or damage
are invented here: the collision callback decides whether a collision hurts.
Only damage to the actual mover from the colliding action receives these flags.
"""
from contextlib import contextmanager
from itertools import combinations


def kind(engine, target, blocked_at):
    """Classify the same crossed volumes used by the native step validator.

    A creature blocking a diagonal side cell is still a creature collision.
    Shared occupancy permissions remain in force; a map boundary is not proof
    of a physical object or surface.
    """
    from .space import point, volume
    if not engine.grid.in_bounds((blocked_at.x, blocked_at.y)):
        return "collision_unclassified"
    start, end = point(target.position), point(blocked_at)
    axes = [i for i in range(3) if start[i] != end[i]]
    if not axes:
        return "collision_unclassified"  # a clamped map edge is not a solid surface
    swept = set()
    for count in range(1, len(axes) + 1):
        for selected in combinations(axes, count):
            anchor = tuple(end[i] if i in selected else start[i] for i in range(3))
            swept.update(volume(anchor, engine._footprint(target)))
    if swept.intersection(engine._occupied_volumes_except(target.entity_id)):
        return "collision_with_creature"
    return "collision_with_object_or_surface"


@contextmanager
def scope(engine, target_id, source_id, kind):
    old = getattr(engine, "_physical_collision", None)
    engine._physical_collision = (target_id, source_id, kind)
    try:
        yield
    finally:
        engine._physical_collision = old


def flags(engine, target_id, source_id):
    frame = getattr(engine, "_physical_collision", None)
    return frozenset({frame[2]}) if frame and frame[:2] == (target_id, source_id) else frozenset()
