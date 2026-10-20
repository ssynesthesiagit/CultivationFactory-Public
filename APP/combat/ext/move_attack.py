"""Typed granted movement before a normal attack; shared by martial techniques.

Only actions carrying move_then_attack opt in. Native granted_movement owns
terrain, walls, footprints, fear, hazards, interruption and evented traversal.
The activation geometry query never changes the actor's position or weapon
reach. The subsequent attack remains a normal top-level typed attack.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from itertools import combinations

from . import effect, hook

_SCOPE = ContextVar("move_attack_traits", default=None)


def movement_row(action):
    return next((row for row in (action.parameters.get("typed") or {}).get("effects") or []
                 if row.get("type") == "move_then_attack"), None)


@contextmanager
def traits(engine, actor, row, through):
    token = _SCOPE.set((engine, actor.entity_id, row, frozenset(through)))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def active_traits(engine, actor):
    scope = _SCOPE.get()
    return scope if scope is not None and scope[0] is engine and scope[1] == actor.entity_id else None


@hook("pass_through")
def passage(engine, actor, occupant):
    scope = active_traits(engine, actor)
    if scope and occupant.entity_id in scope[3]:
        return "difficult"


@hook("difficult_exempt")
def terrain(engine, actor):
    scope = active_traits(engine, actor)
    if scope and scope[2].get("ignore_nonmagical_difficult"):
        from ..motion import TerrainExemption
        return TerrainExemption({(x, y) for x in range(engine.grid.width)
                                  for y in range(engine.grid.height)}, nonmagical_only=True)


def allowance(engine, actor, row):
    distance = row.get("distance_ft", "speed")
    return (int(engine._effective_speed(actor)) * int(row.get("speed_numerator", 1))
            // int(row.get("speed_denominator", 1))) if distance == "speed" else int(distance)


def routes(engine, actor, row, feet, used=()):
    """Every legal endpoint with its cheapest native route and passage grant.

    Search each allowed set of at most N hostile creatures independently.
    This retains routes that go around a second blocker instead of rejecting
    the unconstrained shortest path. Unknown occupants remain native contacts.
    Passage never authorizes an occupied stopping square.
    """
    from .. import granted_movement, motion
    from ..relations import relation, ENEMY
    from ..target_knowledge import actors_for, knowledge
    used = frozenset(used)
    hostiles = [other.entity_id for other in actors_for(engine, actor)
                if other.active and other.entity_id not in used
                and relation(engine, actor, other) == ENEMY
                and (known := knowledge(engine, actor, other)) is not None and known.mode == "DIRECT"]
    remaining = max(0, int(row.get("hostile_spaces", 0)) - len(used))
    out = {actor.position: (granted_movement.Route((actor.position,), "walk"), 0, used)}
    for count in range(min(remaining, len(hostiles)) + 1):
        for subset in combinations(hostiles, count):
            through = used | frozenset(subset)
            # A distinct projected actor also isolates native pure-query memo
            # keys across terrain/passage scopes in the same menu.
            projected = actor.model_copy()
            with traits(engine, projected, row, through), motion.terrain_for(engine, projected):
                found = granted_movement.routes(engine, projected, feet)
            for cell, (path, cost, mode) in found.items():
                if cell not in out or cost < out[cell][1]:
                    out[cell] = (granted_movement.Route(tuple(path), mode), cost, through)
    return out


def attack_action(engine, actor, action, weapon=None):
    """Use the delivering weapon's real current reach, not an activation radius."""
    if weapon is None:
        return action
    from ..ext.reach_bonus import current_reach
    return action.model_copy(update={"range_ft": current_reach(engine, actor, weapon),
                                     "reach_ft": weapon.reach_ft})


def attack_routes(engine, actor, target, action, row, weapon=None):
    from ..targeting import line_of_effect
    strike = attack_action(engine, actor, action, weapon)
    return {cell: route for cell, route in routes(engine, actor, row, allowance(engine, actor, row)).items()
            if engine._target_in_range(actor.model_copy(update={"position": cell}), target, strike)
            and line_of_effect(engine, actor.model_copy(update={"position": cell}), target=target)}


def legal_weapons(engine, actor, target, action, row):
    """Shared with Spear's existing attachment chooser; no duplicate binding."""
    from ..weapon_delivery import ready_weapons
    return {key: weapon for key, weapon in ready_weapons(engine, actor, tuple(row.get("weapon_words") or ())).items()
            if attack_routes(engine, actor, target, action, row, weapon)}


@hook("activation_target_geometry")
def activation_geometry(engine, actor, target, action):
    row = movement_row(action)
    if row is None:
        return None
    if row.get("weapon_words"):
        return bool(legal_weapons(engine, actor, target, action, row))
    return bool(attack_routes(engine, actor, target, action, row))


def choose_route(ctx, row, options, feet, stage):
    from . import needle
    if not options:
        return None
    labels = {needle.cell_id(cell): f"Move to {cell.x},{cell.y}"
              + (f", {cell.z * 5} feet high" if cell.z else "")
              + f" ({route[1]} feet of this ability's {feet}-foot movement)"
              for cell, route in options.items()}
    cells = {needle.cell_id(cell): cell for cell in options}
    # AI prefers the least movement that puts the chosen target in reach.
    # All squares stay available to human and automatic decision adapters.
    preferred = min(options, key=lambda cell: (options[cell][1], cell.z, cell.y, cell.x))
    chosen = needle.ask(ctx.engine, ctx.intent,
        needle.checkpoint_id(ctx.engine, "MOVE_ATTACK_" + stage, ctx.source), ctx.actor,
        "choice:needle.move_attack_" + stage, list(labels), labels=labels,
        preferred=[needle.cell_id(preferred)], allow_decline=False,
        name=ctx.action.display_name, target_id=ctx.target.entity_id if ctx.target else ctx.actor.entity_id,
        prompt=f"{ctx.action.display_name}: {ctx.actor.display_name}, choose where to "
               + (f"attack {ctx.target.display_name}" if stage == "attack" else "finish moving after the attack")
               + f". Move up to {feet} feet using this ability's own movement, not your Move action."
               + (" No opportunity attacks." if row.get("no_oa") else " Opportunity attacks apply normally."))
    return options[cells[chosen[0]]] if chosen else None


def traverse(ctx, row, route, feet):
    from ..movement_paths import resolve
    path, _cost, through = route
    with traits(ctx.engine, ctx.actor, row, through):
        return resolve(ctx.engine, ctx.actor, path, ctx.source, kind="granted", feet=feet,
                       intent=ctx.intent, provokes=not bool(row.get("no_oa")),
                       ignore_oa_from=(ctx.target.entity_id,) if row.get("no_oa_from_target") and ctx.target else ())


@effect("move_then_attack")
def move(ctx, row):
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    weapon = engine.action_catalog.get(ctx.typed.get("weapon_source_id", ""))
    ctx.action = attack_action(engine, actor, ctx.action, weapon)
    feet = allowance(engine, actor, row)
    options = attack_routes(engine, actor, target, ctx.action, row, weapon)
    route = choose_route(ctx, row, options, feet, "attack")
    if route is None:
        return
    start = len(engine.events)
    spent = traverse(ctx, row, route, feet)
    if row.get("attack_during"):
        from ..gate2_runtime_models import Position
        traversed = {tuple((p["x"], p["y"], p.get("z", 0)))
                     for event in engine.events[start:] if event.event_type == "MOVEMENT_COMMITTED"
                     and event.actor_id == actor.entity_id
                     for p in event.payload.get("path", [])}
        used = {who for who in route[2] if any((p.x, p.y, p.z) in traversed
                 for p in (Position(x=x, y=y, z=z) for x, y, z in engine._actor_volume(engine.state.actors[who])))}
        ctx.damage_cache["move_attack_remainder"] = (row, max(0, feet - spent), used)


@hook("technique_used")
def finish(ctx):
    pending = ctx.damage_cache.pop("move_attack_remainder", None)
    if pending is None or not ctx.actor.active or ctx.engine.state.terminal_result is not None:
        return
    row, feet, used = pending
    if feet < ctx.engine.grid.square_size_ft:
        return
    options = routes(ctx.engine, ctx.actor, row, feet, used)
    route = choose_route(ctx, row, options, feet, "finish")
    if route is not None:
        traverse(ctx, row, route, feet)
