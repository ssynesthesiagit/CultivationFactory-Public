"""Owned Water area queries shared by Living Current, Water Shield and Pull.

``areas(engine, owner)`` returns active Shape Current areas created by that actor,
never foreign water or a spiritual Court. ``contains`` uses the full creature
volume; ``distance`` measures from a body to the nearest actual effect cell.
``beside`` includes membership (Living Current's explicit permission), matching
existing Water consumers' within-one-square convention. Queries are pure; absent
owned areas produce an empty list/False. No ownership, resource or clock is stored.
"""
from ..space import point

SHAPE = 'WATER_BASE_SHAPE_CURRENT'


def areas(engine, owner):
    return [z for z in engine.state.zones.values() if z.active and z.owner_id == owner.entity_id
            and source(engine, z) == SHAPE]


def source(engine, zone):
    action = engine.action_catalog.get(zone.source_definition_id)
    return ((getattr(action, 'parameters', None) or {}).get('typed') or {}).get('source')


def contains(engine, owner, zone, creature):
    return (zone.active and zone.owner_id == owner.entity_id and source(engine, zone) == SHAPE
            and bool(set(engine._actor_volume(creature)) & {point(p) for p in zone.affected_cells}))


def distance(engine, owner, zone, creature):
    if not zone.active or zone.owner_id != owner.entity_id or source(engine, zone) != SHAPE:
        return None
    return engine.grid.distance_between_cell_sets_ft(engine._actor_volume(creature),
                                                    {point(p) for p in zone.affected_cells})


def beside(engine, owner, creature):
    return any((feet := distance(engine, owner, z, creature)) is not None and feet <= 5
               for z in areas(engine, owner))
