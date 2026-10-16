"""Any-point attack-line intersection of occupied spaces for aura cover.

Each occupied cell is a convex square. Segments between two such squares fill
exactly their convex hull. Strict separating-axis overlap with a guard square
means some attack line crosses its interior; touching an edge alone does not.
No floating point, ray rounding, actor relocation or knowledge mutation.
"""


def _cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _hull(points):
    points=sorted(set(points));lo=[];hi=[]
    for p in points:
        while len(lo)>1 and _cross(lo[-2],lo[-1],p)<=0:lo.pop()
        lo.append(p)
    for p in reversed(points):
        while len(hi)>1 and _cross(hi[-2],hi[-1],p)<=0:hi.pop()
        hi.append(p)
    return lo[:-1]+hi[:-1]


def _square(cell):
    x,y=cell
    return [(2*x,2*y),(2*x+2,2*y),(2*x+2,2*y+2),(2*x,2*y+2)]


def _overlap(first,second):
    for polygon in (first,second):
        for a,b in zip(polygon,polygon[1:]+polygon[:1]):
            nx,ny=a[1]-b[1],b[0]-a[0]
            left=[nx*x+ny*y for x,y in first];right=[nx*x+ny*y for x,y in second]
            if max(left)<=min(right) or max(right)<=min(left):return False
    return True


def crosses(engine,attacker,target,guard):
    """Whether any line from attacker space to target space crosses guard space."""
    # Cover shares the engine's ordinary ranged-attack height gate; this helper
    # supplies the occupied-space projection rather than only anchor centers.
    return any(_overlap(_hull(_square(a)+_square(t)),_square(g))
        for a in engine._actor_cells(attacker) for t in engine._actor_cells(target) for g in engine._actor_cells(guard))


def _box(cell):
    from itertools import product
    return [(2*x+dx,2*y+dy,2*z+dz) for x,y,z in (cell,) for dx,dy,dz in product((0,2),repeat=3)]


def _difference(a,b):return tuple(x-y for x,y in zip(a,b))


def _cross3(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])


def _volume_overlap(first,second):
    """Separating-axis test; all hull face/edge axes are included.

    Superset axes cannot exclude an intersection: intersecting sets overlap on
    every projection. Extra axes avoid an external convex-hull dependency.
    """
    from itertools import combinations
    from math import gcd
    vertices=list(dict.fromkeys(first));axes={(1,0,0),(0,1,0),(0,0,1)}
    def add(axis):
        divisor=gcd(*axis)
        if not divisor:return
        axis=tuple(v//divisor for v in axis)
        if next(v for v in axis if v)<0:axis=tuple(-v for v in axis)
        axes.add(axis)
    for a,b in combinations(vertices,2):
        edge=_difference(a,b)
        for unit in ((1,0,0),(0,1,0),(0,0,1)):add(_cross3(edge,unit))
    for a,b,c in combinations(vertices,3):add(_cross3(_difference(a,b),_difference(a,c)))
    for axis in axes:
        left=[sum(v*n for v,n in zip(p,axis)) for p in vertices]
        right=[sum(v*n for v,n in zip(p,axis)) for p in second]
        if max(left)<=min(right) or max(right)<=min(left):return False
    return True


def crosses_volume(engine,attacker,target,guard):
    """Any-point attack line against the guard's actual native body volume."""
    if not any(a.position.z for a in (attacker,target,guard)):
        return crosses(engine,attacker,target,guard)
    return any(_volume_overlap(_box(a)+_box(t),_box(g)) for a in engine._actor_volume(attacker)
        for t in engine._actor_volume(target) for g in engine._actor_volume(guard))
