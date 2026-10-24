"""Line occluders shared by grid sight, effect rays and table fog.

Walls, objects and blocking terrain keep their movement footprint. Sight uses
connected centre runs with full-depth perpendicular end caps. Tree/bamboo
crosses and horizontal roof surfaces retain their own geometric primitives.
Exported coordinates are integers with an explicit scale for authored stems
(default: doubled integers); fractions are query-only.
"""
from fractions import Fraction


def cell_runs(cells):
    remaining, runs = set(map(tuple, cells)), []
    while remaining:
        first = min(remaining)
        remaining.remove(first)
        group, pending = {first}, [first]
        while pending:
            x, y = pending.pop()
            for cell in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
                if cell in remaining:
                    remaining.remove(cell)
                    group.add(cell)
                    pending.append(cell)
        xs, ys = zip(*group)
        vertical = max(ys)-min(ys) > max(xs)-min(xs)
        rows = {}
        for x, y in group:
            u, v = (y,x) if vertical else (x,y)
            rows.setdefault(v, []).append(u)
        def point(u, v, depth):
            return (2*v+depth, 2*u) if vertical else (2*u, 2*v+depth)
        strips = {}
        for v, values in sorted(rows.items()):
            values.sort()
            start = last = values[0]
            for u in values[1:] + [None]:
                if u != last+1:
                    strips.setdefault((start,last+1),[]).append(v)
                    start = u
                last = u
        # Equal adjoining strips form one thicker wall, with its line through
        # the middle of the whole depth. Different extents retain their ends.
        for (start,end), values in strips.items():
            first = last = values[0]
            for v in values[1:] + [None]:
                if v != last+1:
                    depth = last-first+1
                    runs.append((point(start,first,depth),point(end,first,depth),depth))
                    first = v
                last = v
    return runs


def source(cells, kind, bottom=0, top=None, name='Sight blocker', *, segments=None, scale=2):
    cells = sorted(set(map(tuple,cells)))
    authored = segments is not None
    if authored:
        if type(scale) is not int or scale <= 0:
            raise ValueError('Sight segment scale must be a positive integer')
        segments = [tuple(map(tuple,s)) for s in segments]
        for a,b in segments:
            if any(type(n) is not int for p in (a,b) for n in p) or len(a)!=2 or len(b)!=2 or a==b or (a[0]!=b[0] and a[1]!=b[1]):
                raise ValueError('Sight segments must be nonempty axis-aligned integer pairs')
    else:
        segments = []
        for a,b,depth in cell_runs(cells):
            segments.append((a,b))
            dx,dy = (depth,0) if a[0] == b[0] else (0,depth)
            segments.extend(((p[0]-dx,p[1]-dy),(p[0]+dx,p[1]+dy)) for p in (a,b))
    return {**({'scale':scale,'surface':False} if authored else {}),
            'cells':cells, 'kind':kind, 'bottom_ft':bottom, 'top_ft':top,
            'name':name, 'segments':segments}


def bind(grid, dynamic=()):
    """Rebuild derived line spans after policy binding or zone/object changes.

    Only matching spans are replaced; independent overlapping crosses remain.
    This seam changes no movement data, saved objects, decisions or abilities.
    """
    sources = []
    grid.solid_cross_spans = {}
    for region in grid._occluder_regions:
        kind = region['terrain_type']
        if kind not in {'BLOCKED','SIGHT_BLOCKED'}:
            continue
        # Unstamped cross-era maps retain their previous tree/cell policy.
        # Ordinary walls/objects still use line runs in either policy.
        if 'sight_segments' not in region and grid.occluder_policy == 'cell-v1' and region.get('occluder') == 'centerline':
            continue
        if 'sight_segments' not in region and grid.occluder_policy == 'cross-v1' and region.get('occluder') == 'centerline':
            if kind == 'BLOCKED':
                bottom = region.get('base_altitude_ft',0) if region.get('height_ft') is not None else 0
                top = bottom+region['height_ft'] if region.get('height_ft') is not None else None
                for c in region['cells']:
                    grid.solid_cross_spans.setdefault((c['x'],c['y']),[]).append((bottom,top))
            continue
        bottom = region.get('base_altitude_ft',0) if region.get('height_ft') is not None else 0
        top = bottom+region['height_ft'] if region.get('height_ft') is not None else None
        cells = [(c['x'],c['y']) for c in region['cells']
                 if (bottom,top) in grid.terrain_spans.get(kind,{}).get((c['x'],c['y']),())]
        authored = region.get('sight_segments')
        sources.append(source(cells,kind,bottom,top,region.get('description') or 'Blocking terrain',
                              **({'segments':authored['segments'],'scale':authored['scale']} if authored is not None else {})))
    sources.extend(dynamic)
    grid.sight_line_sources = [row for row in sources if row['cells']]
    grid.sight_line_spans = {}
    grid.sight_line_bounds = []
    for row in grid.sight_line_sources:
        xs,ys = zip(*row['cells'])
        points = [p for segment in row['segments'] for p in segment]
        if points:
            px,py = zip(*points)
            scale = row.get('scale',2)
            grid.sight_line_bounds.append((min(px),max(px),min(py),max(py)) if scale==2 else
                                         tuple(Fraction(n*2,scale) for n in (min(px),max(px),min(py),max(py))))
        else:
            grid.sight_line_bounds.append((2*min(xs),2*(max(xs)+1),2*min(ys),2*(max(ys)+1)))
        for cell in row['cells']:
            grid.sight_line_spans.setdefault((row['kind'],tuple(cell)),[]).append((row['bottom_ft'],row['top_ft']))


def hit(start, end, row, *, near_endpoint=False):
    bottom, top = row['bottom_ft'], row['top_ft']
    if top is not None and top <= bottom:
        return False
    scale = row.get('scale',2)
    half = scale//2 if scale%2==0 else Fraction(scale,2)
    p = (scale*start.x+half, scale*start.y+half)
    d = (scale*(end.x-start.x), scale*(end.y-start.y))
    dz = 5*(end.z-start.z)
    lower, upper = Fraction(0), Fraction(1)
    occupied_start = False
    if near_endpoint and row['kind'] == 'SIGHT_BLOCKED':
        # Creature sight retains the walk-through screen endpoint policy.
        # Clip only the occupied cell's part of this ray, not the whole
        # connected source: another cell of the same screen still intervenes.
        exit_t = min((Fraction(half, abs(n)) for n in d if n), default=Fraction(1))
        def occupies(point):
            return ((point.x, point.y) in row['cells'] and bottom <= 5*point.z
                    and (top is None or 5*point.z < top))
        occupied_start = occupies(start)
        if occupied_start:
            lower = max(lower, exit_t)
        if occupies(end):
            upper = min(upper, 1-exit_t)
        if lower >= upper:
            return False
    for a,b in row['segments']:
        axis = 0 if a[0] == b[0] else 1
        other = 1-axis
        low, high = sorted((a[other],b[other]))
        if d[axis]:
            t = Fraction(a[axis]-p[axis],d[axis])
            if not lower <= t <= upper or (near_endpoint and
                    (t == upper or (occupied_start and t == lower))):
                continue
            coord, altitude = p[other]+d[other]*t, 5*start.z+dz*t
            if low <= coord <= high and bottom <= altitude and (top is None or altitude < top):
                return True
        elif p[axis] == a[axis]:
            from .terrain_occlusion import collinear_span_hit
            lo, hi = lower, upper
            if d[other]:
                ends = sorted((Fraction(low-p[other], d[other]), Fraction(high-p[other], d[other])))
                lo, hi = max(lo, ends[0]), min(hi, ends[1])
            if lo > hi or (lo == hi and near_endpoint and
                    (lo == upper or (occupied_start and lo == lower))):
                continue
            if collinear_span_hit(p[other]+d[other]*lo, d[other]*(hi-lo), low, high,
                                  5*start.z+dz*lo, dz*(hi-lo), bottom, top):
                return True
    return False


def clear(grid, start, end, *, physical=False, near_endpoint=False):
    x0,x1 = sorted((2*start.x+1,2*end.x+1))
    y0,y1 = sorted((2*start.y+1,2*end.y+1))
    return not any(hit(start,end,row,near_endpoint=near_endpoint)
                   for row,(left,right,low,high) in zip(getattr(grid,'sight_line_sources',()),getattr(grid,'sight_line_bounds',()))
                   if (not physical or row['kind'] == 'BLOCKED')
                   and x0<=right and x1>=left and y0<=high and y1>=low)


def remaining_spans(grid, kind, cell):
    rows = list(grid.terrain_spans.get(kind,{}).get(cell,
                [(0,grid.terrain_heights.get(kind,{}).get(cell))]))
    for span in getattr(grid,'sight_line_spans',{}).get((kind,cell),()):
        if span in rows:
            rows.remove(span)
    return rows
