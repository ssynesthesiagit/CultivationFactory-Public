"""Pure contact geometry for collision consumers and placed blocking objects.

Used by Brute's Impact Collision and objects.blocker_at. Call only after native
movement rejects a step: this query neither moves actors nor grants knowledge.
All diagonal side placements use the mover's actual current footprint. Missing
object heights retain Grid's existing infinite-column wall semantics.
"""
from itertools import combinations

from .space import point, position


def attempted_cells(engine, mover, destination):
    """Return full 3D cells checked by the rejected native step, without mutation."""
    start, end = point(mover.position), point(destination)
    axes = [i for i in range(3) if start[i] != end[i]]
    return frozenset(cell
        for count in range(1, len(axes) + 1)
        for selected in combinations(axes, count)
        for cell in engine._actor_volume(mover, position=position(tuple(
            end[i] if i in selected else start[i] for i in range(3)))))


def blocking_objects(engine, cells):
    """Standing blocking objects intersecting supplied 3D cells, in stable order.

    Objects without Hit Points still block movement; consumers decide whether
    their printed effect can damage that profile. No size/material is inferred.
    """
    from .object_geometry import target_cells
    cells = tuple(cells)
    result = []
    for obj in engine.state.objects.values():
        if obj.destroyed or not (obj.component or {}).get('blocks'):
            continue
        footprint = {(p.x, p.y) for p in target_cells(engine, obj)}
        bottom = obj.position.z * engine.grid.square_size_ft
        if any((x, y) in footprint and (obj.height_ft is None or
               z * engine.grid.square_size_ft < bottom + obj.height_ft and
               (z + 1) * engine.grid.square_size_ft > bottom)
               for x, y, z in cells):
            result.append(obj)
    return tuple(sorted(result, key=lambda obj: obj.object_id))


def blocking_creatures(engine, mover, cells):
    """Live physical contacts, including unperceived bodies; grants no knowledge."""
    cells = frozenset(cells)
    return tuple(sorted((actor for actor in engine.state.actors.values()
        if actor.entity_id != mover.entity_id and actor.active and engine._on_battlefield(actor)
        and not engine._shared_occupancy_pair(mover.entity_id, actor.entity_id)
        and cells.intersection(engine._actor_volume(actor))), key=lambda actor: actor.entity_id))


def blocking_terrain(engine, mover, destination, cells):
    """Whether authored/zone terrain physically blocks this attempted step.

    Map bounds are an execution limit, not an inferred physical wall. Remove
    runtime objects through the shared read-only Asset geometry contract so an
    undersized object cannot masquerade as terrain after source eligibility.
    """
    if engine.state.objects:
        from .asset_anchor_runtime import without_objects
        grid = without_objects(engine, tuple(engine.state.objects)).grid
    else:
        grid = engine.grid
    cells = tuple(cells)
    if any(grid.in_bounds((x, y)) and grid.terrain_at((x, y, z), 'BLOCKED') for x, y, z in cells):
        return True
    if not all(grid.in_bounds((x, y)) for x, y, _ in cells):
        return False
    return not grid.volume_step_legal(mover.position, destination, occupied_cells=(),
                                      footprint=engine._footprint(mover))
