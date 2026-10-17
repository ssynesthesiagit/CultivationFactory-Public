"""Volume membership for areas; stored cells remain compact drawing projections."""
from collections import deque
from itertools import product

from .space import point, position


def reaches(engine, vertex, aim, destination, area):
    from .typed_executor import in_area
    if not in_area(engine, vertex, aim, destination, area):
        return False
    if not area.get('spreads'):
        return True
    if not (vertex.z or aim.z or destination.z or engine.grid.finite_heights):
        from .area_projection import cells as area_cells
        return destination in area_cells(engine, vertex, aim, area)
    # Only height-aware spreading needs volume search. Ordinary legacy darkness
    # keeps its cached plane projection; this search ends as soon as it connects.
    start, target = point(aim), point(destination)
    queue, seen = deque([start]), {start}
    offsets = tuple(d for d in product((-1, 0, 1), repeat=3) if any(d))
    while queue:
        cell = queue.popleft()
        if cell == target:
            return True
        for delta in offsets:
            nxt = tuple(a+b for a, b in zip(cell, delta))
            if nxt in seen or min(nxt) < 0 or nxt[0] >= engine.grid.width or nxt[1] >= engine.grid.height:
                continue
            seen.add(nxt)
            dest = position(nxt)
            if in_area(engine, vertex, aim, dest, area) and engine.grid.volume_step_legal(cell, nxt):
                queue.append(nxt)
    return False


def actor_in_area(engine, actor, vertex, aim, area, *, at=None):
    """Pure volume membership, shared by targeting, area risk and zone queries.

    A preview may ask again for each effect/save branch at the same placement.
    Reuse only in a read frame; actor_positions retains the actor object.
    Actor projections, explicit positions, vertices and aims stay distinct.
    Geometry specification is bound once per object; holding it prevents ID
    recycling. Recipient filters are applied by the caller, not by reaches.
    The pure-query contract forbids spec mutations during the frame.
    """
    from .read_queries import memo
    from .area_projection import geometry_key
    geometry = memo(engine, ('area_signature', id(area)), lambda: (area, geometry_key(area)))[1]
    key = ('area_member', id(actor), point(actor.position), geometry, point(vertex), point(aim),
           point(at) if at is not None else None)
    return memo(engine, key, lambda: any(reaches(engine, vertex, aim, cell, area)
                                        for cell in actor_positions(engine, actor, at=at)))


def actor_positions(engine, actor, *, at=None):
    """Index immutable volume positions within one pure geometry query.

    Area previews and terrain membership share this helper. Explicit projected
    origins stay separate; outside a read frame every call computes afresh.
    No Position or footprint is retained in saved state.
    """
    from .read_queries import memo
    memo(engine, ('volume_actor', id(actor)), lambda: actor)
    key = ('volume_positions', id(actor), point(actor.position),
           point(at) if at is not None else None)
    from .volume_queries import positions
    return memo(engine, key, lambda: positions(engine._actor_volume(actor, at), position))


def zone_contains(engine, actor, zone, *, at=None):
    spec = zone.trigger_profile
    # A saved block owns its recorded horizontal footprint, including legacy
    # cubes. New blocks already record the half-open grid geometry. Altitude
    # uses the block's size; radial membership is a separate rule below.
    if spec.get('shape') in ('cube', 'square') and spec.get('size_ft'):
        columns = {(cell.x, cell.y) for cell in zone.affected_cells}
        half = int(spec['size_ft']) / 2
        return any((x, y) in columns and -half <= (z-zone.center.z)*engine.grid.square_size_ft < half
                   for x, y, z in engine._actor_volume(actor, at))
    # Painted terrain and explicit zero-radius footprints own their recorded
    # cells. A copied ability profile must not expand those cells into a sphere.
    if (zone.radius_cells > 0 and spec.get('shape') not in (None, 'wall', 'painted')
            and spec.get('size_ft')):
        vertex = position(spec.get('area_vertex', point(zone.center)))
        return actor_in_area(engine, actor, vertex, zone.center, spec, at=at)
    # Explicit painted terrain stays on its stated plane. Radius-backed native
    # zones and plug-in auras also extend above/below the recorded center.
    columns = {(cell.x, cell.y) for cell in zone.affected_cells}
    if spec.get('wall'):
        height = spec['wall'].get('height_ft')
        base = spec['wall'].get('base_altitude_ft', zone.center.z*5)
        return any((x,y) in columns and (height is None or base <= z*5 < base+height)
                   for x,y,z in engine._actor_volume(actor, at))
    radius = zone.radius_cells
    return any((x,y) in columns and abs(z-zone.center.z) <= radius
               for x,y,z in engine._actor_volume(actor, at))


def display_cells(engine, zone):
    """Effective plane footprint for Table shading, including continued old zones.

    Stored cells and journals remain untouched. Round zones use current radial
    geometry; cubes, squares, explicit paint and walls retain recorded cells.
    The continuation dialog already discloses changed engine behavior.
    """
    spec = zone.trigger_profile
    if (zone.radius_cells > 0 and spec.get('shape') not in (None, 'wall', 'painted', 'cube', 'square')
            and spec.get('size_ft')):
        from .typed_executor import area_cells
        vertex = position(spec.get('area_vertex', point(zone.center)))
        return area_cells(engine, vertex, zone.center, spec)
    return zone.affected_cells


def difficult_at(engine, actor, destination):
    """Volumetric difficult areas affect flying movement; ground paint does not.

    Route searches price many edges entering the same cell. Reuse its boolean
    only in the existing read frame, keyed by state version/event sequence in
    read_queries.memo and by actor object, actual origin and destination here.
    Outside a read query (including execution), always compute afresh.
    """
    from .read_queries import memo
    return memo(engine, ('area_difficult', id(actor), point(actor.position), point(destination)),
                lambda: (actor, _difficult_at(engine, actor, destination)))[1]


def _difficult_at(engine, actor, destination):
    from . import zones
    from .motion import exempt_cells, ignores_area_difficult
    if ignores_area_difficult(engine, actor):
        return False
    # These are ground an ability made, so only a benefit that ignores ALL difficult terrain reaches it (the
    # "magical" scope); Death's Court of the Ninth Grave says "nonmagical" and does not (combat/motion.py exempt_cells).
    if (destination.x, destination.y) in exempt_cells(engine, actor, terrain="magical"):
        return False
    for zone in zones.typed_zones(engine):
        spec = zone.trigger_profile
        if not spec.get('shape') or zone.owner_id == zones.MAP_OWNER:
            continue
        owner = engine.state.actors.get(zone.owner_id)
        hostile = owner is not None and owner.team_id != actor.team_id
        if (spec.get('difficult') == 'all' or spec.get('difficult') == 'hostile' and hostile) and zone_contains(engine, actor, zone, at=destination):
            return True
    return False
