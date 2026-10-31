"""Shared physical routes for Bojutsu, Path, Needle and reaction movement.

routes/step share native granted_movement geometry and resolution: footprints,
terrain, drag, fear, entry checkpoints, interrupted transit recovery and OAs.
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


@contextmanager
def crossing(engine, actor, occupant_id):
    """Scope one extra difficult-terrain crossing for this mover, not others."""
    previous = getattr(engine, '_rider_crossing', None)
    engine._rider_crossing = {'actor_id': actor.entity_id, 'occupant_id': occupant_id, 'entered': False}
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
        return 'difficult'
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


def crossing_routes(engine, actor, feet, occupant_id, *, edge_allowed=None):
    """Stateful native-cost search: before, inside, then outside one crossing.

    Search state includes crossing progress, not just a destination. A cheaper
    route around a creature must not hide a legal route through it (White Wing).
    Geometry and edge prices are the same public queries native movement uses.
    """
    from heapq import heappush, heappop
    from itertools import count, product
    from .. import flight
    from ..creature_passage import geometry
    from ..terrain_materials import placement_legal
    from ..voluntary_movement import edge_predicate, path_allowed
    from ..gate2_runtime_models import Position

    if not actor.active or engine._effective_speed(actor) <= 0:
        return {}
    occupant = engine.state.actors.get(occupant_id)
    volume = set(engine._actor_volume(occupant)) if occupant is not None else set()
    def inside(cell):
        return bool(set(engine._actor_volume(actor, cell)) & volume)
    out = {}
    restriction = edge_predicate(engine, actor)
    modes = ['walk', 'fly'] if flight.profile(engine, actor).speed_ft else ['walk']
    for mode in modes:
        start = (actor.position, (1 if inside(actor.position) else 0) if occupant is not None else 2)
        serial = count()
        queue = [(0, next(serial), start)]
        prices, paths = {start: 0}, {start: (actor.position,)}
        difficult = engine._hostile_difficult_cells(actor) | geometry(engine, actor, observed=True)[2]
        offsets = tuple(product((-1, 0, 1), repeat=3 if mode == 'fly' else 2))
        while queue:
            cost, _, node = heappop(queue)
            if cost != prices[node]:
                continue
            cell, phase = node
            if phase == 2 and cell != actor.position and placement_legal(engine, actor, cell, mode, observed=True):
                if path_allowed(engine, actor, paths[node]) and (cell not in out or cost < out[cell][1]):
                    out[cell] = (paths[node], cost, mode)
            if cost >= feet:
                continue
            for delta in offsets:
                if not any(delta):
                    continue
                x, y, z = cell.x+delta[0], cell.y+delta[1], cell.z+(delta[2] if mode == 'fly' else 0)
                if min(x, y, z) < 0:
                    continue
                nxt = Position(x=x, y=y, z=z)
                enters = inside(nxt)
                if phase == 2 and enters:
                    continue
                new_phase = 1 if enters else 2 if phase else 0
                if ((restriction is not None and not restriction(cell, nxt))
                        or (edge_allowed is not None and not edge_allowed(cell, nxt))):
                    continue
                if not flight.step_allowed(engine, actor, cell, nxt, mode=mode, observed=True):
                    continue
                paid = cost + flight.step_cost(engine, actor, cell, nxt, mode, difficult)
                key = (nxt, new_phase)
                if paid <= feet and paid < prices.get(key, feet+1):
                    prices[key], paths[key] = paid, (*paths[node], nxt)
                    heappush(queue, (paid, next(serial), key))
    return out


def routes(engine, actor, distance, *, through=(), require_through=False, edge_allowed=None):
    """Free endpoints, with optional one-creature passage, priced by native rules.

    Each named creature is considered independently, never as permission to
    cross the entire roster. Independent native passage grants still apply.
    require_through is for an ability whose ending result needs actual transit.
    """
    from ..granted_movement import routes as native_routes
    from .needle import cell_id

    out, prices = {}, {}
    for occupant_id in (None, *sorted(set(through))):
        if occupant_id is None and require_through:
            continue
        if occupant_id:
            occupant = engine.state.actors.get(occupant_id)
            if (occupant is None or not occupant.active or occupant is actor
                    or engine._distance_actor_to_actor(actor, occupant) > distance):
                continue
        with crossing(engine, actor, occupant_id):
            found = (crossing_routes(engine, actor, distance, occupant_id, edge_allowed=edge_allowed)
                     if occupant_id or edge_allowed is not None else native_routes(engine, actor, distance))
            for cell, (path, cost, mode) in found.items():
                entries = crossed(engine, actor, path, occupant_id) if occupant_id else 0
                if entries > 1 or (require_through and entries != 1):
                    continue
                key = cell_id(cell)
                if key not in prices or cost < prices[key]:
                    out[key] = PassageRoute(tuple(path), mode, occupant_id)
                    prices[key] = cost
    return out


def step(engine, actor, path, source, *, distance=None, provokes=False, ignore_oa_from=()):
    """Commit through native per-step checkpoints, preserving ordinary movement.

    The route owns only its extra passage permission. Native execution rechecks
    live geometry, consumes first-entry notices, and recovers an interrupted
    transit to a free space. Return the actual grant budget spent.
    """
    from ..granted_movement import path_cost, resolve_path

    occupant_id = path.through if isinstance(path, PassageRoute) else None
    if occupant_id and crossed(engine, actor, path, occupant_id) > 1:
        raise ValueError('A route grants only one crossing of a creature')
    with crossing(engine, actor, occupant_id):
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
