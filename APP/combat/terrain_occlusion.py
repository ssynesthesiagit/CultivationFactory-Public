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
    if top is not None and top <= bottom:
        return False
    if start.x == end.x and start.y == end.y:
        if cell != (start.x, start.y):
            return False
        low, high = sorted((start.z * 5, end.z * 5))
        return high >= bottom and (top is None or low < top)
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
    """Terrain spans only; no actor, zone, sense or ability special cases."""
    endpoints = {(start.x, start.y), (end.x, end.y)}
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
        # Infinite full-cell obstacles keep their historical raster policy.
        # Finite cell spans are checked at the exact segment below, not z's
        # rounded voxel (which can put a low wall above the flying viewer).
        for bottom, top in cell_spans(grid, (x, y)):
            if top is None and bottom <= z:
                return False
        for mode, bottom, top in grid.occluder_spans.get((x, y), ()):
            if endpoint_in_span(start, end, (x, y), bottom, top):
                continue
            if cached is None and mode == 'centerline' and cross_hit(start, end, (x,y), bottom, top):
                return remember(False)
    for cell in crossed_cells(start, end):
        for bottom, top in cell_spans(grid, cell):
            if top is None:
                continue
            # Preserve sight of an obstacle's near-side endpoint, while a
            # raised roof between endpoints in the same column still blocks.
            if cell in endpoints and endpoint_in_span(start, end, cell, bottom, top):
                continue
            if cell_span_hit(start, end, cell, bottom, top):
                return False
    if not grid.centerline_cells:
        return True
    if cached is not None:
        return cached
    for cell in crossed_cells(start, end):
        if cell not in grid.centerline_cells:
            continue
        for mode, bottom, top in grid.occluder_spans[cell]:
            if endpoint_in_span(start, end, cell, bottom, top):
                continue
            if mode == 'centerline' and cross_hit(start, end, cell, bottom, top):
                return remember(False)
    return remember(True)


def endpoint_in_span(start, end, cell, bottom, top):
    """Near-side endpoints stay visible; a span between their heights does not."""
    return any((p.x, p.y) == cell and bottom <= p.z * 5 and (top is None or p.z * 5 < top)
               for p in (start, end))


def cell_spans(grid, cell):
    """Full-cell sight spans, shared by immutable terrain and dynamic objects.

    Static centerline spans are removed once from the current terrain spans;
    overlapping dynamic full-cell walls must retain their own geometry.
    """
    spans = []
    for kind, cells in (("BLOCKED", grid.blocked), ("SIGHT_BLOCKED", grid.opaque)):
        if cell not in cells:
            continue
        rows = grid.terrain_spans.get(kind, {}).get(cell)
        spans.extend(rows if rows is not None else [(0, grid.terrain_heights.get(kind, {}).get(cell))])
    for mode, bottom, top in grid.occluder_spans.get(cell, ()):
        if mode == 'centerline' and (bottom, top) in spans:
            spans.remove((bottom, top))
    return spans


def cell_span_hit(start, end, cell, bottom, top):
    """Exact ray intersection with a cell interior and [bottom, top) feet.

    Slab bounds are rational integer pairs, never rounded altitude or floats.
    Corner-only contact does not enter the obstacle. Terrain and objects use
    this same seam; the start and end z coordinates are the sight origins.
    """
    lower, upper = (0, 1), (1, 1)
    for axis, (origin, delta, low, high) in enumerate((
            (2 * start.x + 1, 2 * (end.x - start.x), 2 * cell[0], 2 * cell[0] + 2),
            (2 * start.y + 1, 2 * (end.y - start.y), 2 * cell[1], 2 * cell[1] + 2),
            (start.z * 5, (end.z - start.z) * 5, bottom, top))):
        if not delta:
            inside = (low < origin < high if axis < 2 else
                      low <= origin and (high is None or origin < high))
            if not inside:
                return False
            continue
        a = (low - origin, delta)
        b = (high - origin, delta) if high is not None else None
        if delta < 0:
            a, b = ((-b[0], -delta) if b is not None else None), (-a[0], -delta)
        if a is not None and a[0] * lower[1] > lower[0] * a[1]:
            lower = a
        if b is not None and b[0] * upper[1] < upper[0] * b[1]:
            upper = b
        if lower[0] * upper[1] >= upper[0] * lower[1]:
            return False
    return True


def segment_clear(grid, start, end, *, physical=False, obscured_cells=()):
    """Exact surface-ended sight/effect segment, sharing the ordinary 3D slabs.

    Unlike creature sight, projectile endpoints have no terrain exemption.
    Physical queries check solid spans; sight also checks full-cell/centerline
    occluders and obscurement. No span is removed, including overlapping ones.
    Fractional endpoints are transient points from space.surface_point.
    """
    cells = grid.blocked if physical else grid.blocked | grid.opaque
    for cell in cells:
        spans = (grid.terrain_spans.get('BLOCKED', {}).get(cell,
                 [(0, grid.terrain_heights.get('BLOCKED', {}).get(cell))])
                 if physical else cell_spans(grid, cell))
        if any(cell_span_hit(start, end, cell, bottom, top) for bottom, top in spans):
            return False
        if not physical and any(mode == 'centerline' and cross_hit(start, end, cell, bottom, top)
                                for mode, bottom, top in grid.occluder_spans.get(cell, ())):
            return False
    for cell in (() if physical else obscured_cells):
        bottom, top = (cell[2] * 5, (cell[2] + 1) * 5) if len(cell) == 3 else (0, None)
        if cell_span_hit(start, end, cell[:2], bottom, top):
            return False
    return True
