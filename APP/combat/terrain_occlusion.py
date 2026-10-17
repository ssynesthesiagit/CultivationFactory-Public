"""General terrain geometry used by SquareGrid and its saved-policy loaders.

The cell-v1 predecessor ignores map modes. cross-v1 enables each region's
occluder (cell or centerline); missing modes still mean cell. Endpoint terrain
is visible, as before; dynamic obscurement remains the caller's separate rule.
Crosses include their tips: adjacent crosses join without diagonal pinholes.
All geometry uses integer cross products, including altitude at intersection.
"""
CELL_POLICY = 'cell-v1'
CROSS_POLICY = 'cross-v1'


def saved_policy(events):
    for event in reversed(events):
        kind = event.event_type if hasattr(event, 'event_type') else event['event_type']
        payload = event.payload if hasattr(event, 'payload') else event.get('payload', {})
        if kind in {'MATCH_CREATED', 'SAVED_FIGHT_CONTINUED'} and 'terrain_occlusion_policy' in payload:
            policy = payload['terrain_occlusion_policy']
            if policy not in {CELL_POLICY, CROSS_POLICY}:
                raise ValueError('Unknown saved terrain occlusion policy')
            return policy
    return CELL_POLICY  # Every unstamped predecessor used whole cells.


def crossed_cells(start, end):
    """Supercover of a centre-to-centre ray, including corner-touching cells."""
    x, y = start.x, start.y
    nx, ny = abs(end.x - x), abs(end.y - y)
    sx, sy = (1 if end.x > x else -1), (1 if end.y > y else -1)
    ix = iy = 0
    yield x, y
    while ix < nx or iy < ny:
        a, b = (1 + 2 * ix) * ny, (1 + 2 * iy) * nx
        if a == b:
            yield x + sx, y
            yield x, y + sy
            x, y, ix, iy = x + sx, y + sy, ix + 1, iy + 1
        elif a < b:
            x, ix = x + sx, ix + 1
        else:
            y, iy = y + sy, iy + 1
        yield x, y


def cross_hit(start, end, cell, bottom, top):
    """Does this ray meet either edge-to-edge centre segment at its height?"""
    x, y = cell
    origin = (2 * start.x + 1, 2 * start.y + 1)
    delta = (2 * (end.x - start.x), 2 * (end.y - start.y))
    dz = (end.z - start.z) * 5
    for axis, center, low, high in ((0, 2*x+1, 2*y, 2*y+2), (1, 2*y+1, 2*x, 2*x+2)):
        d = delta[axis]
        if not d:
            # A collinear ray passes through this cell's centre, so the other
            # arm supplies the same hit (including vertical-only rays).
            continue
        n = center - origin[axis]
        if d < 0:
            n, d = -n, -d
        other = origin[1-axis] * d + delta[1-axis] * n
        altitude = start.z * 5 * d + dz * n
        if 0 <= n <= d and low*d <= other <= high*d and bottom*d <= altitude and (top is None or altitude < top*d):
            return True
    return False


def terrain_visible(grid, start, end, ray):
    """Static terrain only; no actor, zone, sense or ability special cases."""
    key = (start.x,start.y,start.z,end.x,end.y,end.z)
    cached = grid._centerline_sight_cache.get(key)
    def remember(value):
        # Only immutable cross geometry is retained. Full cells and dynamic
        # obscurement are checked afresh. Rebinding clears the bounded cache.
        if len(grid._centerline_sight_cache) >= 8192:
            grid._centerline_sight_cache.clear()
        grid._centerline_sight_cache[key] = value
        return value
    for cell in ray[1:-1]:
        x, y = cell[:2]
        if (x, y) not in grid.blocked and (x, y) not in grid.opaque:
            continue
        z = cell[2] * 5 if len(cell) > 2 else 0
        spans = grid.occluder_spans.get((x, y), ())
        if not spans and (grid.terrain_at(cell,'BLOCKED') or grid.terrain_at(cell,'SIGHT_BLOCKED')):
            return False
        for mode, bottom, top in spans:
            if mode == 'cell' and bottom <= z and (top is None or z < top):
                return False
            if cached is None and mode == 'centerline' and cross_hit(start, end, (x,y), bottom, top):
                return remember(False)
    if not grid.centerline_cells:
        return True
    if cached is not None:
        return cached
    endpoints = {(start.x, start.y), (end.x, end.y)}
    for cell in crossed_cells(start, end):
        if cell in endpoints or cell not in grid.centerline_cells:
            continue
        for mode, bottom, top in grid.occluder_spans[cell]:
            if mode == 'centerline' and cross_hit(start, end, cell, bottom, top):
                return remember(False)
    return remember(True)
