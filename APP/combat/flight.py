"""Native flight capabilities and shared movement accounting.

Ability owners grant flat, recorded condition data or answer the pure `flight`
hook. The engine owns geometry, movement payment, opportunity attacks and falls.
Zero/default capabilities do not change ground movement or serialized saves.
"""
from dataclasses import dataclass
import heapq
from itertools import product, combinations

from . import ext
from .gate2_runtime_models import Position
from .space import point, volume
from .read_queries import pure


@dataclass(frozen=True)
class Profile:
    speed_ft: int = 0
    hover: bool = False
    suspended: bool = False
    can_ascend: bool = True


def profile(engine, actor):
    speed, hover = actor.fly_speed_ft, actor.hover
    suspended = disabled = cannot_ascend = zeroed = False
    rows = [condition.data for condition in actor.conditions.values()]
    if ext.has("flight"):
        rows += ext.run_strict("flight", engine, actor)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("flight providers must return a capability dictionary")
        amount = row.get("fly_speed_ft", 0)
        if type(amount) is not int or amount < 0:
            raise ValueError("Fly Speed must be nonnegative integer feet")
        speed = max(speed, amount)
        hover |= bool(row.get("flight_hover", 0))
        suspended |= bool(row.get("flight_suspended", 0))
        disabled |= bool(row.get("flight_disabled", 0))
        cannot_ascend |= bool(row.get("cannot_gain_altitude", 0))
        zeroed |= bool(row.get("fly_speed_zero", 0))
    percent = 100
    for row in rows:  # a weight that presses a Fly Speed down ("its Fly Speed is halved")
        value = row.get("fly_speed_percent", 100)
        if type(value) is not int or not 1 <= value <= 100:
            raise ValueError("fly_speed_percent must be an integer percentage of Fly Speed")
        percent = min(percent, value)
    speed = 0 if zeroed else speed * percent // 100
    if disabled:
        return Profile(0, False, False, not cannot_ascend)
    if engine._effective_speed(actor) <= 0:
        speed = 0
    return Profile(speed, hover, suspended, not cannot_ascend)


def dash_count(actor):
    # Existing native flags also cover a Dash taken before gaining flight.
    native = int(bool(actor.turn_flags.get("dash_used"))) + int(bool(actor.turn_flags.get("stomping_step_dash")))
    return max(native, int(actor.turn_flags.get("flight_native_dashes", 0))) + int(actor.turn_flags.get("flight_typed_dashes", 0))


def remaining(engine, actor, mode="walk"):
    overrun = int(actor.turn_flags.get("flight_movement_overrun_ft", 0))
    available = actor.movement_remaining_ft - overrun
    if mode == "fly":
        speed = profile(engine, actor).speed_ft
        if speed <= 0:
            return 0
        # The walking allowance was granted before later Speed changes. Never
        # subtract today's walking Speed from yesterday's granted allowance.
        basis = actor.speed_ft * (1 + dash_count(actor)) + int(actor.turn_flags.get("movement_allowance_adjustment_ft", 0))
        available += speed * (1 + dash_count(actor)) - basis
    return max(0, available)


def spend(actor, amount):
    """Spend one shared allowance; remember flight spent beyond walking capacity."""
    excess = max(0, amount - actor.movement_remaining_ft)
    actor.movement_remaining_ft = max(0, actor.movement_remaining_ft - amount)
    if excess:
        actor.turn_flags["flight_movement_overrun_ft"] = int(actor.turn_flags.get("flight_movement_overrun_ft", 0)) + excess


@dataclass(frozen=True)
class Budget:
    """What movement a creature has left this turn, over every mode it can use.

    ``available_ft`` is the most it can still travel: 0 when it is unsupported with no Fly
    Speed, or its Speed is 0, however much allowance remains. ``allowance_ft`` is what the shared
    allowance still allows it, ignoring where it is and what its Speed is, so it exceeds
    ``available_ft`` only while some other bar to moving is in force. ``granted_ft`` is what the
    turn granted it to begin with, so :attr:`spent` can tell movement that is gone because it was
    used from movement that was never there.
    """

    available_ft: int
    allowance_ft: int
    granted_ft: int

    @property
    def spent(self) -> bool:
        """Whether its movement is gone because it used it, not because it cannot move."""
        return self.available_ft <= 0 and self.allowance_ft <= 0 and self.granted_ft > 0


def budget(engine, actor) -> Budget:
    """Movement a creature can still spend this turn, over every mode it is in a position to use.

    Walking and flight draw on one allowance, so the two budgets are alternatives rather than a
    sum: :func:`reachable` keeps offering ground routes once flight is exhausted, and a creature
    whose Fly Speed is slower than its walking Speed spends its walking pool instead. A creature
    without ground or solid terrain support can only fly, and one whose Speed is 0 cannot move
    at all. Supported elevated creatures retain their walking pool. The single contract
    behind a printed "reduce its remaining movement" outcome: the gate that offers it, the
    reduction itself and the line the table logs afterwards all read this. Used by Chains'
    ``chains_counter_success``, combat/ext/chains_sphere.py.
    """
    allowance = max(remaining(engine, actor, "walk"), remaining(engine, actor, "fly"))
    from .falling import supported
    available = allowance if supported(engine, actor) else remaining(engine, actor, "fly")
    if engine._effective_speed(actor) <= 0:
        available = 0
    granted = actor.speed_ft * (1 + dash_count(actor)) + int(actor.turn_flags.get("movement_allowance_adjustment_ft", 0))
    return Budget(available, allowance, max(0, granted))


def restrict(engine, actor, feet):
    """Take ``feet`` off what the creature can actually still move this turn.

    Flight draws from the same allowance: :func:`remaining` reports the walking pool less the
    flight overrun, plus the difference between the flying and walking allowances. Changing
    ``movement_remaining_ft`` alone therefore cannot reach the feet a flyer has left beyond its
    walking Speed, so the remainder is taken from the overrun instead. The request is priced
    against :func:`budget`, so a flyer slower than it walks can still lose walking feet even once
    its flight is exhausted.

    Returns the feet actually removed, which is fewer than ``feet`` once the creature's budget is
    smaller than the request; zero when it cannot move at all. Used by printed "reduce its
    remaining movement" outcomes that a flyer can be subject to (Chains'
    ``chains_counter_success``, combat/ext/chains_sphere.py).
    """
    wanted = min(int(feet or 0), budget(engine, actor).available_ft)
    if wanted <= 0:
        return 0
    overrun = int(actor.turn_flags.get("flight_movement_overrun_ft", 0))
    from_walking = min(wanted, max(0, actor.movement_remaining_ft - overrun))
    actor.movement_remaining_ft -= from_walking
    remainder = wanted - from_walking
    if remainder:
        # What was left was only in the flying allowance. A creature that cannot fly never leaves
        # a remainder, so this cannot add flight feet to something that has none.
        actor.turn_flags["flight_movement_overrun_ft"] = overrun + remainder
    return wanted


def begin_turn(engine, actor):
    """Capture nonstandard walking allowance in the recorded turn-start state."""
    adjustment = actor.movement_remaining_ft - actor.speed_ft
    if adjustment:
        actor.turn_flags["movement_allowance_adjustment_ft"] = adjustment


def dash(engine, actor, *, typed=False):
    adjustment = engine._effective_speed(actor) - actor.speed_ft
    if adjustment:
        actor.turn_flags["movement_allowance_adjustment_ft"] = int(actor.turn_flags.get("movement_allowance_adjustment_ft", 0)) + adjustment
    # Typed Dash has no legacy flag, including when flight is granted later.
    if typed or profile(engine, actor).speed_ft:
        key = "flight_typed_dashes" if typed else "flight_native_dashes"
        actor.turn_flags[key] = int(actor.turn_flags.get(key, 0)) + 1


def step_cost(engine, actor, previous, destination, mode="walk", difficult=(), *, passage_difficult=None):
    """Price the actual segment, including a high jump's walking approach.

    Jump routes contain level walking followed by vertical ascent. Both route
    quotes and native execution use this function; the route label alone must
    not exempt the approach from walking surcharges.

    An area-scoped nonmagical-Difficult-Terrain exemption is re-read at the
    mover's current square for this one step (combat/motion.py repriced), so a
    servant that leaves its area pays and one that enters it does not.
    """
    from .motion import repriced

    with repriced(engine, actor):
        return _step_cost(engine, actor, previous, destination, mode, difficult, passage_difficult)


def _step_cost(engine, actor, previous, destination, mode, difficult, passage_difficult):
    from .movement_costs import surcharge
    from .posture import walking_extra
    if mode == "jump" and previous.z == destination.z:
        mode = "walk"
    if mode == "fly" or previous.z or destination.z:
        from .spatial_areas import difficult_at
        from .creature_passage import volume_geometry
        if passage_difficult is None:
            passage_difficult = volume_geometry(engine, actor)[1]
        multiplier = 2 if difficult_at(engine, actor, destination) or set(engine._actor_volume(actor, destination)) & passage_difficult else 1
    else:
        multiplier = engine.grid.movement_step_multiplier(
            previous, destination, footprint=engine._footprint(actor), difficult_cells=difficult)
    if mode == 'walk':
        multiplier += walking_extra(engine, actor)
    return (engine.grid.square_size_ft * multiplier + surcharge(engine, actor, mode)) * engine._drag_multiplier(actor)


def step_allowed(engine, actor, previous, destination, *, mode="walk", observed=False):
    if mode == "fly":
        capability = profile(engine, actor)
        if not capability.speed_ft or (destination.z > previous.z and not capability.can_ascend):
            return False
    elif mode == "jump":
        if not profile(engine, actor).can_ascend:
            return False
    elif destination.z != previous.z:
        return False  # jumps and forced vertical movement use their explicit entry points
    elif previous.z:
        from .falling import supported
        if not supported(engine, actor, previous):
            return False
    if mode == "fly" or previous.z or destination.z or engine.grid.finite_heights:
        from .creature_passage import volume_geometry
        return engine.grid.volume_step_legal(previous, destination, footprint=engine._footprint(actor),
                                             occupied_cells=volume_geometry(engine, actor, observed=observed)[0])
    from .creature_passage import geometry
    occupied, _, _, _ = geometry(engine, actor, observed=observed)
    return engine.grid.step_legal(previous, destination, footprint=engine._footprint(actor),
                                 occupied_cells=occupied)


@pure
def reachable(engine, actor, *, grant_ft=None, path_selector=None):
    """Existing move candidates gain height; no separate altitude action or choice.

    One read-only route search shares terrain queries across its edges. The
    call-local frame is discarded on return/error; execution never inherits it.
    A path selector must obey the existing read-only query contract.
    """
    capability = profile(engine, actor)
    mode = "fly" if capability.speed_ft else "walk"
    budget = remaining(engine, actor, mode) if grant_ft is None else grant_ft
    walking = {}
    walk_budget = remaining(engine, actor, "walk") if grant_ft is None else grant_ft
    from .voluntary_movement import edge_predicate
    restriction = edge_predicate(engine, actor)
    if not actor.position.z and walk_budget:
        from .posture import walking_extra
        from .creature_passage import geometry
        from .movement_costs import surcharge
        occupied, end_blocked, extra_difficult, _ = geometry(engine, actor, observed=True)
        walking = {destination: (path, cost * engine._drag_multiplier(actor), "walk") for destination, (path, cost) in engine.grid.reachable(
            actor.position, movement_ft=walk_budget // engine._drag_multiplier(actor),
            extra_step_cost_ft=surcharge(engine, actor),
            occupied_cells=occupied, end_blocked_cells=end_blocked,
            difficult_cells=engine._hostile_difficult_cells(actor) | extra_difficult,
            footprint=engine._footprint(actor),
            extra_step_multiplier=walking_extra(engine, actor),
            path_selector=path_selector,
            **({'edge_allowed': restriction} if restriction is not None else {})).items()}
    if not budget:
        return walking
    if mode == "walk" and not actor.position.z:
        return walking
    start = point(actor.position)
    from .creature_passage import volume_geometry
    occupied, passage_difficult = volume_geometry(engine, actor, observed=True)
    endpoint_occupied = engine._occupied_volumes_except(actor.entity_id, observed=True)
    footprint = engine._footprint(actor)
    ceiling = start[2] + budget // engine.grid.square_size_ft if mode == "fly" and capability.can_ascend else start[2]
    legal = {}
    def fits(cell):
        if cell not in legal:
            legal[cell] = (0 <= cell[2] <= ceiling and engine.grid.volume_legal(cell, footprint=footprint, occupied_cells=occupied))
        return legal[cell]
    from .voluntary_movement import fear_sources, blocking_source
    fears = fear_sources(engine, actor)
    costs, parents, predecessors = {start: 0}, {}, {}
    queue = [(0, start)]
    neighbors = tuple(offset for offset in product((-1, 0, 1), repeat=3)
                      if offset != (0, 0, 0) and (mode == "fly" or offset[2] == 0))
    difficult = engine._hostile_difficult_cells(actor)
    from .falling import supported
    while queue:
        spent, cell = heapq.heappop(queue)
        if spent != costs[cell] or spent >= budget:
            continue
        if mode == "walk" and not supported(engine, actor, Position(x=cell[0], y=cell[1], z=cell[2])):
            continue
        for delta in neighbors:
            if delta[2] > 0 and not capability.can_ascend:
                continue
            nxt = tuple(a+b for a, b in zip(cell, delta))
            if not fits(nxt):
                continue
            cost = step_cost(engine, actor, Position(x=cell[0], y=cell[1], z=cell[2]),
                             Position(x=nxt[0], y=nxt[1], z=nxt[2]), mode, difficult,
                             passage_difficult=passage_difficult)
            if spent + cost > budget:
                continue
            if costs.get(nxt, budget+1) < spent+cost or (path_selector is None and costs.get(nxt) == spent+cost) or not fits(nxt):
                continue
            axes = [i for i in range(3) if delta[i]]
            if any(not fits(tuple(cell[i]+delta[i] if i in selected else cell[i] for i in range(3)))
                   for size in range(1, len(axes)) for selected in combinations(axes, size)):
                continue
            if fears and blocking_source(engine, actor, Position(x=cell[0], y=cell[1], z=cell[2]),
                                         Position(x=nxt[0], y=nxt[1], z=nxt[2]), sources=fears):
                continue
            if costs.get(nxt) == spent + cost:
                predecessors[nxt].add(cell)
            else:
                costs[nxt], parents[nxt], predecessors[nxt] = spent+cost, cell, {cell}
                heapq.heappush(queue, (spent+cost, nxt))
    from types import MappingProxyType
    selected = path_selector(start, MappingProxyType({cell: frozenset(rows) for cell, rows in predecessors.items()}),
                             MappingProxyType(costs), MappingProxyType(parents)) if path_selector else {}
    result = {}
    for cell in sorted(parents):
        if not engine.grid.volume_legal(cell, footprint=footprint, occupied_cells=endpoint_occupied):
            continue
        chain = [cell]
        while chain[-1] != start:
            chain.append(parents[chain[-1]])
        if cell in selected:
            chosen = selected[cell]
            if chosen[0] != start or chosen[-1] != cell or any(a not in predecessors.get(b, ()) for a, b in zip(chosen, chosen[1:])):
                raise ValueError('Route selection must use an equal-cost native path')
            chain = list(reversed(chosen))
        path = tuple(Position(x=x, y=y, z=z) for x, y, z in reversed(chain))
        result[path[-1]] = (path, costs[cell], mode)
    for destination, route in walking.items():
        if destination not in result or route[1] <= result[destination][1]:
            result[destination] = route
    return result


def _running_start(engine, actor, path):
    """At least ten feet in one direction immediately before leaving support."""
    ground = list(path)
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED":
            break
        if event.actor_id != actor.entity_id:
            continue
        if event.event_type == "MOVEMENT_COMMITTED":
            row = event.payload
            if not row.get("forced") and row.get("movement_mode", "walk") == "walk":
                prior = [Position.model_validate(p) for p in row.get("path", ())]
                if prior and ground and prior[-1] == ground[0]:
                    ground = prior[:-1] + ground
            break
    if len(ground) < 3:
        return False
    a, b, c = ground[-3:]
    return (a.z == b.z == c.z and (b.x-a.x, b.y-a.y) == (c.x-b.x, c.y-b.y)
            and engine.grid.distance_cells(a, b) == engine.grid.distance_cells(b, c) == 1)


def jump_score(engine, actor):
    """The ability score that measures this creature's jump, and any flat bonus to its jump height in feet.

    ``jump_ability(engine, actor)`` is the pure `jump_ability` hook: "STR" or "DEX", the score a plug-in
    substitutes for jump height and distance (Mighty Conditioning's "use Dexterity instead of Strength").
    ``jump_bonus_ft(engine, actor)`` is the pure `jump_bonus_ft` hook: flat feet added to the jump height the
    score earns (Polearm Vaulter's Bonus Action increase). Both default to no answer and no bonus, so a creature
    with neither jumps exactly as it did before. A jump bonus also supplies the ascent the minimum score gate
    otherwise asks for, because the printed increase does not depend on Strength.
    """
    if not ext.has("jump_ability") and not ext.has("jump_bonus_ft"):
        return actor.strength_score, 0
    ability = "STR"
    for answer in ext.run_strict("jump_ability", engine, actor):
        if answer is not None:
            ability = str(answer).upper()
    score = actor.dexterity_score if ability == "DEX" else actor.strength_score
    bonus = max(0, max((int(value) for value in ext.run_strict("jump_bonus_ft", engine, actor)
                        if isinstance(value, int)), default=0))
    return int(score), bonus


def jump_steps(engine, actor, ground_path):
    from .falling import supported
    if not ground_path or not supported(engine, actor, ground_path[-1]) or not profile(engine, actor).can_ascend:
        return 0
    score, bonus = jump_score(engine, actor)
    height = max(0, 3 + (score - 10) // 2) + bonus
    return height // (5 if _running_start(engine, actor, ground_path) else 10)


def valid_jump(engine, actor, path):
    first = next((i for i in range(1, len(path)) if path[i].z != path[i-1].z), None)
    if first is None:
        return False
    ground, air = path[:first], path[first:]
    start = ground[-1]
    return (len(air) <= jump_steps(engine, actor, ground)
            and all(p.x == start.x and p.y == start.y and p.z == start.z+i
                    for i, p in enumerate(air, 1)))


def jumps(engine, actor, walking):
    """Grid high jumps: spend walking distance, rise whole 5-ft steps, then fall.

    Sub-square jumps have no new grid destination. Running starts can be in this
    route or the immediately preceding recorded movement in the same turn. The minimum
    score gate is 14 for the score that measures this jump, which is the substituted one
    when a plug-in substitutes it; a flat jump bonus answers the gate instead, because
    the printed increase it buys does not depend on Strength. jump_steps still decides
    how many whole steps that score and bonus actually earn, so a bonus too small to reach
    one step produces no destination either way.
    """
    score, bonus = jump_score(engine, actor)
    if (score < 14 and not bonus) or not profile(engine, actor).can_ascend:
        return {}
    budget = remaining(engine, actor)
    result = {}
    routes = [((actor.position,), 0)] + [(route[0], route[1] * engine._drag_multiplier(actor) if len(route) == 2 else route[1]) for route in walking.values()
                                       if len(route) == 2 or route[2] == "walk"]
    for ground, cost in routes:
        path = list(ground)
        for _ in range(jump_steps(engine, actor, ground)):
            nxt = path[-1].model_copy(update={"z": path[-1].z+1})
            cost += step_cost(engine, actor, path[-1], nxt, "jump")
            if cost > budget or not step_allowed(engine, actor, path[-1], nxt, mode="jump", observed=True):
                break
            path.append(nxt)
            if nxt not in result or result[nxt][1] > cost:
                result[nxt] = (tuple(path), cost, "jump")
    return result
