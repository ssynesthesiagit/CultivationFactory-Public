"""Move along a physical route to the aimed square, then strike around the new space (rider lane C7, 2026-09-30).

Shared by Body Refining "descent" features printed as "Move to the selected space without provoking ... This is not
teleportation", followed by an area around where the user lands (Adamantine Descent: "Each chosen creature within 20 feet
makes a Dexterity saving throw"). The action compiles as an area aimed at a square within its range (CELL); this effect runs
first:

    {"type": "move_to_aim", "distance_ft": 120, "radius_ft": 20}

The user moves along the shortest legal route (its own footprint, occupied squares, walls, difficult terrain, drag and
fear, shared with combat/ext/rider_movement.py) to the aimed square, or -- when a wall, total cover or an occupied square
stops it -- to the reachable square nearest to it. The movement provokes no Opportunity Attacks, spends none of the
user's Speed, and each square entered still triggers areas and hazards. It is never a teleport.

With ``radius_ft`` the effects that follow are re-aimed at the landing space: the creatures affected become the hostile
creatures within that many feet of the user (measured between spaces), and an object_damage row's area is centred there.
Nothing happens for an action without the row.
"""

from __future__ import annotations

from typing import Any

from . import effect


def _route(engine: Any, actor: Any, aim: Any, distance: int) -> list[Any] | None:
    from .rider_movement import routes

    paths = routes(engine, actor, distance)
    if not paths:
        return None
    exact = next((path for path in paths.values() if path[-1] == aim), None)
    if exact is not None:
        return exact
    return min(paths.values(), key=lambda path: (engine.grid.distance_ft(path[-1], aim), len(path), path[-1].y, path[-1].x))


@effect("move_to_aim")
def move_to_aim(ctx: Any, row: dict[str, Any]) -> None:
    from . import note
    from .rider_movement import step

    engine, actor = ctx.engine, ctx.actor
    aim = ctx.damage_cache.get("_checkpoint_aim")
    if aim is not None and aim != actor.position:
        path = _route(engine, actor, aim, int(row.get("distance_ft") or 0))
        if path and path[-1] != actor.position and engine.grid.distance_ft(path[-1], aim) < engine.grid.distance_ft(actor.position, aim):
            step(engine, actor, path, ctx.source)
        elif path is None:
            note(engine, ctx.source, actor, f"{ctx.action.display_name}: {actor.display_name} cannot move right now and stays put.")
    radius = row.get("radius_ft")
    if radius is None or not actor.active:
        return
    ctx.damage_cache["_checkpoint_aim"] = actor.position
    from ..targeting import line_of_effect
    found = [other for other in sorted(engine.state.actors.values(), key=lambda a: a.entity_id)
             if other.active and other.entity_id != actor.entity_id
             and (row.get('chosen_after_arrival') or other.team_id != actor.team_id)
             and engine._distance_actor_to_actor(actor, other) <= int(radius)
             and (not row.get('chosen_after_arrival') or line_of_effect(engine, actor, target=other))]
    if row.get('chosen_after_arrival'):
        ctx.typed.pop('_area_recipients_preselected', None)
    ctx.targets = found
    ctx.target = found[0] if len(found) == 1 else None
