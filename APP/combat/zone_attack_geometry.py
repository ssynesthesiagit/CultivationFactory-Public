"""Pure attack-path geometry shared by area plug-ins, including Verdant Growth.

Measure travel through occupied five-foot volumes using the same shape,
height and footprint query as zone membership. Intersections are transient;
no floating-point value is stored in fight state.
"""
import math

from .spatial_areas import positions_inside_zone


def path_distance_ft(engine, zone, attacker, target):
    """Centre-to-centre travel inside the effective zone's grid volume.

    Split at crossed cell faces and test each interval's occupied cell. This
    visits only the ray, reconstructs altitude rather than extruding a drawing,
    and counts overlapping cells once. Tangent-only contact contributes zero.
    """
    start = (attacker.position.x, attacker.position.y, attacker.position.z)
    end = (target.position.x, target.position.y, target.position.z)
    delta = tuple(b - a for a, b in zip(start, end))
    cuts = {0.0, 1.0}
    for a, b, d in zip(start, end, delta):
        if d:
            cuts.update((face + 0.5 - a) / d for face in range(min(a, b), max(a, b)))
    ordered = sorted(cuts)
    total = 0.0
    for lo, hi in zip(ordered, ordered[1:]):
        middle = (lo + hi) / 2
        cell = tuple(math.floor(a + d * middle + 0.5) for a, d in zip(start, delta))
        if positions_inside_zone(engine, (cell,), zone):
            total += hi - lo
    return total * math.sqrt(sum(d * d for d in delta)) * engine.grid.square_size_ft
