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
    from .spread_areas import reaches as spread_reaches
    return spread_reaches(engine, vertex, aim, destination, area, _spread_reaches)


def _spread_reaches(engine, vertex, aim, destination, area):
    """Uncached reference for grids outside the native pure-data contract."""
    from .typed_executor import in_area
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
    if getattr(actor,'perception_cell',False):
        return (at or actor.position,)
    from .read_queries import memo
    memo(engine, ('volume_actor', id(actor)), lambda: actor)
    key = ('volume_positions', id(actor), point(actor.position),
           point(at) if at is not None else None)
    from .volume_queries import positions
    return memo(engine, key, lambda: positions(engine._actor_volume(actor, at), position))


def zone_contains(engine, actor, zone, *, at=None):
    """Check membership, optionally clipping the footprint to saved cells.

    footprint_is_authoritative is a general zone seam: affected_cells defines
    the effective horizontal footprint while native shape and height continue
    to define the zone's vertical volume. Clipping only ever narrows columns;
    it never invents altitude, so a retained wall section or single space still
    reports membership strictly inside its own recorded extent.
    """
    return positions_inside_zone(engine, (point(at or actor.position),) if getattr(actor,'perception_cell',False) else engine._actor_volume(actor, at), zone)


def _zone_columns(engine, zone):
    """Stored column set and clipping flags for one area, shared inside a query.

    Building the column set from ``affected_cells`` (and subtracting removed
    sections) is fixed for one unchanged area object, while membership is asked
    for many projected creatures and path cells. Hold the area for the frame so
    an id cannot be reused, and return immutable data.
    """
    from .read_queries import shared_query

    def build():
        spec = zone.trigger_profile
        columns = {(cell.x, cell.y) for cell in zone.affected_cells}
        suppressed = spec.get('suppressed') or []
        held = {tuple(cell)[:2] for row in suppressed for cell in row.get('cells') or []}
        return (frozenset(columns - held), bool(spec.get('footprint_is_authoritative') or suppressed),
                any(row.get('all') for row in suppressed))

    return shared_query(engine, ('zone_columns', id(zone)), build, refs=(zone,))


def positions_inside_zone(engine, positions, zone):
    """Public point-volume query shared by actor membership and attack paths.

    Positions are integer grid triples, not display cells. Native shape/height,
    authoritative footprints and suppressed columns determine membership.
    This pure query neither widens a footprint nor changes saved zone state.
    """
    spec = zone.trigger_profile
    # Some zones use affected_cells as an authoritative, deliberately reduced
    # footprint (for example after a physical section is removed). Keep the
    # native height/volume rules below, but do not let the original radius
    # refill removed columns.
    columns, clip, all_suppressed = _zone_columns(engine, zone)
    if all_suppressed:
        return False
    volume = list(positions)
    if clip and not any((x, y) in columns for x, y, _z in volume):
        return False
    # Explicit footprint extrusions keep their recorded columns and base plane.
    # The exclusive top is independent of the display shape/radius. Unstamped
    # saved areas retain their historical geometry below.
    height = spec.get('footprint_height_ft')
    if height is not None:
        if type(height) is not int or height <= 0:
            raise ValueError('footprint_height_ft must be positive integer feet')
        base = zone.center.z * engine.grid.square_size_ft
        return any((x, y) in columns and base <= z * engine.grid.square_size_ft < base + height
                   for x, y, z in volume)
    # A saved block owns its recorded horizontal footprint, including legacy
    # cubes. New blocks already record the half-open grid geometry. Altitude
    # uses the block's size; radial membership is a separate rule below.
    if spec.get('shape') in ('cube', 'square') and spec.get('size_ft'):
        half = int(spec['size_ft']) / 2
        return any((x, y) in columns and -half <= (z-zone.center.z)*engine.grid.square_size_ft < half
                   for x, y, z in volume)
    # Painted terrain and explicit zero-radius footprints own their recorded
    # cells. A copied ability profile must not expand those cells into a sphere.
    # Clipped, prove membership at a column that actually survived rather than
    # anywhere inside the original radius.
    if (zone.radius_cells > 0 and spec.get('shape') not in (None, 'wall', 'painted')
            and spec.get('size_ft')):
        vertex = position(spec.get('area_vertex', point(zone.center)))
        if clip:
            return any((x, y) in columns and reaches(engine, vertex, zone.center, position((x, y, z)), spec)
                       for x, y, z in volume)
        return any(reaches(engine, vertex, zone.center, position(cell), spec) for cell in volume)
    # Explicit painted terrain stays on its stated plane. Radius-backed native
    # zones and plug-in auras also extend above/below the recorded center.
    if spec.get('wall'):
        height = spec['wall'].get('height_ft')
        base = spec['wall'].get('base_altitude_ft', zone.center.z*5)
        return any((x, y) in columns and (height is None or base <= z*5 < base+height)
                   for x, y, z in volume)
    radius = zone.radius_cells
    return any((x, y) in columns and abs(z-zone.center.z) <= radius
               for x, y, z in volume)


def zone_contains_cells(engine, volume, zone):
    """Shared whole-delivery membership query using the attack-path geometry.

    Any supplied cell must intersect the live native zone. Callers requiring
    complete containment query each cell separately. Delegate to the same
    public query as actor membership so suppression and clipping stay shared.
    """
    return positions_inside_zone(engine, volume, zone)


def zone_volume_cells(engine, zone):
    """Stream a zone's native 3D region for exact whole-delivery consumers.

    Source-region defenses use this without pretending the creator is the
    source. Native cube/painted footprints, clipping and explicit extrusion
    retain their stored columns; radial/ray shapes use native area geometry.
    Unbounded walls have unknown complete volume and yield no proof. The
    iterator is resolution-local, never persisted, and allows early rejection.
    """
    spec = zone.trigger_profile
    columns = sorted({(p.x, p.y) for p in zone.affected_cells})
    square = engine.grid.square_size_ft
    height = spec.get('footprint_height_ft')
    wall = spec.get('wall')
    if height is not None:
        zs = range(zone.center.z, zone.center.z + (int(height) + square - 1) // square)
    elif wall:
        height = wall.get('height_ft')
        if height is None:
            return
        # Match the native wall membership above, whose stored altitude unit
        # is five feet even in legacy grids with a different square size.
        unit = 5
        base = int(wall.get('base_altitude_ft', zone.center.z * unit))
        zs = range(max(0, (base + unit - 1) // unit), (base + int(height) + unit - 1) // unit)
    elif spec.get('shape') in ('cube', 'square') and spec.get('size_ft'):
        reach = int(spec['size_ft']) // square + 1
        zs = range(max(0, zone.center.z - reach), zone.center.z + reach + 1)
    elif zone.radius_cells > 0 and spec.get('shape') not in (None, 'wall', 'painted') and spec.get('size_ft'):
        from .typed_executor import area_cells
        vertex = position(spec.get('area_vertex', point(zone.center)))
        for p in area_cells(engine, vertex, zone.center, spec, include_altitude=True):
            cell = (p.x, p.y, p.z)
            if zone_contains_cells(engine, [cell], zone):
                yield cell
        return
    else:
        zs = range(max(0, zone.center.z - zone.radius_cells), zone.center.z + zone.radius_cells + 1)
    for x, y in columns:
        for z in zs:
            cell = (x, y, z)
            if zone_contains_cells(engine, [cell], zone):
                yield cell


def zone_volume_inside(engine, source, destination):
    """True only with nonempty, complete source-region containment evidence."""
    seen = False
    for cell in zone_volume_cells(engine, source):
        seen = True
        if not zone_contains_cells(engine, [cell], destination):
            return False
    return seen


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
        cells = area_cells(engine, vertex, zone.center, spec)
        if spec.get('footprint_is_authoritative'):
            recorded = {(p.x, p.y) for p in zone.affected_cells}
            return tuple(p for p in cells if (p.x, p.y) in recorded)
        return cells
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
    from . import zones, ext
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
        if any(answer is True for answer in ext.run_strict(
                "difficult_zone_at_exempt", engine, actor, zone, destination)):
            continue
        if spec.get('footprint_height_ft') is not None:
            subject = actor.model_copy(update={'position': destination})
            if zones.zone_is_difficult(engine, zone, subject) and zone_contains(engine, actor, zone, at=destination):
                return True
            continue
        # Ground and volume movement share recipient policies and per-zone exemptions.
        if zones.zone_is_difficult(engine, zone, actor) and zone_contains(engine, actor, zone, at=destination):
            return True
    return False
