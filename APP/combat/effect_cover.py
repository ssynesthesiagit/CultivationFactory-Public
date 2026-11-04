"""Read-only origin-cell cover shared by native attacks and spatial saves.

Terrain/objects, zone cover and directional edges use the same ray helpers.
Attack queries retain historical visibility and ability restrictions. Effect
queries separate physical blockage from obscurement and may originate at a
single point instead of impersonating a creature with its whole footprint.
"""
from .space import SurfacePoint, point, position, projection, ray as spatial_ray, surface_ray


def rays(engine, origins, targets, *, purpose='attack'):
    grid = engine.grid
    for a in sorted({point(cell) for cell in origins}):
        for b in sorted({point(cell) for cell in targets}):
            start, end = position(a), position(b)
            if isinstance(start, SurfacePoint) or isinstance(end, SurfacePoint):
                from .terrain_occlusion import segment_clear
                clear = segment_clear(grid, start, end, physical=purpose!='attack',
                                      obscured_cells=engine._obscured_cells() if purpose=='attack' else ())
                if clear:
                    yield start, end, surface_ray(start,end)
                continue
            ray = spatial_ray(start, end) if start.z or end.z else grid.ray_cells(start, end)
            if purpose == 'attack':
                clear = grid.line_of_sight(start, end, obscured_cells=engine._obscured_cells())
            else:
                clear = (not grid.roof_ray_blocked(start, end)
                         and not any(grid.terrain_at(cell, 'BLOCKED') for cell in ray[1:]))
            if clear:
                yield start, end, ray


def ray_bonus(engine, ray, *, deep=False):
    grid = engine.grid
    deep_cells = engine.__dict__.get('_cover_three_quarters', set()) if deep else set()
    terrain = max((5 if projection(cell) in deep_cells else 2
                   for cell in ray[1:-1] if grid.terrain_at(cell, 'SIMPLE_COVER')), default=0)
    roof = grid.roof_cover_bonus(position(ray[0]), position(ray[-1])) if ray else 0
    return max(terrain, roof)


def terrain_bonus(engine, origins, targets, *, purpose='attack', deep=False):
    return min((ray_bonus(engine, ray, deep=deep) for _, _, ray in
                rays(engine, origins, targets, purpose=purpose)), default=0)


def ability_cover(engine, source, target, context):
    """Shared per-ray provider dispatch for actual attacks and explicit queries.

    The caller combines replies by maximum with terrain, then takes the least
    covered clear ray. Legacy scalar attack cover remains the caller's floor.
    """
    from . import ext
    context = {**context, 'origin_cells': context.get('origin_cells') or [context['start']]}
    return [*ext.run_strict('directional_cover', engine, source, target, context),
            *ext.run_strict('effect_cover', engine, source, target, context)]


def query(engine, origin_cells, source_actor_id, target, *, purpose='effect', target_cells=None):
    """Return {bonus: 0|2|5, blocked: bool}; empty origins are unknown, never inferred."""
    from . import ext
    from .directional_cover import crossed_edges
    if purpose not in ('attack', 'effect'):
        raise ValueError('cover purpose must be attack or effect')
    origins = tuple(sorted({point(cell) for cell in origin_cells}))
    targets = tuple(engine._actor_volume(target) if target_cells is None else target_cells)
    if not origins or not targets:
        return {'bonus': 0, 'blocked': False}
    source = engine.state.actors.get(source_actor_id)
    physical = list(rays(engine, origins, targets, purpose='effect'))
    selected = physical if purpose == 'effect' else list(rays(engine, origins, targets))
    values = []
    bodies = {cell for actor in engine.state.actors.values()
              if actor.active and actor.entity_id not in (source_actor_id, target.entity_id)
              for cell in engine._actor_volume(actor)} if purpose == 'effect' else set()
    for a, b, ray in selected:
        context = {'start': list(point(a)), 'end': list(point(b)), 'crossed_edges': crossed_edges(point(a), point(b)),
                   'purpose': purpose, 'ranged': purpose == 'attack', 'source_actor_id': source_actor_id,
                   'origin_cells': [list(cell) for cell in origins]}
        answers = ability_cover(engine, source, target, context)
        if any(type(v) is not int or v not in (0, 2, 5) for v in answers):
            raise ValueError('effect cover must be 0, 2 or 5')
        body = 2 if any(point(cell) in bodies for cell in ray[1:-1]) else 0
        values.append(max([ray_bonus(engine, ray, deep=True), body, *answers]))
    # Legacy scalar cover hooks were documented for attacks; do not silently
    # broaden attack-only protection to saves. Spatial providers use effect_cover.
    legacy = ext.run('cover', engine, source, target) if purpose == 'attack' and source is not None else []
    return {'bonus': max([min(values, default=0), *[int(v) for v in legacy]]), 'blocked': not physical}
