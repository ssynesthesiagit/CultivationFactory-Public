"""Exact square-edge crossings for opt-in facing-dependent attack cover."""
from fractions import Fraction

from . import ext
from .gate2_runtime_models import Position


def crossed_edges(start, end):
    """Exact segment, including face origins; vertex crossings count both edges.

    A start on an edge belongs to the cell the ray enters. Crossings at that
    origin are not crossings of a shield farther along the outgoing segment.
    """
    from math import floor
    ax, ay = start[:2]
    bx, by = end[:2]
    dx, dy = bx - ax, by - ay
    sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
    x = floor(ax+Fraction(1,2)) - (1 if dx<0 and (ax+Fraction(1,2))%1==0 else 0)
    y = floor(ay+Fraction(1,2)) - (1 if dy<0 and (ay+Fraction(1,2))%1==0 else 0)
    tx = (x+Fraction(sx,2)-ax)/dx if dx else None
    ty = (y+Fraction(sy,2)-ay)/dy if dy else None
    out = []
    while any(t is not None and t<1 for t in (tx,ty)):
        cross_x = tx is not None and (ty is None or tx <= ty)
        cross_y = ty is not None and (tx is None or ty <= tx)
        nx, ny = x + (sx if cross_x else 0), y + (sy if cross_y else 0)
        pairs = []
        if cross_x:
            pairs.append(("E", "W") if sx > 0 else ("W", "E"))
            tx += Fraction(1, abs(dx))
        if cross_y:
            pairs.append(("S", "N") if sy > 0 else ("N", "S"))
            ty += Fraction(1, abs(dy))
        for leaving, entering in pairs:
            out.append({"cell": [x, y], "edge": leaving, "direction": "exit"})
            out.append({"cell": [nx, ny], "edge": entering, "direction": "enter"})
        x, y = nx, ny
    return out


def sight_rays(engine, attacker, target, *, tactical=False):
    """Clear rays retain altitude; horizontal shield edges use their projection."""
    from .shot_geometry import source_cells
    from .effect_cover import rays
    # A prospective query must not inherit the active actor's accepted route.
    starts = (engine._actor_volume(attacker) if attacker.position.z or target.position.z or engine.grid.finite_heights
               else engine._actor_cells(attacker)) if tactical else source_cells(engine, attacker, target)
    for start in sorted(starts):
        endpoints = engine._actor_volume(target) if len(start) == 3 or target.position.z else engine._actor_cells(target)
        for a, b, _ in rays(engine, [start], endpoints):
            end = (b.x, b.y, b.z) if len(start) == 3 or target.position.z else (b.x, b.y)
            context = {"start": list(start), "end": list(end),
                       "crossed_edges": crossed_edges(start, end)}
            yield a, b, context


def _terrain_cover(engine, a, b, ranged):
    """Terrain/roof cover for one ray; fixed for one unchanged map and ray.

    One tactical cover answer asks the same ray once per eligible ranged attack
    of the same creature, so a read-only frame shares the geometry answer.
    """
    if not ranged:
        return 0
    from .space import SurfacePoint, point, surface_ray
    from .read_queries import shared_query
    if isinstance(a, SurfacePoint) or isinstance(b, SurfacePoint):
        from .effect_cover import ray_bonus
        return shared_query(engine, ('cover.terrain.surface', id(engine.grid), point(a), point(b)),
                            lambda: ray_bonus(engine, surface_ray(a, b), deep=True))
    grid = engine.grid
    three_quarters = frozenset(engine.__dict__.get("_cover_three_quarters", set()))

    def compute():
        value = grid.cover_bonus(a, b)
        if any(cell in three_quarters for cell in grid.ray_cells(a, b)[1:-1]):
            value = 5
        return value

    return shared_query(engine, ('cover.terrain.ray', id(grid), three_quarters, point(a), point(b)), compute)


def cover_bonus(engine, attacker, target, *, ranged, base=0, attack=None, tactical=False, ray_paths=None):
    if not ext.has("directional_cover") and not ext.has("effect_cover"):
        return base
    bonuses = []
    answered = False
    for a, b, ray in (sight_rays(engine, attacker, target, tactical=tactical) if ray_paths is None else ray_paths):
        context = {**ray, "ranged": ranged, "purpose": "attack", "source_actor_id": attacker.entity_id,
                   "attack": attack, "tactical": tactical}
        from .effect_cover import ability_cover
        answers = ability_cover(engine, attacker, target, context)
        answered = answered or bool(answers)
        if any(type(v) is not int or v not in {0, 2, 5} for v in answers):
            raise ValueError("directional cover must be 0, 2 or 5")
        # Combine terrain and edge cover on each ray before choosing the best clear ray.
        terrain = _terrain_cover(engine, a, b, ranged)
        value = max([terrain, *answers])
        # The answer is the least covered clear ray. A ray with no cover makes
        # that minimum zero, so neither further rays nor whether any provider
        # answered can change max(base, 0): stop before pricing them. A malformed
        # answer from a ray past this one is therefore not inspected; valid
        # answers are already checked above, and pricing later rays would undo
        # the early exit.
        if value == 0:
            return base
        bonuses.append(value)
    return max(base, min(bonuses, default=0)) if answered else base


def tactical_cover(engine, attacker, target, position, attacks=None):
    """Cover against known ranged threats at a prospective defender position.

    Preserve the stock anchor-to-anchor terrain baseline. A mixed attacker is
    credited with shelter against any eligible in-range ranged attack. The
    target is a copy; actors, scopes and saved state are never modified.
    """
    base = engine.grid.cover_bonus(attacker.position, position)
    if not ext.has('directional_cover'):
        return base
    from .attack_provenance import ranged_attacks
    threats = ranged_attacks(engine, attacker) if attacks is None else attacks
    projected = target.model_copy(update={'position': position})
    distance = engine._distance_actor_to_actor(attacker, projected)
    threats = tuple(attack for attack in threats if attack.get('ranged')
                    and distance <= int(attack.get('range_ft') or 0))
    if not threats:
        return base
    ray_paths = tuple(sight_rays(engine, attacker, projected, tactical=True))
    values = [cover_bonus(engine, attacker, projected, ranged=True, base=base,
                         attack=attack, tactical=True, ray_paths=ray_paths)
              for attack in threats]
    return max(values, default=base)
