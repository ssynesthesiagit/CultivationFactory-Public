"""River Passage's printed connected-water route, using existing table choice and teleport effects.

Water geometry comes from active Shape Current zones and explicitly named map
water terrain. Touching water cells form a connected system. The owner's Basins
are additional legal exits. Unknown/unrecorded water is never invented.
"""
from __future__ import annotations

import copy
import re
from dataclasses import replace
from typing import Any

from . import hook, effect

PASSAGE = "TAL_WATER_RIVER_PASSAGE"
SHAPE = "WATER_BASE_SHAPE_CURRENT"
WATER = re.compile(r"\b(water source|basin|current|river|canal|pond|cistern|rain curtain|water)\b", re.I)


def water_cells(engine: Any, owner: Any) -> tuple[set, set, set]:
    """Return water cells, owner's Basin cells, and explicitly significant source cells."""
    from ..zones import MAP_OWNER

    cells, basins, significant = set(), set(), set()
    for zone in engine.state.zones.values():
        if not zone.active:
            continue
        action = engine.action_catalog.get(zone.source_definition_id)
        typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
        profile = zone.trigger_profile or {}
        label = str(typed.get("option_label") or profile.get("name") or "")
        map_water = zone.owner_id == MAP_OWNER and WATER.search(" ".join(profile.get("terrain") or []))
        if typed.get("source") != SHAPE and not map_water:
            continue
        points = {(p.x, p.y) for p in zone.affected_cells}
        cells.update(points)
        if zone.owner_id == owner.entity_id and "basin" in label.lower():
            basins.update(points)
    for row in (getattr(engine, "battlefield_document", None) or {}).get("map_terrain") or []:
        if not WATER.search(str(row.get("terrain") or "")):
            continue
        points = {(int(p["x"]), int(p["y"])) if isinstance(p, dict) else (int(p[0]), int(p[1]))
                  for p in row.get("cells") or []}
        cells.update(points)
        if row.get("significant_water_source") is True:
            significant.update(points)
    return cells, basins, significant


def adjacent(point: Any, cells: set) -> bool:
    px, py = (point.x, point.y) if hasattr(point, "x") else point[:2]
    return any(max(abs(px - x), abs(py - y)) <= 1 for x, y in cells)


def beside_water(engine: Any, actor: Any, cells: set, position: Any = None) -> bool:
    """Adjacency uses the creature's full footprint, shared by origin and exit checks."""
    return any(adjacent(p, cells) for p in engine.grid.footprint_cells(position or actor.position, engine._footprint(actor)))


def connected_water(cells: set, seeds: set) -> set:
    """Return the recorded water components containing the supplied water cells."""
    reached = cells & seeds
    pending = list(reached)
    while pending:
        x, y = pending.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                point = x + dx, y + dy
                if point in cells and point not in reached:
                    reached.add(point)
                    pending.append(point)
    return reached


def connected_origin(engine: Any, actor: Any, cells: set) -> set:
    return connected_water(cells, {p for p in cells if beside_water(engine, actor, {p})})


def landings(engine: Any, owner: Any, passenger: Any, cl: int) -> list[Any]:
    from .teleport_steps import destinations

    cells, basins, significant = water_cells(engine, owner)
    origin = connected_origin(engine, owner, cells)
    if not origin:
        return []
    reach = 300 if cl >= 11 else 60
    # Both endpoints must connect to a significant source, not touch the
    # explicitly labelled source cells themselves.
    significant_route = origin & connected_water(cells, significant)
    long_route = cl >= 15 and bool(significant_route)
    result = []
    for p in destinations(engine, passenger, 5280 if long_route else reach):
        distance = engine.grid.distance_ft(owner.position, p)
        if not beside_water(engine, passenger, origin | basins, p):
            continue
        if distance > reach and not (long_route and beside_water(engine, passenger, significant_route, p)):
            continue
        result.append(p)
    return result


@hook("compile_action")
def passage_action(action: Any, info: dict[str, Any]) -> Any:
    typed = (action.parameters or {}).get("typed") or {}
    if PASSAGE not in info["owned_ids"] or (typed.get("modifier") or {}).get("id") != PASSAGE:
        return None
    typed = copy.deepcopy(typed)
    # River Passage is an alternative use of Return the Flow, not a request to
    # end or move its water path before travelling through it.
    typed["effects"] = [{"type": "water_river_passage", "source_modifier": PASSAGE}]
    typed["riders"] = []
    return action.model_copy(update={"target_kind": "ANY_CREATURE",
                                     "parameters": {**action.parameters, "typed": typed}})


@hook("candidate_allowed")
def passage_gate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if (typed.get("modifier") or {}).get("id") != PASSAGE:
        return None
    passenger = engine.state.actors.get(next(iter(candidate.target_ids), actor.entity_id))
    return (passenger is not None
            and bool(landings(engine, actor, passenger, int(typed.get("numbers", {}).get("cl") or 1))))


@effect("water_river_passage")
def passage(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id, cell_id, CHOICE
    from ..typed_executor import run_effects

    owner = ctx.actor
    passenger = ctx.target or owner
    # Willingness belongs to the passenger, regardless of team or saved
    # catalog target kind; eligibility alone never authorizes their movement.
    points = landings(ctx.engine, owner, passenger, int(ctx.numbers.get("cl") or 1))
    if not points:
        return
    if passenger.entity_id != owner.entity_id:
        consent = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "river_passage_consent", passenger.entity_id),
                      passenger, CHOICE + "river_passage_consent", ["accept"], minimum=0, allow_decline=True,
                      preferred=["accept"], target_id=passenger.entity_id, name="River Passage",
                      labels={"accept": f"Allow {owner.display_name} to carry {passenger.display_name} through water"},
                      prompt=f"River Passage: {owner.display_name} uses {ctx.action.display_name} to carry "
                             f"{passenger.display_name} instantly to an unoccupied space beside connected water. "
                             "Allow this teleport? It uses the caster's Bonus Action; no resource cost to either creature.")
        if not consent:
            return
    choices = {cell_id(p): p for p in points}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "river_passage", passenger.entity_id), owner,
                 CHOICE + "river_passage", list(choices), minimum=0, allow_decline=True,
                 labels={k: f"Carry {passenger.display_name} to water at ({p.x}, {p.y})" for k, p in choices.items()},
                 name="River Passage", prompt=f"River Passage: {ctx.action.display_name} carries {passenger.display_name} "
                 "through connected water to an unoccupied space beside the same water system or one of your Basins. "
                 "Uses this Bonus Action; no resource cost.")
    if picked:
        travel = replace(ctx, actor=passenger, targets=[passenger], target=passenger, destination=choices[picked[0]])
        from .teleport_steps import Destination, hop_key
        travel.hop_destination[hop_key(travel, 5280)] = Destination(travel.destination, True)
        run_effects(travel, [{"type": "teleport", "applies_to": "self", "distance_ft": 5280,
                              "duration": "instant"}])
