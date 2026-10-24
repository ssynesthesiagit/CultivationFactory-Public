"""Shared free willing movement for Bojutsu, Path and Needle physical routes.

routes uses the moving creature's footprint, drag, fear and difficult terrain.
step commits that creature's physical path without spending anybody's ordinary
movement or provoking exit OAs; hazards and entry riders still apply per square.
forced_route is Bojutsu's shared physical forced-route helper: it offers the
standard victim/ally forced-movement checkpoint once before traversal, honors
the remaining distance, and rechecks footprint/occupancy at every square.
"""
from __future__ import annotations


def routes(engine, actor, distance):
    from .needle import cell_id
    from .frightened_movement import path_allowed
    if engine._effective_speed(actor) <= 0:
        return {}
    found = engine.grid.reachable(actor.position, movement_ft=distance // engine._drag_multiplier(actor),
        occupied_cells=engine._occupied_cells_except(actor.entity_id),
        difficult_cells=engine._hostile_difficult_cells(actor), footprint=engine._footprint(actor))
    return {cell_id(cell): path for cell, (path, cost) in found.items()
            if cell != actor.position and cost > 0 and path_allowed(engine, actor, path)}


def step(engine, actor, path, source):
    """Check the full willing route for visible fear, including direct callers.

    Forced movement uses forced_route and is exempt from this willing-path veto.
    Preserve existing entry-interruption behavior: through-creature routes may
    have intermediate occupied squares that are not legal stopping locations.
    """
    from .. import typed_reactions
    from .frightened_movement import path_allowed

    if not path_allowed(engine, actor, path):
        return
    for cell in path[1:]:
        previous = actor.position
        actor.position = cell
        engine._append_event("MOVEMENT_COMMITTED", source, actor_id=actor.entity_id,
            payload={"destination": cell.model_dump(mode="json"), "cost_ft": 0,
                     "without_provoking": True, "path": [previous.model_dump(mode="json"), cell.model_dump(mode="json")]})
        dragged, drag_stopped = engine._drag_along(actor)
        for other_id, dragged_path in dragged.items():
            engine._append_event("MOVEMENT_COMMITTED", source, actor_id=other_id,
                payload={"destination": dragged_path[-1].model_dump(mode="json"), "cost_ft": 0, "forced": True,
                         "dragged_by": actor.entity_id, "path": [square.model_dump(mode="json") for square in dragged_path]})
        engine._resolve_qi_hazard(actor)
        engine._resolve_zone_entry_triggers(actor)
        engine._remove_zone_leave_conditions(actor)
        if actor.active and engine.state.terminal_result is None:
            typed_reactions.on_creature_event(engine, actor, "moved", moved_ft=int(engine.grid.distance_ft(previous, cell)))
            typed_reactions.on_moved_geometry(engine, actor, previous, cell)
        if drag_stopped or not actor.active or actor.position != cell or engine._effective_speed(actor) <= 0 or engine.state.terminal_result is not None:
            break


def forced_route(engine, actor, path, source, source_actor):
    """Commit a legal forced path after reactions; never overwrite interrupted movement."""
    from .. import typed_reactions, zones

    if len(path) < 2 or not actor.active or actor.position != path[0]:
        return
    distance = sum(int(engine.grid.distance_ft(a, b)) for a, b in zip(path, path[1:]))
    remaining = typed_reactions.on_forced_movement(engine, actor, source_actor, distance)
    if not actor.active or actor.position != path[0] or engine.state.terminal_result is not None:
        return
    for cell in path[1:]:
        previous = actor.position
        cost = int(engine.grid.distance_ft(previous, cell))
        if cost > remaining or not engine.grid.volume_step_legal(previous, cell,
                occupied_cells=engine._occupied_volumes_except(actor.entity_id), footprint=engine._footprint(actor)):
            break
        remaining -= cost
        actor.position = cell
        engine._append_event("MOVEMENT_COMMITTED", source, actor_id=actor.entity_id,
            payload={"destination": cell.model_dump(mode="json"), "cost_ft": 0, "forced": True,
                     "path": [previous.model_dump(mode="json"), cell.model_dump(mode="json")]})
        zones.on_moved(engine, actor, previous, cell, forced=True)
        if not actor.active or actor.position != cell or engine.state.terminal_result is not None:
            break


def volume_route(engine, actor, path, source):
    """Free forced placement: reject an initially blocked route before any movement.

    The caller authorizes the path and exemption from movement payment and OAs.
    Preflight includes every segment and the full destination volume. Zone entry,
    leave and following geometry run per segment through the shared placement seam.
    Effects can interrupt travel; never overwrite their relocation or removal.
    """
    from .needle import step_to

    if len(path) < 2 or not actor.active or actor.position != path[0]:
        return False
    def legal(start, end):
        occupied = engine._occupied_volumes_except(actor.entity_id)
        return (engine.grid.volume_legal(end, footprint=engine._footprint(actor), occupied_cells=occupied)
                and engine.grid.volume_step_legal(start, end, footprint=engine._footprint(actor), occupied_cells=occupied))
    if not all(legal(start, end) for start, end in zip(path, path[1:])):
        return False
    for start, end in zip(path, path[1:]):
        if not actor.active or engine.state.terminal_result is not None or actor.position != start or not legal(start, end):
            return False
        step_to(engine, actor, end, source, forced=True)
        if not actor.active or actor.position != end:
            return False
    return actor.position == path[-1]


def forced_routes(engine, mover, viewer, origin, reach):
    """Observed physical repositioning with a direct-distance route bound.

    Ignore movement-price terrain and Speed: this is forced distance. Preserve
    native 3D footprint, walls, roofs and diagonal volume checks. The viewer's
    known creatures supply menu occupancy; native forced-step execution rechecks
    actual occupancy and interruptions. No caller creates a route or effect.
    """
    from collections import deque
    from itertools import product
    from ..gate2_runtime_models import Position
    from ..target_knowledge import actors_for
    from ..space import point
    size = engine.grid.square_size_ft
    if type(reach) is not int or reach <= 0 or not mover.active:
        return {}
    occupied = {point(cell) for actor in actors_for(engine, viewer)
                if actor.active and actor.entity_id != mover.entity_id for cell in engine._actor_volume(actor)}
    footprint = engine._footprint(mover)
    start = mover.position
    # Both endpoints are within Staff reach. Include the moving footprint and
    # the source footprint in the finite distance bound, including altitude.
    extent = max([1, *(max(abs(p[0]-origin.position.x), abs(p[1]-origin.position.y), abs(p[2]-origin.position.z))
                      for p in engine._actor_volume(origin))])
    maximum = max(1, int(engine.grid.distance_ft(start, origin.position)) // size + reach // size + extent)
    queue = deque([start]); paths = {start: (start,)}; result = {}
    steps = [v for v in product((-1, 0, 1), repeat=3) if any(v)]
    while queue:
        current = queue.popleft(); path = paths[current]; used = len(path)-1
        if (current != start and engine._distance_actor_to_cell(origin, current) <= reach
                and used*size <= int(engine.grid.distance_ft(start, current))):
            result[current] = path
        if used >= maximum:
            continue
        for dx, dy, dz in steps:
            x, y, z = current.x+dx, current.y+dy, current.z+dz
            if z < 0 or z > max(start.z, origin.position.z)+maximum or not engine.grid.in_bounds((x, y)):
                continue
            cell = Position(x=x, y=y, z=z)
            if cell in paths or not engine.grid.volume_step_legal(current, cell, footprint=footprint, occupied_cells=occupied):
                continue
            paths[cell] = (*path, cell); queue.append(cell)
    return result
