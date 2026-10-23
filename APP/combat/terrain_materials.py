"""Authored materials and opt-in material traversal, shared by maps and movement.

Materials describe matter, never sight, breath or a permission by themselves.
Unknown/unlabelled obstacles and sealed regions remain obstacles. A capability
publishes {mode, materials, difficult_materials}; search and execution use the
same volume/edge law. All queries are pure and use observed occupancy in menus.
Supported connections outside the granted medium, at any altitude, obey ordinary
walking costs, including posture; flight.step_cost applies that law to preview
and execution.
"""
import heapq
from itertools import combinations

from . import ext
from .gate2_runtime_models import Position
from .space import point

# One mapping for existing editor ground kinds. Decorative artwork is not a
# material claim. Painted floors are surfaces, not solid walls above the floor.
EDITOR_MATERIALS = {
    'grass': 'soil', 'forest_loam': 'soil', 'packed_dirt': 'soil',
    'sand': 'sand', 'dunes': 'sand', 'snow': 'snow', 'snowfield': 'snow',
    'wood': 'wood', 'flagstone': 'stone', 'tiles': 'stone', 'cave': 'stone',
    'temple_court': 'stone', 'swamp_mud': 'loose earth',
}


ANCHOR_KINDS = ('anti_void', 'conceptual_anchoring')


def anchor_of(raw):
    """Authored active anti-Void or conceptual anchoring on matter: {kind, source_cl}, else None.

    Only a region or zone wall carries it; the engine never infers one from a name.
    """
    if not raw:
        return None
    if (not isinstance(raw, dict) or raw.get('kind') not in ANCHOR_KINDS
            or type(raw.get('source_cl')) is not int or raw['source_cl'] < 0):
        raise ValueError('material anchor needs a known kind and a nonnegative integer source_cl')
    return {'kind': raw['kind'], 'source_cl': raw['source_cl']}


def material_tag(value):
    """Canonical map-data spelling; absent material stays absent."""
    return str(value or '').strip().lower().replace('_', ' ').replace('-', ' ')


def at(grid, cell):
    """Public query: all material records intersecting one integer 3-D cell.

    Records include material, terrain_type and sealed, with authored vertical
    spans. The immutable grid index preserves overlapping independent sources.
    """
    x, y, z = point(cell)
    return tuple(row for row in grid.material_regions.get((x, y), ())
                 if z * 5 >= row['bottom'] and (row['top'] is None or z * 5 < row['top']))


def query(engine, cell):
    """Map and active zone material records; independent sources stay separate.

    Zones may author material/sealed in their profile or wall rule. Named
    terrains use terrain.json's material. Missing matter never opens a wall.
    Sight/obscurement visuals alone are not a solid traversal permission.
    """
    from .zones import typed_zones, terrain_rules
    from .read_queries import memo
    x, y, z = point(cell)
    def collect():
        records = list(at(engine.grid, cell))
        for zone in typed_zones(engine):
            if not any(c.x == x and c.y == y for c in zone.affected_cells):
                continue
            spec = zone.trigger_profile or {}
            if any(tuple(row['cell']) == (x, y) for row in spec.get('openings') or []):
                continue
            wall = spec.get('wall') or {}
            bottom, height = int(wall.get('base_altitude_ft', 0)), wall.get('height_ft')
            if not wall and z:
                continue
            if height is not None and not bottom <= z * 5 < bottom + height:
                continue
            names = spec.get('terrain') or ()
            anchor = anchor_of(wall.get('anchor') or spec.get('anchor'))
            materials = [wall.get('material') or spec.get('material')]
            materials.extend((terrain_rules().get('terrains', {}).get(name) or {}).get('material') for name in names)
            # An unlabelled wall must remain an independent blocking source.
            materials = [material_tag(tag) for tag in materials if tag] or ['']
            records.extend({'material': tag, 'terrain_type': 'BLOCKED' if wall.get('blocks_movement') else 'OPEN',
                            'sealed': bool(wall.get('sealed') or spec.get('sealed')),
                            'bottom': bottom, 'top': bottom + height if height is not None else None,
                            'magical': zone.owner_id != 'map', 'anchor': anchor} for tag in materials)
        return tuple(records)
    return memo(engine, ('material_records', x, y, z), collect)


def profiles(engine, actor):
    """Capabilities are default-inert and carry no hidden creature information."""
    from .read_queries import memo
    def collect():
        modes = {}
        for row in ext.run_strict('material_traversal', engine, actor):
            mode = row['mode']
            allowed = {material_tag(tag) for tag in row['materials']}
            difficult = {material_tag(tag) for tag in row.get('difficult_materials', ())}
            costs = modes.setdefault(mode, {})
            for tag in allowed:
                # Independent grants union, and the cheapest permission wins.
                costs[tag] = min(costs.get(tag, 2), 2 if tag in difficult else 1)
        return tuple({'mode': mode, 'materials': tuple(sorted(costs)),
                      'difficult_materials': tuple(sorted(tag for tag in costs if costs[tag] == 2))}
                     for mode, costs in modes.items())
    return memo(engine, ('material_traversal', actor.entity_id), collect)


def profile(engine, actor, mode):
    return next((row for row in profiles(engine, actor) if row['mode'] == mode), None)


def passable(engine, cell, capability):
    grid = engine.grid
    records = query(engine, cell)
    if any(row['sealed'] for row in records):
        return False
    blocked = [row for row in records if row['terrain_type'] == 'BLOCKED']
    if not grid.terrain_at(cell, 'BLOCKED'):
        return True
    if not blocked or any(row['material'] not in capability['materials'] for row in blocked):
        return False
    return True


def supported(engine, actor, destination, capability=None):
    """Matter that can carry this creature in a published swimming mode.

    Used by falling and material route admission. This is support in the
    medium, not Hover, a sight grant, or a way to swim through empty air.
    """
    capabilities = (capability,) if capability is not None else profiles(engine, actor)
    return any(all(any(row['material'] in cap['materials'] for row in query(engine, cell))
                   and passable(engine, cell, cap)
                   for cell in engine._actor_volume(actor, destination)) for cap in capabilities)


def step_allowed(engine, actor, previous, destination, mode, *, observed=False):
    capability = profile(engine, actor, mode)
    if capability is None:
        return False
    start, end = point(previous), point(destination)
    axes = [i for i in range(3) if start[i] != end[i]]
    if not axes or any(abs(start[i] - end[i]) > 1 for i in axes):
        return False
    from .creature_passage import volume_geometry
    occupied = volume_geometry(engine, actor, observed=observed)[0]
    footprint = engine._footprint(actor)
    if engine.grid.roof_step_blocked(previous, destination, footprint):
        return False
    for count in range(1, len(axes) + 1):
        for selected in combinations(axes, count):
            anchor = tuple(end[i] if i in selected else start[i] for i in range(3))
            position = Position(x=anchor[0], y=anchor[1], z=anchor[2])
            if anchor[2] != start[2] and not supported(engine, actor, position, capability):
                return False  # swimming grants vertical travel only inside its medium
            if anchor[2] and anchor[2] == start[2]:
                from .falling import supported as ordinary_support
                if not supported(engine, actor, position, capability) and not ordinary_support(engine, actor, position):
                    return False
            if engine.grid.roof_geometry.volume_blocked(anchor, footprint):
                return False
            for cell in engine._actor_volume(actor, Position(x=anchor[0], y=anchor[1], z=anchor[2])):
                if (not engine.grid.in_bounds(cell[:2]) or cell in occupied
                        or not passable(engine, cell, capability)):
                    return False
    return True


def placement_legal(engine, actor, destination, mode, *, observed=False):
    """End in an owned medium with the shared, scoped endpoint permissions."""
    capability = profile(engine, actor, mode)
    footprint = engine._footprint(actor)
    from .creature_passage import endpoint_volumes
    occupied = endpoint_volumes(engine, actor, observed=observed)
    if capability is None:
        return engine.grid.volume_legal(destination, footprint=footprint, occupied_cells=occupied)
    from .falling import supported as ordinary_support
    return ((not destination.z or supported(engine, actor, destination, capability)
             or ordinary_support(engine, actor, destination))
            and not engine.grid.roof_geometry.volume_blocked(destination, footprint)
            and all(engine.grid.in_bounds(cell[:2]) and cell not in occupied
                    and passable(engine, cell, capability)
                    for cell in engine._actor_volume(actor, destination)))


def difficult(engine, actor, previous, destination, mode):
    capability = profile(engine, actor, mode)
    if capability is None:
        return False
    from .motion import mover_exempt_cells, ignores_area_difficult, exempt_cells
    exempt = mover_exempt_cells(engine, actor)
    return any(row['material'] in capability.get('difficult_materials', ())
               and ((not ignores_area_difficult(engine, actor) and cell[:2] not in exempt_cells(engine, actor, 'magical'))
                    if row.get('magical') else (exempt is not None and cell[:2] not in exempt))
               for cell in engine._actor_volume(actor, destination)
               for row in query(engine, cell))


def routes(engine, actor, mode, *, grant_ft=None, path_selector=None):
    """Every reachable endpoint in a material mode, without truncating options."""
    from . import flight
    from .voluntary_movement import edge_predicate
    budget = flight.remaining(engine, actor, mode) if grant_ft is None else grant_ft
    if budget <= 0 or profile(engine, actor, mode) is None:
        return {}
    restriction = edge_predicate(engine, actor)
    from .creature_passage import geometry
    extra_difficult = geometry(engine, actor, observed=True)[2]
    difficult_cells = engine._hostile_difficult_cells(actor) | extra_difficult
    start = point(actor.position)
    costs, paths, queue = {start: 0}, {start: (actor.position,)}, [(0, start)]
    ceiling = start[2] + budget // engine.grid.square_size_ft
    parents, predecessors = {}, {}
    while queue:
        cost, cell = heapq.heappop(queue)
        if cost != costs[cell]:
            continue
        previous = paths[cell][-1]
        from itertools import product
        for dx, dy, dz in product((-1, 0, 1), repeat=3):
            if (not (dx or dy or dz) or not 0 <= cell[2] + dz <= ceiling
                    or not engine.grid.in_bounds((cell[0] + dx, cell[1] + dy))):
                continue
            nxt = Position(x=cell[0] + dx, y=cell[1] + dy, z=cell[2] + dz)
            if (restriction is not None and not restriction(previous, nxt)) or not flight.step_allowed(engine, actor, previous, nxt, mode=mode, observed=True):
                continue
            price = cost + flight.step_cost(engine, actor, previous, nxt, mode,
                                            difficult_cells)
            key = point(nxt)
            if price == costs.get(key):
                predecessors[key].add(cell)
                continue
            if price > budget or price >= costs.get(key, budget + 1):
                continue
            costs[key], paths[key] = price, (*paths[cell], nxt)
            parents[key], predecessors[key] = cell, {cell}
            heapq.heappush(queue, (price, key))
    if path_selector:
        from types import MappingProxyType
        selected = path_selector(start, MappingProxyType({cell: frozenset(rows) for cell, rows in predecessors.items()}),
                                 MappingProxyType(costs), MappingProxyType(parents))
        for cell, chosen in selected.items():
            if chosen[0] != start or chosen[-1] != cell or any(a not in predecessors.get(b, ()) for a, b in zip(chosen, chosen[1:])):
                raise ValueError('Material route selection must use an equal-cost native path')
            paths[cell] = tuple(Position(x=x, y=y, z=z) for x, y, z in chosen)
    from .creature_passage import endpoint_volumes
    occupied = endpoint_volumes(engine, actor, observed=True)
    return {path[-1]: (path, costs[cell], mode) for cell, path in paths.items()
            if cell != start and not set(engine._actor_volume(actor, path[-1])) & occupied}
