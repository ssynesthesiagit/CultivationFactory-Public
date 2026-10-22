"""Native surface swimming on explicitly authored water terrain.

The map editor's ordinary terrain producer persists water squares with the
battlefield. Capabilities come from conditions or the pure swimming hook;
absence of either a Swim Speed or water is inert. Routes share native movement
payment, collision, fear, hazards and opportunity attacks with other modes.
This module grants neither water breathing nor underwater perception/combat.
"""
import heapq
from itertools import product

from .gate2_runtime_models import Position


def speed(engine, actor):
    from . import ext
    rows = [c.data for c in actor.conditions.values()]
    rows += ext.run_strict("swimming", engine, actor)
    result = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Swimming providers must return capability dictionaries")
        amount = row.get("swim_speed_ft", 0)
        if type(amount) is not int or amount < 0:
            raise ValueError("Swim Speed must be nonnegative integer feet")
        result = max(result, amount)
    return result if actor.active and engine._effective_speed(actor) > 0 else 0


def water_cells(engine):
    """Only physical water declared by the native map terrain catalogue."""
    from .zones import terrain_rules
    water = {key for key, row in terrain_rules()["terrains"].items() if row.get("material") == "water"}
    return {(int(x), int(y), 0) for row in (engine.battlefield_document or {}).get("map_terrain", [])
            if row.get("terrain") in water for x, y in row.get("cells", [])}


def in_water(engine, actor, position, water=None):
    water = water_cells(engine) if water is None else water
    return all((x, y, position.z) in water for x, y in engine._actor_cells(actor, position))


def step_allowed(engine, actor, start, end):
    """A surface Swim Speed operates only along recorded water squares."""
    return (speed(engine, actor) > 0 and start.z == end.z == 0
            and in_water(engine, actor, start) and in_water(engine, actor, end))


def routes(engine, actor, *, grant_ft=None):
    """All reachable water endpoints; no truncation or duplicate scheduler."""
    if not speed(engine, actor):
        return {}
    water = water_cells(engine)
    if not in_water(engine, actor, actor.position, water):
        return {}
    from . import flight
    from .voluntary_movement import path_allowed
    budget = flight.remaining(engine, actor, "swim") if grant_ft is None else grant_ft
    start = actor.position
    costs, paths, queue = {start: 0}, {start: (start,)}, [(0, start.x, start.y)]
    while queue:
        cost, x, y = heapq.heappop(queue)
        here = Position(x=x, y=y)
        if cost != costs[here]:
            continue
        for dx, dy in product((-1, 0, 1), repeat=2):
            if dx == dy == 0:
                continue
            if not engine.grid.in_bounds((x + dx, y + dy)):
                continue
            end = Position(x=x + dx, y=y + dy)
            if not in_water(engine, actor, end, water):
                continue
            if not flight.step_allowed(engine, actor, here, end, mode="swim", observed=True):
                continue
            price = cost + flight.step_cost(engine, actor, here, end, "swim", engine._hostile_difficult_cells(actor))
            path = (*paths[here], end)
            if price > budget or price >= costs.get(end, budget + 1) or not path_allowed(engine, actor, path):
                continue
            costs[end], paths[end] = price, path
            heapq.heappush(queue, (price, end.x, end.y))
    from .creature_passage import endpoint_volumes
    occupied = endpoint_volumes(engine, actor, observed=True)
    return {end: (path, costs[end], "swim") for end, path in paths.items() if end != start
            and engine.grid.volume_legal(end, footprint=engine._footprint(actor), occupied_cells=occupied)}
