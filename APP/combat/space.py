"""Integer combat geometry: five-foot altitude and creature volumes.

Two-coordinate terrain/footprint cells remain valid ground projections. Callers
needing reach, sight or occupancy use points/volumes, never infer altitude from
the projection. No state or ability ownership is stored here.
"""
from .gate2_runtime_models import Position
from fractions import Fraction
from typing import NamedTuple


class SurfacePoint(NamedTuple):
    """Transient exact ray endpoint; never serialized into fight state."""
    x: Fraction
    y: Fraction
    z: int


def surface_point(waypoint, cell):
    """Midpoint of the face between adjacent grid centres, in grid units.

    Projectile routes store the integer waypoint and surface cell; sight and
    physical effect validation derive this same exact endpoint from them.
    """
    return SurfacePoint(Fraction(waypoint.x + cell['x'], 2),
                        Fraction(waypoint.y + cell['y'], 2), waypoint.z)


def point(cell):
    if isinstance(cell, Position):
        return cell.x, cell.y, cell.z
    return (cell[0], cell[1], cell[2] if len(cell) > 2 else 0)


def position(cell):
    """Keep derived fractional endpoints exact; integer cells remain Positions."""
    x, y, z = point(cell)
    if any(isinstance(v, Fraction) and v.denominator != 1 for v in (x,y,z)):
        return SurfacePoint(x,y,z)
    return Position(x=x, y=y, z=z)


def projection(cell):
    x, y, _ = point(cell)
    return x, y


def volume(anchor, footprint=None):
    """Exact pure native footprint derivation, with bounded immutable reuse."""
    from .volume_queries import volume as indexed_volume
    return indexed_volume(point(anchor), footprint, _volume)


def _volume(anchor, footprint=None):
    x, y, z = point(anchor)
    cells = tuple(footprint.occupied_cells((x, y))) if footprint is not None else ((x, y),)
    height = max(max(cx for cx, _ in cells) - min(cx for cx, _ in cells) + 1,
                 max(cy for _, cy in cells) - min(cy for _, cy in cells) + 1)
    return tuple((cx, cy, cz) for cx, cy in cells for cz in range(z, z + height))


def ray(start, end):
    """A deterministic integer 3D center ray, including both endpoints."""
    left, right = point(start), point(end)
    steps = max(abs(a - b) for a, b in zip(left, right))
    if not steps:
        return (left,)
    return tuple(tuple((2 * (a * steps + (b - a) * i) + steps) // (2 * steps)
                       for a, b in zip(left, right)) for i in range(steps + 1))


def effect_ray(start, end):
    """Every voxel whose interior a center-to-center effect segment crosses.

    Integer cross-products order boundary crossings exactly in 2D or 3D.
    Simultaneous crossings advance all tied axes: touching only a corner/edge
    does not enter either grazed voxel. Includes endpoints and is reversible.
    Used for physical area propagation, not legacy attack sight rasterization.
    """
    current, finish = list(point(start)), point(end)
    distance = [abs(b-a) for a,b in zip(current,finish)]
    direction = [1 if b>a else -1 for a,b in zip(current,finish)]
    crossed = [0,0,0]
    cells = [tuple(current)]
    while tuple(current) != finish:
        active = [i for i in range(3) if current[i] != finish[i]]
        first = active[0]
        for i in active[1:]:
            if (2*crossed[i]+1)*distance[first] < (2*crossed[first]+1)*distance[i]:
                first = i
        tied = [i for i in active if (2*crossed[i]+1)*distance[first] == (2*crossed[first]+1)*distance[i]]
        for i in tied:
            current[i] += direction[i]
            crossed[i] += 1
        cells.append(tuple(current))
    return tuple(cells)


def surface_ray(start, end):
    """Exact voxels crossed by a surface-ended segment, for cover consumers.

    effect_cover and directional_cover use this for transient face origins.
    Boundary-only cells are excluded; tied crossings enter only the next voxel.
    An endpoint on a face belongs to the cell on the interior of the segment.
    """
    from math import floor
    left, right = point(start), point(end)
    delta = [b-a for a,b in zip(left,right)]
    step = [1 if d>0 else -1 for d in delta]
    current = [floor(a+Fraction(1,2)) - (1 if d<0 and (a+Fraction(1,2))%1==0 else 0)
               for a,d in zip(left,delta)]
    times = [(Fraction(current[i],1)+Fraction(step[i],2)-left[i])/delta[i]
             if delta[i] else None for i in range(3)]
    cells = [tuple(current)]
    while True:
        active = [t for t in times if t is not None]
        if not active or min(active)>=1:
            return tuple(cells)
        first = min(active)
        for i,t in enumerate(times):
            if t==first:
                current[i]+=step[i]
                times[i]+=Fraction(1,abs(delta[i]))
        cells.append(tuple(current))
