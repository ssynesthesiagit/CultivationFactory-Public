"""Shared free willing movement for Bojutsu, Path and Needle physical routes.

routes uses the moving creature's footprint, drag, fear and difficult terrain.
step commits that creature's physical path without spending anybody's ordinary
movement or provoking exit OAs; hazards and entry riders still apply per square.
forced_route is Bojutsu's shared physical forced-route helper: it offers the
standard victim/ally forced-movement checkpoint once before traversal, honors
the remaining distance, and rechecks footprint/occupancy at every square.
"""
from __future__ import annotations


def routes(engine, actor, distance, *, native=False, source=None):
    from .needle import cell_id
    if native:
        from ..granted_movement import routes as native_routes,Route
        return {cell_id(cell):Route(tuple(path),mode) for cell,(path,cost,mode) in native_routes(engine,actor,distance,source=source).items()}
    from .frightened_movement import path_allowed
    if engine._effective_speed(actor) <= 0:
        return {}
    found = engine.grid.reachable(actor.position, movement_ft=distance // engine._drag_multiplier(actor),
        occupied_cells=engine._occupied_cells_except(actor.entity_id),
        difficult_cells=engine._hostile_difficult_cells(actor), footprint=engine._footprint(actor))
    return {cell_id(cell): path for cell, (path, cost) in found.items()
            if cell != actor.position and cost > 0 and path_allowed(engine, actor, path)}


def step(engine, actor, path, source, *, native=False, feet=None, intent=None):
    """Check the full willing route for visible fear, including direct callers.

    Forced movement uses forced_route and is exempt from this willing-path veto.
    Preserve existing entry-interruption behavior: through-creature routes may
    have intermediate occupied squares that are not legal stopping locations.
    """
    if native and (intent is not None or getattr(engine,'_active_intent',None) is not None):
        from ..granted_movement import resolve_path
        if type(feet) is not int:raise ValueError('Native rider movement requires its printed distance allowance.')
        return resolve_path(engine,actor,path,source,feet=feet,intent=intent,provokes=False)
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
