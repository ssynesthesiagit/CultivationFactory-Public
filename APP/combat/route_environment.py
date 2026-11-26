"""Authored route geometry shared by combat routes and elapsed-time journeys.

The protected map-save path supplies facts, never artwork, team membership or
damage labels. Missing water properties remain unknown. Consumers opt in to
barrier queries; this module changes no ordinary movement or teleport by itself.
"""
from .gate2_runtime_models import Position

KINDS = ('water', 'spatial_lock', 'sealed_formation', 'planar_boundary', 'teleport_barrier')
PROPERTIES = ('stagnant', 'poisoned', 'supernaturally_altered', 'actively_cultivated')


def normalize(rows, width, height):
    if not isinstance(rows, list):
        raise ValueError('Route regions must be a list.')
    result = []
    for row in rows:
        if not isinstance(row, dict) or row.get('kind') not in KINDS:
            raise ValueError('Choose a known route medium or barrier.')
        if set(row) - {'id', 'kind', 'cells', 'flow', *PROPERTIES}:
            raise ValueError('Unknown route fact field.')
        if not isinstance(row.get('id'), str) or not row['id'].strip():
            raise ValueError('A route region needs a stable identity.')
        cells = row.get('cells')
        if not isinstance(cells, list) or not cells:
            raise ValueError('A route region needs mapped spaces.')
        normalized = []
        for cell in cells:
            if (not isinstance(cell, dict) or set(cell) - {'x', 'y', 'z'}
                    or any(type(cell.get(k, 0)) is not int for k in ('x', 'y', 'z'))
                    or not 0 <= cell.get('x', -1) < width or not 0 <= cell.get('y', -1) < height
                    or cell.get('z', 0) < 0):
                raise ValueError('Route spaces must be whole in-bounds map coordinates.')
            normalized.append(Position.model_validate(cell).model_dump(mode='json'))
        extra = {}
        if row['kind'] == 'water':
            if 'flow' in row:
                if row['flow'] not in ('north', 'south', 'east', 'west', 'northeast', 'northwest', 'southeast', 'southwest', 'up', 'down', 'still'):
                    raise ValueError('Choose a water flow direction.')
                extra['flow'] = row['flow']
            for name in PROPERTIES:
                if name in row:
                    if type(row[name]) not in (bool, int) or row[name] not in (0, 1):
                        raise ValueError('Water properties must be explicit true or false facts.')
                    extra[name] = int(row[name])
        elif set(row) & {'flow', *PROPERTIES}:
            raise ValueError('Only water carries water properties.')
        result.append({'id': row['id'], 'kind': row['kind'], 'cells': normalized, **extra})
    if len({r['id'] for r in result}) != len(result):
        raise ValueError('Route identities must be unique.')
    return result


def key(cell):
    return (cell.x, cell.y, cell.z)


def at(grid, cell, kinds=KINDS):
    return [r for r in grid.route_regions if r['kind'] in kinds
            and any((c['x'], c['y'], c.get('z', 0)) == key(cell) for c in r['cells'])]


def permits(grid, start, end, *, teleport=False, barriers=None):
    """Absolute printed barriers on a route, including its endpoints.

    Teleportation checks its straight spatial crossing, physical movement its
    actual per-step edge. Native collision/cover and effect gates remain callers'
    responsibility. Explicit Riverway prohibitions do not use a guessed CL DC.
    """
    kinds = tuple(barriers) if barriers is not None else (('spatial_lock', 'sealed_formation', 'planar_boundary', 'teleport_barrier') if teleport else ('spatial_lock', 'sealed_formation'))
    if not set(kinds)<=set(KINDS)-{'water'}:raise ValueError('Unknown route barrier type.')
    for x,y,z in grid.effect_ray_cells(start,end):
        p = Position(x=x,y=y,z=z)
        if at(grid, p, kinds):
            return False
    return True


def water_knowledge(grid, position, feet=60):
    """Connected water's declared flow, plus declared nearby quality facts.

    Connection means touching water at the observer's space or adjacent to it;
    the graph follows real contiguous water cells. Absent facts stay absent.
    """
    water = [r for r in grid.route_regions if r['kind'] == 'water']
    by_cell = {}
    for row in water:
        for c in row['cells']:
            by_cell.setdefault((c['x'], c['y'], c.get('z', 0)), []).append(row)
    connected = {c for c in by_cell if max(abs(c[i]-key(position)[i]) for i in range(3)) <= 1
                 and grid.volume_legal(Position(x=c[0],y=c[1],z=c[2]))
                 and grid.line_of_physical_transmission(position,Position(x=c[0],y=c[1],z=c[2]))}
    frontier = list(connected)
    while frontier:
        c = frontier.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    nxt = (c[0]+dx, c[1]+dy, c[2]+dz)
                    if (nxt in by_cell and nxt not in connected
                        and grid.volume_step_legal(Position(x=c[0],y=c[1],z=c[2]),Position(x=nxt[0],y=nxt[1],z=nxt[2]))
                        and grid.line_of_physical_transmission(Position(x=c[0],y=c[1],z=c[2]),Position(x=nxt[0],y=nxt[1],z=nxt[2]))):
                        connected.add(nxt); frontier.append(nxt)
    result = []
    for c in sorted(connected):
        facts = {'space': ','.join(map(str, c))}
        for row in by_cell[c]:
            if 'flow' in row:
                facts['flow'] = row['flow']
            if max(abs(c[i]-key(position)[i]) for i in range(3))*grid.square_size_ft <= feet:
                facts.update({p: row[p] for p in PROPERTIES if p in row})
        if len(facts) > 1:
            result.append(facts)
    return result
