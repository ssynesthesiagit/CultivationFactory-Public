"""Shared active-turn willing-distance query for typed_reactions; no hooks or state."""
from ..gate2_runtime_models import Position


def physical_distance(engine,actor,*,include_forced=False):
    """Physical movement since the most recent turn began, including off-turn movers.

    Forced movement and teleports do not spend physical distance. Queries are
    pure; native recorded movement events own committed distances and rollback.
    """
    total=0
    for event in reversed(engine.events):
        if event.event_type=='TURN_STARTED':break
        p=event.payload or {}
        if event.event_type!='MOVEMENT_COMMITTED' or event.actor_id!=actor.entity_id or (p.get('forced') and not include_forced) or p.get('teleport'):
            continue
        path=[Position.model_validate(c) for c in p.get('path') or []]
        total+=sum(engine.grid.distance_ft(a,b) for a,b in zip(path,path[1:]))
    return total


def willing_distance(engine,actor):
    """Backward-compatible voluntary physical distance, excluding teleportation."""
    return physical_distance(engine,actor)
