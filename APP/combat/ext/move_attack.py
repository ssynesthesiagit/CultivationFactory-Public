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
                 if isinstance(row, dict) and row.get("type") == "move_then_attack"), None)


@contextmanager
def traits(engine, actor, row, through):
    from ..motion import TerrainExemption
    exemption = (TerrainExemption(frozenset((x, y) for x in range(engine.grid.width)
                                          for y in range(engine.grid.height)), nonmagical_only=True)
                 if row.get("ignore_nonmagical_difficult") else None)
    crossed = set()
    token = _SCOPE.set((engine, actor.entity_id, row, frozenset(through), exemption, crossed))
    try:
        yield crossed
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


@hook("pass_through_entered")
def crossed_hostile(engine, actor, occupant, intent):
    scope = active_traits(engine, actor)
    if scope and occupant.entity_id in scope[3]:
        scope[5].add(occupant.entity_id)


@hook("difficult_exempt")
def terrain(engine, actor):
    scope = active_traits(engine, actor)
    if scope:
        return scope[4]


def allowance(engine, actor, row):
    distance = row.get("distance_ft", "speed")
    return (int(engine._effective_speed(actor)) * int(row.get("speed_numerator", 1))
            // int(row.get("speed_denominator", 1))) if distance == "speed" else int(distance)


def routes(engine, actor, row, feet, used=()):
    """Share one immutable route search across weapon/target geometry queries."""
    from ..read_queries import memo
    used = frozenset(used)
    return dict(memo(engine, ("move_attack_routes", id(actor), id(row), feet, used),
                     lambda: (actor, row, search_routes(engine, actor, row, feet, used)))[2])


def search_routes(engine, actor, row, feet, used=()):
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


def attack_routes(engine, actor, target, action, row, weapon=None, destination=None):
    """Cheapest route cells from which this action can strike.

    With ``destination`` the strike is checked against a known square (a
    remembered target) instead of the creature's current hidden position.
    """
    from ..targeting import line_of_effect
    strike = attack_action(engine, actor, action, weapon)
    out = {}
    for cell, route in routes(engine, actor, row, allowance(engine, actor, row)).items():
        at = actor.model_copy(update={"position": cell})
        if destination is not None:
            from ..action_geometry import valid as origin_valid
            from ..attack_reach import maximum
            limit = maximum(engine, at, strike)
            legal = (origin_valid(engine, at, strike)
                     and (limit is None or engine._effect_distance_to_cell(at, destination) <= limit)
                     and line_of_effect(engine, at, destination=destination))
        else:
            legal = (engine._target_in_range(at, target, strike)
                     and line_of_effect(engine, at, target=target))
        if legal:
            out[cell] = route
    return out


def weapon_matches_attack(action, weapon):
    """A melee attack cannot borrow a ranged-only weapon profile's range."""
    attacks = [effect for effect in (action.parameters.get("typed") or {}).get("effects") or []
               if isinstance(effect, dict) and effect.get("type") == "attack"]
    melee = any("melee" in str(effect.get("attack_kind") or "") for effect in attacks)
    typed = weapon.parameters.get("typed") or {}
    return not melee or (typed.get("range_ft") is None
                         and (typed.get("weapon") or {}).get("attack_delivery") != "ranged")


def legal_weapons(engine, actor, target, action, row, destination=None):
    """Shared with Spear's existing attachment chooser; no duplicate binding."""
    from ..weapon_delivery import ready_weapons
    weapons = ready_weapons(engine, actor, tuple(row.get("weapon_words") or ()))
    legal = {}
    for key, weapon in weapons.items():
        if not weapon_matches_attack(action, weapon):
            continue
        # "No route for this weapon" is an empty route map, answered explicitly
        # here. Any exception from the geometry query is a real fault and must
        # surface instead of silently hiding the weapon (or the action).
        routes = attack_routes(engine, actor, target, action, row, weapon, destination)
        if routes:
            legal[key] = weapon
    return legal


@hook("activation_target_geometry")
def activation_geometry(engine, actor, target, action, *, destination=None):
    row = movement_row(action)
    if row is None:
        return None
    if row.get("weapon_words"):
        legal = legal_weapons(engine, actor, target, action, row, destination)
        return bool(legal)
    return bool(attack_routes(engine, actor, target, action, row, destination=destination))


def choose_route(ctx, row, options, feet, stage, target=None):
    from . import needle
    if not options:
        return None
    target = target if target is not None else ctx.target
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
        name=ctx.action.display_name, target_id=target.entity_id if target else ctx.actor.entity_id,
        prompt=f"{ctx.action.display_name}: {ctx.actor.display_name}, choose where to "
               + (f"attack {target.display_name}" if stage == "attack" else "finish moving after the attack")
               + f". Move up to {feet} feet using this ability's own movement, not your Move action."
               + (" No opportunity attacks." if row.get("no_oa") else
                  f" No opportunity attacks from {target.display_name}; other creatures can react normally."
                  if row.get("no_oa_from_target") and target else " Opportunity attacks apply normally."))
    return options[cells[chosen[0]]] if chosen else None


def traverse(ctx, row, route, feet, target=None):
    from ..movement_paths import resolve
    path, _cost, through = route
    target = target if target is not None else ctx.target
    with traits(ctx.engine, ctx.actor, row, through) as crossed:
        spent = resolve(ctx.engine, ctx.actor, path, ctx.source, kind="granted", feet=feet,
                        intent=ctx.intent, provokes=not bool(row.get("no_oa")),
                        ignore_oa_from=(target.entity_id,) if row.get("no_oa_from_target") and target else ())
        return spent, crossed


def missed_aim(ctx):
    """The aimed creature and its remembered square when the aim was missed (typed_executor drops it from
    ctx.targets and keeps its id in ctx.missed_target_ids). Uses only the known square, never a hidden position."""
    missed = getattr(ctx, "missed_target_ids", ())
    if ctx.targets or not missed:
        return None, None
    target = ctx.engine.state.actors.get(missed[0])
    square = ctx.damage_cache.get("_checkpoint_aim")
    if square is None:
        square = ctx.engine.state.observations.get(ctx.actor.team_id, {}).get(missed[0])
    return (target, square) if target is not None and square is not None else (None, None)


def choose_aim_weapon(ctx, row, destination):
    """The delivering weapon for an empty remembered square, chosen from the same legal set activation offered.

    The executor skips a recipient-bound weapon-binding effect when every aim was missed (nothing there to bind
    to), so an empty aim arrives without ``weapon_source_id``. Asking ``legal_weapons`` with the remembered square
    answers exactly the query ``activation_geometry`` answers, so execution reach can never be shorter than the
    reach that offered the action. Only legal weapons are listed; the player is asked when more than one remains.
    """
    from . import needle
    target, _ = missed_aim(ctx)
    legal = legal_weapons(ctx.engine, ctx.actor, target, ctx.action, row, destination)
    if not legal:
        ctx.rider("No approved weapon can reach the remembered square.")
        return None
    choices = list(legal)
    picked = choices if len(choices) == 1 else needle.ask(
        ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "MOVE_ATTACK_WEAPON", ctx.source), ctx.actor,
        "choice:needle.move_attack_weapon", choices,
        labels={key: weapon.display_name for key, weapon in legal.items()},
        prompt=f"{ctx.action.display_name}: {ctx.actor.display_name}, choose the weapon for the attack on the "
               f"remembered square at {destination.x},{destination.y}. Only weapons that can reach it are listed.",
        name=ctx.action.display_name, target_id=target.entity_id if target else ctx.actor.entity_id,
        preferred=choices[:1], allow_decline=False)
    return legal.get(picked[0]) if picked else None


@effect("move_then_attack")
def move(ctx, row):
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    destination = None
    if target is None:
        # Empty remembered square: the grant still moves the user toward it; the strike then hits nothing there.
        target, destination = missed_aim(ctx)
        if target is None:
            return
    weapon = engine.action_catalog.get(ctx.typed.get("weapon_source_id", ""))
    bindings = {}
    if weapon is None and destination is not None and row.get("weapon_words"):
        weapon = choose_aim_weapon(ctx, row, destination)
        if weapon is None:
            return
        bindings.update(weapon=weapon.parameters["typed"]["weapon"],
                        weapon_source_id=weapon.source_definition_id.split("#", 1)[0])
    ctx.action = attack_action(engine, actor, ctx.action, weapon)
    if weapon is not None and row.get("weapon_attack"):
        bindings["numbers"] = {**ctx.numbers, "attack_bonus": int(
            weapon.parameters["typed"]["numbers"].get("attack_bonus") or 0)}
    if bindings:
        # The single activation-local rebinding: never write into the action's shared
        # parameters["typed"] dict, or the bound weapon and bonus would leak into every
        # later menu build, seat and cold reload.
        ctx.typed = {**ctx.typed, **bindings}
    feet = allowance(engine, actor, row)
    options = attack_routes(engine, actor, target, ctx.action, row, weapon, destination)
    route = choose_route(ctx, row, options, feet, "attack", target)
    if route is None:
        return
    spent, crossed = traverse(ctx, row, route, feet, target)
    if row.get("attack_during"):
        ctx.damage_cache["move_attack_remainder"] = (row, max(0, feet - spent), crossed, target.entity_id)


@hook("technique_used")
def finish(ctx):
    pending = ctx.damage_cache.pop("move_attack_remainder", None)
    if pending is None or not ctx.actor.active or ctx.engine.state.terminal_result is not None:
        return
    row, feet, used, target_id = pending
    target = ctx.engine.state.actors.get(target_id)
    if feet < ctx.engine.grid.square_size_ft:
        return
    options = routes(ctx.engine, ctx.actor, row, feet, used)
    route = choose_route(ctx, row, options, feet, "finish", target)
    if route is not None:
        traverse(ctx, row, route, feet, target)
