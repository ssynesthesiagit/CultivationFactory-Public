"""Seat movement suggestions from redacted observations and legal destinations.

Used by choices, never by combat resolution. Public grid helpers evaluate only
observed geometry; fresh engine menus remain the authority for each step.
"""
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
import re


def observed_grid(view):
    """Public helper for choices: approximate only the perceived map geometry."""
    board = view.get("map") or {}
    regions = []
    for tree in board.get("trees", []):
        regions.append({"terrain_type": "BLOCKED", "movement_cost": 1,
                        "cells": [dict(x=x, y=y) for x, y in tree["cells"]]})
    for terrain in board.get("terrain", []):
        name = terrain.get("name", "").upper()
        if name in {"BLOCKED", "SIGHT_BLOCKED", "SIMPLE_COVER"}:
            regions.append({"terrain_type": name, "movement_cost": 1,
                            "cells": [dict(x=x, y=y) for x, y in terrain["cells"]]})
    # Projection walls are clipped to perceived cells. Rasterize those pieces
    # only, never use the unredacted arena or infer unseen continuations.
    for wall in board.get("walls", []):
        points = wall.get("points", [])
        if points:
            x = min(p[0] for p in points) // 1000
            y = min(p[1] for p in points) // 1000
            regions.append({"terrain_type": "SIGHT_BLOCKED" if wall.get("sight_only") else "BLOCKED",
                            "movement_cost": 1, "cells": [dict(x=x, y=y)],
                            **({"height_ft": wall["height_ft"]} if "height_ft" in wall else {})})
    return SquareGrid({"width_squares": board.get("width", 100),
                       "height_squares": board.get("height", 100),
                       "square_size_ft": 5, "starting_positions": {}, "terrain_regions": regions})


def plausible_after_move(view, action, destination, grid):
    """Filter obvious range/sight failures using public observations only.

    This is a conservative plan suggestion, never combat legality. With no
    printed range, don't move farther from a target currently in range.
    """
    own = next(a for a in view["actors"] if a["entity_id"] == view["fighter"])
    start = Position.model_validate(own["position"])
    end = Position.model_validate(destination)
    positions = {a["entity_id"]: a.get("position") for a in view["actors"]}
    positions.update({o["id"]: {"x": o["x"], "y": o["y"]} for o in view.get("objects", [])})
    anchors = [positions[t] for t in action.get("targets", []) if t != view["fighter"]]
    if action.get("destination"):
        anchors.append(action["destination"])
    ranges = re.findall(r"(\d+)\s*(?:feet|foot|ft)\b", str(action.get("range_label") or ""), re.I)
    for anchor in anchors:
        if not anchor:
            return False
        p = Position.model_validate(anchor)
        bound = max(map(int, ranges)) if ranges else grid.distance_ft(start, p)
        if grid.distance_ft(end, p) > bound or not grid.line_of_sight(end, p):
            return False
    return True


def tactical_moves(view, legal):
    """Return distinct (menu key, purpose) suggestions, without hidden state.

    Cover labels describe an intention, not a guarantee about an unseen foe.
    Memory is a last-seen location, never an assertion of current occupancy.
    """
    own = next(a for a in view["actors"] if a["entity_id"] == view["fighter"])
    if not own.get("position"):
        return []
    start = Position.model_validate(own["position"])
    moves = [(k, Position.model_validate(r["destination"])) for k, r in legal.items()
             if r["action"] == "Move" and r.get("destination")
             and r["destination"] != own["position"]]
    if not moves:
        return []
    grid = observed_grid(view)
    threats = [a for a in view["actors"] if a["entity_id"] != view["fighter"]
               and a.get("active") is not False
               and (own.get("team_id") is None or a.get("team_id") != own.get("team_id"))
               and a.get("position")]
    # Vision still retains remembered allies and legacy unclassified markers.
    # Search must use only observations explicitly remembered as hostile.
    memory = [Position.model_validate(m["position"]) for m in view.get("last_seen", [])
              if m.get("position") and m.get("hostile") == 1]
    anchors = [Position.model_validate(a["position"]) for a in threats] or memory
    result = []
    def add(pair, purpose):
        if pair and pair[0] not in {k for k, _ in result}:
            result.append((pair[0], purpose))
    def distance(a, b):
        return grid.distance_ft(a, b)
    def shelter(p):
        return sum(not grid.line_of_sight(a, p) or bool(grid.cover_bonus(a, p)) for a in anchors)
    if anchors:
        covered = [m for m in moves if shelter(m[1]) > shelter(start)]
        if covered:
            best = min(covered, key=lambda m: (distance(start, m[1]), m[1].z != start.z, -shelter(m[1]), m[0]))
            add(best, "seek cover from visible threats" if threats else "seek cover near the last seen enemy position")
    for actor in sorted(threats, key=lambda a: (distance(start, Position.model_validate(a["position"])), a["entity_id"])):
        target = Position.model_validate(actor["position"])
        name = actor.get("display_name") or "the visible enemy"
        closer = [m for m in moves if distance(m[1], target) < distance(start, target)]
        if closer:
            add(min(closer, key=lambda m: (distance(m[1], target), m[1].z != start.z, -shelter(m[1]), distance(start, m[1]), m[0])), "close in on " + name)
        farther = [m for m in moves if distance(m[1], target) > distance(start, target)]
        if farther:
            add(min(farther, key=lambda m: (-shelter(m[1]), m[1].z != start.z, -distance(m[1], target), distance(start, m[1]), m[0])), "put distance between you and " + name + "; leaving reach may provoke an attack")
        watching = [m for m in moves if grid.line_of_sight(m[1], target)]
        if watching:
            add(min(watching, key=lambda m: (distance(start, m[1]), m[1].z != start.z, -grid.cover_bonus(target, m[1]), m[0])),
                "reposition and keep " + name + " in sight")
    if threats and not result:
        add(min(moves, key=lambda m: (distance(start, m[1]), m[1].z != start.z, m[0])),
            "reposition carefully around the visible threats")
    if not threats:
        if memory:
            best = min(moves, key=lambda m: (min(distance(m[1], a) for a in memory), m[1].z != start.z, -shelter(m[1]), m[0]))
            add(best, "advance toward the last seen enemy position; watch the approach")
            covered = [m for m in moves if shelter(m[1])]
            if covered:
                add(min(covered, key=lambda m: (min(distance(m[1], a) for a in memory), m[1].z != start.z, distance(start, m[1]), m[0])),
                    "take a covered spot and watch the approach to the last seen enemy position")
        else:
            visible = {tuple(c) for c in view.get("visible_cells", [])}
            cover_cells = grid.blocked | grid.opaque | grid.cover
            def frontier(p):
                return sum(grid.in_bounds((p.x+dx, p.y+dy)) and (p.x+dx, p.y+dy) not in visible
                           for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            def nearby_cover(p):
                return sum((p.x+dx, p.y+dy) in cover_cells
                           for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            # No ai-search planner on this base: advance to the perceived
            # frontier, or toward the map center if the local area is explored.
            center = Position(x=grid.width//2, y=grid.height//2)
            best = min(moves, key=lambda m: (-frontier(m[1]), m[1].z != start.z, -nearby_cover(m[1]), distance(m[1], center), distance(start, m[1]), m[0]))
            add(best, "advance near observed cover and look for enemies" if nearby_cover(best[1]) else
                "advance carefully and look for enemies")
    return result
