"""Shared active-turn willing-distance query for typed_reactions; no hooks or state.

MOVEMENT_COMMITTED receipt keys that readers rely on:
  path          squares the mover stood on, including any forced leg at the end.
  forced        True only for a forced move (no willing movement at all).
  teleport      True for a teleport (no physical distance).
  forced_steps  count of trailing squares of path that are a forced leg (a Deny Passage separation);
                they are not willing movement. Present only when non-zero.
  separation    True when the receipt includes a Deny Passage separation leg.
Every willing-distance reader counts through willing_route / willing_squares / willing_feet.
"""
from ..gate2_runtime_models import Position


def willing_route(payload):
    """The squares a MOVEMENT_COMMITTED receipt says the mover walked by its own choice.

    The receipt's last ``forced_steps`` squares are a forced leg (a Deny Passage separation); they are not willing.
    """
    path=[Position.model_validate(c) for c in payload.get('path') or []]
    forced=int(payload.get('forced_steps') or 0)
    return path[:len(path)-forced] if forced else path


def willing_distance(engine,actor):
    """Physical movement since the most recent turn began, including off-turn movers.

    Forced movement and teleports do not spend physical distance. Queries are
    pure; native recorded movement events own committed distances and rollback.
    """
    total=0
    for event in reversed(engine.events):
        if event.event_type=='TURN_STARTED':break
        p=event.payload or {}
        if event.event_type!='MOVEMENT_COMMITTED' or event.actor_id!=actor.entity_id or p.get('forced') or p.get('teleport'):
            continue
        path=willing_route(p)
        total+=sum(engine.grid.distance_ft(a,b) for a,b in zip(path,path[1:]))
    return total


def willing_squares(payload):
    """Squares of willing movement in a MOVEMENT_COMMITTED receipt (the forced separation leg is not counted)."""
    return max(0, len(willing_route(payload or {})) - 1)


def willing_feet(engine, payload):
    """Feet of willing movement in a MOVEMENT_COMMITTED receipt; every willing-distance reader uses this one count."""
    return willing_squares(payload) * engine.grid.square_size_ft
