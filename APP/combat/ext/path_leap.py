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

from . import effect,hook


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
        if row.get('cross_open_air'):
            from .. import flight
            from ..granted_movement import resolve_path
            path=ctx.damage_cache.get('_checkpoint_path') or ()
            with air_scope(engine,actor):
                prefix=[actor.position]
                if path and path[0]==actor.position:
                    for nxt in path[1:]:
                        if not flight.step_allowed(engine,actor,prefix[-1],nxt,mode='fly',observed=True):break
                        prefix.append(nxt)
                if len(prefix)>1:
                    resolve_path(engine,actor,prefix,ctx.source,feet=int(row['distance_ft']),intent=ctx.intent,provokes=False,mode='fly')
            from ..paid_relocation import preserve_pending
            preserve_pending(engine,'_path_leap_pending_fall')
            engine.__dict__.setdefault('_path_leap_pending_fall',set()).add(actor.entity_id)
            path=prefix
        else:
            path = _route(engine, actor, aim, int(row.get("distance_ft") or 0))
            if path and path[-1] != actor.position and engine.grid.distance_ft(path[-1], aim) < engine.grid.distance_ft(actor.position, aim):
                step(engine, actor, path, ctx.source)
        if path is None:
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


from contextlib import contextmanager
from contextvars import ContextVar
_AIR=ContextVar('physical_path_leap',default=None)


@contextmanager
def air_scope(engine,actor):
    """Physical source permission during one query/route; never Fly Speed."""
    token=_AIR.set((engine,actor.entity_id))
    try:yield
    finally:_AIR.reset(token)


@hook('movement_step_capability')
def physical_air_step(engine,actor,previous,destination,mode):
    if mode=='fly' and _AIR.get()==(engine,actor.entity_id):return True


@hook('flight')
def physical_air_gravity(engine,actor):
    # The body is in transit. Its arrival effects resolve before unsupported
    # descent; there is no standing surface, Fly Speed or lasting Hover grant.
    if _AIR.get()==(engine,actor.entity_id) or actor.entity_id in engine.__dict__.get('_path_leap_pending_fall',set()):return {'flight_suspended':1}


def air_row(action):
    return next((r for r in (action.parameters.get('typed') or {}).get('effects',[])
                 if r.get('type')=='move_to_aim' and r.get('cross_open_air') is True),None)


def air_paths(engine,actor,feet):
    if not actor.active or engine._effective_speed(actor)<=0:return {}
    from ..read_queries import invariant_memo
    from .. import flight
    def compute():
        with air_scope(engine,actor):return flight.reachable(engine,actor,grant_ft=feet,mode='fly')
    return invariant_memo(engine,('physical_air_paths',actor.entity_id,actor.position.x,actor.position.y,actor.position.z,feet),compute)


@hook('cell_aim_levels')
def physical_air_levels(engine,actor,action,levels):
    row=air_row(action)
    if row:return range(0,actor.position.z+int(row['distance_ft'])//engine.grid.square_size_ft+1)


@hook('action_candidate_route')
def physical_air_candidate_route(engine,actor,action,destination):
    row=air_row(action)
    if row:
        route=air_paths(engine,actor,int(row['distance_ft'])).get(destination)
        return tuple(route[0]) if route else ()


@hook('candidate_allowed')
def physical_air_destination(engine,actor,candidate,action):
    if action is not None and air_row(action) is not None and candidate.destination is not None:
        return bool(candidate.canonical_path and candidate.canonical_path[-1]==candidate.destination)


@hook('resolution_final',priority=200)
def physical_air_arrival_fall(engine,actor,action,candidate,intent):
    if engine.__dict__.pop('_path_leap_pending_fall',set()):
        from ..falling import settle
        settle(engine,action.source_definition_id,intent)
