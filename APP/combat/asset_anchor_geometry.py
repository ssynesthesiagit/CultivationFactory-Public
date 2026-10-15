"""Explicit partial-object cover for created works and native GM profiles.

A tall clear ray does not erase a printed partial-cover profile when the same
origin still has lower target-body rays crossing that object. Actual height,
footprint and source origins remain authoritative; no name or ability is read.
"""
from fractions import Fraction
from .space import point
from .object_geometry import target_cells


def _crosses(origin, end, cell, height_ft):
    """Positive-length segment overlap with the object's native square prism."""
    lower=Fraction(0);upper=Fraction(1)
    for a,b,low,high in zip(origin,end,
            (Fraction(2*cell.x-1,2),Fraction(2*cell.y-1,2),Fraction(cell.z)),
            (Fraction(2*cell.x+1,2),Fraction(2*cell.y+1,2),Fraction(cell.z)+Fraction(height_ft,5))):
        delta=b-a
        if not delta:
            if not low<=a<high:return False
            continue
        lo,hi=sorted(((low-a)/delta,(high-a)/delta))
        lower=max(lower,lo);upper=min(upper,hi)
        if lower>=upper:return False
    return lower<upper and upper>0 and lower<1


def partial_cover(engine, origins, target):
    """Return 0/2/5 from live explicit profiles and the actual target body.

    Pure/default-inert without a profile. Ended/destroyed works contribute no
    geometry. The caller supplies real action/effect origins, including routed
    attacks; the actor's location is never substituted for an explicit origin.
    """
    profiles=[o for o in engine.state.objects.values() if not o.destroyed and o.height_ft
              and (o.component or {}).get('cover') in ('half','three_quarters')
              and not (o.component or {}).get('asset_anchor_runtime',{}).get('ended')]
    if not profiles:return 0
    starts=[point(p) for p in origins];ends=list(engine._actor_volume(target));values=[]
    for origin in starts:
        best=0
        for obj in profiles:
            value=2 if obj.component['cover']=='half' else 5
            if value<=best:continue
            if any(_crosses(origin,b,c,obj.height_ft) for b in ends for c in target_cells(engine,obj)):
                best=value
        values.append(best)
    return min(values,default=0)
