"""Shared physical routes for Bojutsu, Path, Needle and reaction movement.

routes preserves legacy grid reachability unless through-creature IDs opt in
to native granted_movement searches. checkpoint_step uses native resolution:
footprints, terrain, drag, fear, entry checkpoints, transit recovery and OAs.
The legacy step contract remains direct, free, non-provoking traversal for
Bojutsu, Needle, Black Current and other callers that authorize their own path.
Empty Cup, Flowing Evasion and White Wing can request one scoped creature
crossing. Permission exists only while quoting/resolving that route; queries
never spend it, first entry consumes it, interior steps retain it, exit bars
re-entry. Nested moves, pauses and errors restore the enclosing permission.
forced_route and volume_route remain shared forced-placement helpers.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from ..granted_movement import Route
from . import hook


@dataclass(frozen=True)
class PassageRoute(Route):
    """Query-only route entitlement; never serialized as fight state."""
    through: str | None = None
    passage_cost: str = 'difficult'


@contextmanager
def crossing(engine, actor, occupant_id, cost='difficult'):
    """Scope one passage grant, not terrain immunity, for this mover only."""
    previous = getattr(engine, '_rider_crossing', None)
    engine._rider_crossing = {'actor_id': actor.entity_id, 'occupant_id': occupant_id, 'entered': False, 'cost': cost}
    try:
        yield
    finally:
        engine._rider_crossing = previous


@hook('pass_through')
def route_permission(engine, mover, occupant):
    scope = getattr(engine, '_rider_crossing', None) or {}
    if scope.get('actor_id') != mover.entity_id or scope.get('occupant_id') != occupant.entity_id:
        return None
    if not scope['entered'] or set(engine._actor_volume(mover)) & set(engine._actor_volume(occupant)):
        return scope['cost']
    return None


@hook('pass_through_entered')
def consume_crossing(engine, mover, occupant, intent):
    scope = getattr(engine, '_rider_crossing', None) or {}
    if scope.get('actor_id') == mover.entity_id and scope.get('occupant_id') == occupant.entity_id:
        scope['entered'] = True


def crossed(engine, actor, path, occupant_id):
    """Number of separate entries into this creature's volume along a route."""
    occupant = engine.state.actors[occupant_id]
    volume = set(engine._actor_volume(occupant))
    inside = [bool(set(engine._actor_volume(actor, cell)) & volume) for cell in path]
    return sum(not before and after for before, after in zip(inside, inside[1:]))


def routes(engine, actor, distance, *, through=(), require_through=False, edge_allowed=None,
           passage_cost='difficult'):
    """Legacy grid routes by default; native search for one-creature passage.

    With no through IDs, preserve the original paths, costs and return types.
    Each named creature is considered independently, never as permission to
    cross the entire roster. Independent native passage grants still apply.
    require_through is for an ability whose ending result needs actual transit.
    passage_cost='free' waives only the creature surcharge (Empty Cup's opposite
    side alternative); real terrain, dragging and posture still cost normally.
    """
    from .needle import cell_id
    from .frightened_movement import path_allowed

    if not through:
        if engine._effective_speed(actor) <= 0:
            return {}
        found = engine.grid.reachable(actor.position, movement_ft=distance // engine._drag_multiplier(actor),
            occupied_cells=engine._occupied_cells_except(actor.entity_id),
            difficult_cells=engine._hostile_difficult_cells(actor), footprint=engine._footprint(actor))
        return {cell_id(cell): path for cell, (path, cost) in found.items()
                if cell != actor.position and cost > 0 and path_allowed(engine, actor, path)}

    from ..granted_movement import routes as native_routes, CrossingConstraint
    from ..gate2_runtime_models import Position
    from ..target_knowledge import knowledge

    out, prices = {}, {}
    for occupant_id in (None, *sorted(set(through))):
        if occupant_id is None and require_through:
            continue
        if occupant_id:
            occupant = engine.state.actors.get(occupant_id)
            if occupant is None or not occupant.active or occupant is actor:
                continue
            known = knowledge(engine, actor, occupant)
            if known is None or known.mode != 'DIRECT' or engine._distance_actor_to_actor(actor, occupant) > distance:
                continue
        constraint = None
        if occupant_id:
            volume = set(engine._actor_volume(occupant))
            constraint = CrossingConstraint(lambda cell: bool(set(engine._actor_volume(actor,
                Position(x=cell[0], y=cell[1], z=cell[2] if len(cell) > 2 else 0))) & volume),
                required=require_through)
        with crossing(engine, actor, occupant_id, passage_cost):
            found = native_routes(engine, actor, distance, crossing=constraint, edge_allowed=edge_allowed)
            for cell, (path, cost, mode) in found.items():
                entries = crossed(engine, actor, path, occupant_id) if occupant_id else 0
                if entries > 1 or (require_through and entries != 1):
                    continue
                key = cell_id(cell)
                if key not in prices or cost < prices[key]:
                    out[key] = PassageRoute(tuple(path), mode, occupant_id, passage_cost)
                    prices[key] = cost
    return out


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


def checkpoint_step(engine, actor, path, source, *, distance=None, provokes=False, ignore_oa_from=()):
    """Commit through native per-step checkpoints, preserving ordinary movement.

    The route owns only its extra passage permission. Native execution rechecks
    live geometry, consumes first-entry notices, and recovers an interrupted
    transit to a free space. Return the actual grant budget spent.
    """
    from ..granted_movement import path_cost, resolve_path

    occupant_id = path.through if isinstance(path, PassageRoute) else None
    if occupant_id and crossed(engine, actor, path, occupant_id) > 1:
        raise ValueError('A route grants only one crossing of a creature')
    with crossing(engine, actor, occupant_id, path.passage_cost if isinstance(path, PassageRoute) else 'difficult'):
        feet = path_cost(engine, actor, path) if distance is None else distance
        return resolve_path(engine, actor, path, source, feet=feet,
                            provokes=provokes, ignore_oa_from=ignore_oa_from)


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
