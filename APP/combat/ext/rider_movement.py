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


def step(engine, actor, path, source, *, volume=False):
    """Check the full willing route for visible fear, including direct callers.

    Forced movement uses forced_route and is exempt from this willing-path veto.
    Preserve existing entry-interruption behavior: through-creature routes may
    have intermediate occupied squares that are not legal stopping locations.
    """
    from .. import typed_reactions
    from .frightened_movement import path_allowed

    if not path_allowed(engine, actor, path) or (volume and
            (len(path) < 2 or not actor.active or actor.position != path[0] or engine._effective_speed(actor) <= 0)):
        return
    for cell in path[1:]:
        previous = actor.position
        if volume and not engine.grid.volume_step_legal(previous, cell, footprint=engine._footprint(actor),
                                                       occupied_cells=engine._occupied_volumes_except(actor.entity_id)):
            break
        if volume and not path_allowed(engine, actor, [previous, cell]):
            break
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
        if cost > remaining or not engine.grid.step_legal(previous, cell,
                occupied_cells=engine._occupied_cells_except(actor.entity_id), footprint=engine._footprint(actor)):
            break
        remaining -= cost
        actor.position = cell
        engine._append_event("MOVEMENT_COMMITTED", source, actor_id=actor.entity_id,
            payload={"destination": cell.model_dump(mode="json"), "cost_ft": 0, "forced": True,
                     "path": [previous.model_dump(mode="json"), cell.model_dump(mode="json")]})
        zones.on_moved(engine, actor, previous, cell, forced=True)
        if not actor.active or actor.position != cell or engine.state.terminal_result is not None:
            break


def vertical_options(engine, actor, feet, viewer=None, *, willing=False):
    """Enumerate legal 3D routes within ``feet`` (kick and Falcon).

    Search adjacent 3D grid cells so descent, diagonal travel, and routes that
    climb around an obstacle remain available. Every edge uses the grid's
    physical volume-step rules and each destination is visibility checked.
    """
    from .needle import cell_id
    import heapq
    from itertools import product
    from ..voluntary_movement import edge_predicate

    if willing and engine._effective_speed(actor) <= 0:
        return {}
    allowed = edge_predicate(engine, actor) if willing else None
    drag = engine._drag_multiplier(actor) if willing else 1
    difficult = engine._hostile_difficult_cells(actor) if willing else set()
    origin = actor.position
    occupied = engine._occupied_volumes_except(actor.entity_id)
    best = {origin: (0, [origin])}
    queue = [(0, 0, origin)]
    serial = 0
    while queue:
        spent, _, cell = heapq.heappop(queue)
        if best.get(cell, (None,))[0] != spent:
            continue
        for dx, dy, dz in product((-1, 0, 1), repeat=3):
            if not (dx or dy or dz):
                continue
            nxt = cell.model_copy(update={"x": cell.x + dx, "y": cell.y + dy, "z": cell.z + dz})
            if not (0 <= nxt.x < engine.grid.width and 0 <= nxt.y < engine.grid.height and nxt.z >= 0):
                continue
            if not engine.grid.volume_step_legal(cell, nxt, footprint=engine._footprint(actor), occupied_cells=occupied):
                continue
            if allowed is not None and not allowed(cell, nxt):
                continue
            rough = (nxt.x, nxt.y) in difficult or (nxt.x, nxt.y, nxt.z) in difficult
            step = int(engine.grid.distance_ft(cell, nxt)) * drag * (2 if rough else 1)
            total = spent + step
            if total > feet or total >= best.get(nxt, (feet + 1, []))[0]:
                continue
            serial += 1
            best[nxt] = (total, [*best[cell][1], nxt])
            heapq.heappush(queue, (total, serial, nxt))
    options = {}
    for destination, (_, path) in best.items():
        if destination == origin or not engine.grid.volume_legal(destination, footprint=engine._footprint(actor), occupied_cells=occupied):
            continue
        if viewer is not None and not engine._line_of_sight_actor_to_cell(viewer, destination):
            continue
        options[cell_id(destination)] = path
    return options


def forced_route_3d(engine, actor, path, source, source_actor):
    """Forced movement along a route that may rise: the shared forced-movement checkpoint,
    then per-segment placement through the volume seam (a kick's vertical trajectory).
    A destination left unsupported falls through the ordinary falling system."""
    from .. import typed_reactions, zones

    if len(path) < 2 or not actor.active or actor.position != path[0]:
        return
    distance = sum(int(engine.grid.distance_ft(a, b)) for a, b in zip(path, path[1:]))
    remaining = typed_reactions.on_forced_movement(engine, actor, source_actor, distance)
    if not actor.active or actor.position != path[0] or engine.state.terminal_result is not None:
        return
    for nxt in path[1:]:
        previous = actor.position
        cost = int(engine.grid.distance_ft(previous, nxt))
        if cost > remaining or not engine.grid.volume_step_legal(previous, nxt, footprint=engine._footprint(actor),
                                                                 occupied_cells=engine._occupied_volumes_except(actor.entity_id)):
            break
        remaining -= cost
        actor.position = nxt
        engine._append_event("MOVEMENT_COMMITTED", source, actor_id=actor.entity_id,
                             payload={"destination": nxt.model_dump(mode="json"), "cost_ft": 0, "forced": True,
                                      "path": [previous.model_dump(mode="json"), nxt.model_dump(mode="json")]})
        zones.on_moved(engine, actor, previous, nxt, forced=True)
        if not actor.active or actor.position != nxt or engine.state.terminal_result is not None:
            break


def volume_route(engine, actor, path, source):
    """Free forced placement: reject an initially blocked route before any movement.
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
