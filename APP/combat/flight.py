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


@pure
def profile(engine, actor, *, excluding_conditions=()):
    """Query flight while optionally excluding selected recorded condition data.

    Lifecycle consumers can check for independent support before removing their
    own receipt, since a removal event immediately settles unsupported falls.
    One call shares pure zone/perception answers between its condition and
    provider checks. Standalone frames end on return; nested callers retain
    their existing pure scope.

    Within one read-only query frame the capability of one unchanged projected
    creature at one square is shared: flight promotion asks it for every route
    endpoint and waypoint. Held objects keep their identity alive; outside a
    frame, or after a recorded change, every call computes afresh. This query
    does not mutate the actor. Native flight, provider answers and
    effective-speed restrictions remain authoritative.
    """
    from .read_queries import shared_query
    from .space import point

    excluded = frozenset(excluding_conditions)
    # The grant rows come from this creature's recorded conditions and the
    # plug-in providers; they do not depend on its square, while the effective
    # Speed restriction below does. Share the rows for one unchanged creature.
    capability = shared_query(engine, ('flight_capability', id(actor), point(actor.position), excluded),
                              lambda: _capability(engine, actor, excluded), refs=(actor,))
    speed, hover, suspended, disabled, cannot_ascend = capability
    if disabled:
        return Profile(0, False, False, not cannot_ascend)
    if speed and engine._effective_speed(actor) <= 0:
        speed = 0
    return Profile(speed, hover, suspended, not cannot_ascend)


def _capability(engine, actor, excluded):
    speed, hover = actor.fly_speed_ft, actor.hover
    bonus = 0
    suspended = disabled = cannot_ascend = zeroed = False
# Independent support: a named condition the caller is about to remove must not
    # count as support for itself, and a plug-in may veto a grant per condition
    # (drum_body). Both filters apply; each is inert when it has nothing to filter.
    rows = [condition.data for iid, condition in actor.conditions.items()
            if iid not in excluded
            and False not in ext.run_strict('flight_grant_allowed', engine, actor, condition)]
    if ext.has("flight"):
        rows += [row for row in ext.run_strict("flight", engine, actor)
                 if False not in ext.run_strict('flight_provider_allowed', engine, actor, row)]
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("flight providers must return a capability dictionary")
        amount = row.get("fly_speed_ft", 0)
        if type(amount) is not int or amount < 0:
            raise ValueError("Fly Speed must be nonnegative integer feet")
        added = row.get("fly_speed_bonus_ft", 0)
        if type(added) is not int or added < 0:
            raise ValueError("Fly Speed bonus must be nonnegative integer feet")
        bonus += added
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
    # Independent flat penalties stack; paired tracking conditions sharing a
    # reduction key describe one effect and contribute only its largest penalty.
    reductions = {}
    for index, row in enumerate(rows):
        amount = row.get("fly_speed_reduction_ft", 0)
        if type(amount) is not int or amount < 0:
            raise ValueError("fly_speed_reduction_ft must be nonnegative integer feet")
        key = ("named", row["fly_speed_reduction_key"]) if row.get("fly_speed_reduction_key") else ("row", index)
        reductions[key] = max(reductions.get(key, 0), amount)
    # Bonuses modify an existing Speed before percentage restrictions. They
    # do not create flight if the underlying capability disappears.
    speed = 0 if zeroed or speed <= 0 else max(0, (speed + bonus) * percent // 100 - sum(reductions.values()))
    return speed, hover, suspended, disabled, cannot_ascend


def dash_count(actor):
    # Existing native flags also cover a Dash taken before gaining flight.
    native = int(bool(actor.turn_flags.get("dash_used"))) + int(bool(actor.turn_flags.get("stomping_step_dash")))
    return max(native, int(actor.turn_flags.get("flight_native_dashes", 0))) + int(actor.turn_flags.get("flight_typed_dashes", 0))


def remaining(engine, actor, mode="walk"):
    overrun = int(actor.turn_flags.get("flight_movement_overrun_ft", 0))
    available = actor.movement_remaining_ft - overrun
    if mode in {"fly", "climb"}:
        from .roof_movement import profile as climbing_profile
        speed = profile(engine, actor).speed_ft if mode == "fly" else climbing_profile(engine, actor).speed_ft
        if speed <= 0:
            return 0 if mode == "fly" else max(0, available)
        # The walking allowance was granted before later Speed changes. Never
        # subtract today's walking Speed from yesterday's granted allowance.
        basis = actor.speed_ft * (1 + dash_count(actor)) + int(actor.turn_flags.get("movement_allowance_adjustment_ft", 0))
        available += speed * (1 + dash_count(actor)) - basis
    from .movement_budget import limit
    return max(0, limit(engine, actor, available)) + mode_credit(engine, actor, mode)


def credit_rows(engine, actor, mode):
    """Optional condition-scoped movement credit; normal movement has no credit.

    Integer feet, a native mode, and optional horizontal/vertical axis are the
    whole persisted contract. movement_credit_allowed may veto one receipt
    when an owned equipment or capability prerequisite is no longer true.
    """
    rows = []
    for condition in actor.conditions.values():
        data = condition.data or {}
        if data.get('movement_credit_mode') != mode:
            continue
        feet = data.get('movement_credit_ft', 0)
        if type(feet) is not int or feet < 0 or data.get('movement_credit_axis') not in (None, 'horizontal', 'vertical'):
            raise ValueError('Movement credit requires integer feet and a valid axis')
        if False not in ext.run_strict('movement_credit_allowed', engine, actor, condition):
            rows.append(condition)
    return rows


def mode_credit(engine, actor, mode, previous=None, destination=None):
    """Pure remaining credit, optionally limited to the actual step's axis."""
    return sum(row.data['movement_credit_ft'] for row in credit_rows(engine, actor, mode)
               if previous is None or destination is None or
               (row.data.get('movement_credit_axis') != 'vertical' or previous.z != destination.z) and
               (row.data.get('movement_credit_axis') != 'horizontal' or previous.z == destination.z))


def spend_mode(engine, actor, amount, mode, previous, destination):
    """Spend applicable credits before ordinary feet; journal each retained receipt."""
    paid = amount
    for row in credit_rows(engine, actor, mode):
        axis = row.data.get('movement_credit_axis')
        if (axis == 'vertical' and previous.z == destination.z) or (axis == 'horizontal' and previous.z != destination.z):
            continue
        credit = min(paid, row.data['movement_credit_ft'])
        if credit:
            engine._update_condition_data(actor, row, {**row.data, 'movement_credit_ft': row.data['movement_credit_ft'] - credit},
                                          row.source_definition_id)
            paid -= credit
    spend(actor, paid)
    return paid


def path_credit(engine, actor, path, mode):
    """Pure credit quote: an axis-specific grant cannot buy a ground approach."""
    rows = [[c.data.get('movement_credit_axis'), c.data['movement_credit_ft']] for c in credit_rows(engine, actor, mode)]
    covered = 0
    for a, b in zip(path, path[1:]):
        left = step_cost(engine, actor, a, b, mode)
        for row in rows:
            if (row[0] == 'vertical' and a.z == b.z) or (row[0] == 'horizontal' and a.z != b.z):
                continue
            credit = min(left, row[1])
            row[1] -= credit
            left -= credit
            covered += credit
    return covered


def path_allowance(engine, actor, path, mode):
    """Quote the ordinary allowance plus credits usable by this exact path.

    Planning, admission and execution share this pure quote. Axis-restricted
    receipts cannot fund a different axis, nor pay more than their matching
    edges cost. Actual steps still spend and journal the same credit rows.
    """
    return remaining(engine, actor, mode) - mode_credit(engine, actor, mode) + path_credit(engine, actor, path, mode)


def spend(actor, amount):
    """Spend one shared allowance; remember flight spent beyond walking capacity."""
    excess = max(0, amount - actor.movement_remaining_ft)
    actor.movement_remaining_ft = max(0, actor.movement_remaining_ft - amount)
    if excess:
        actor.turn_flags["flight_movement_overrun_ft"] = int(actor.turn_flags.get("flight_movement_overrun_ft", 0)) + excess


@dataclass(frozen=True)
class Budget:
    """What movement a creature has left this turn, over every mode it can use.

    ``available_ft`` is the most it can still travel: 0 when it lacks support, a climbing hold
    and Fly Speed, or its Speed is 0, however much allowance remains. ``allowance_ft`` is what the shared
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
    without ground or solid terrain support can fly or use an eligible recorded climbing hold,
    including a virtual wall without roofs. One whose Speed is 0 cannot move at all.
    Supported elevated creatures retain their walking pool. The single contract
    behind a printed "reduce its remaining movement" outcome: the gate that offers it, the
    reduction itself and the line the table logs afterwards all read this. Used by Chains'
    ``chains_counter_success``, combat/ext/chains_sphere.py.
    """
    walking, flying = remaining(engine, actor, "walk"), remaining(engine, actor, "fly")
    allowance = max(walking, flying)
    from .falling import supported
    supported_here = supported(engine, actor)
    available = allowance if supported_here else flying
    from .roof_movement import can_hold, eligible, faces
    if engine.grid.roof_surfaces or eligible(engine, actor):
        climbing = remaining(engine, actor, 'climb')
        allowance = max(allowance, climbing)
        if can_hold(engine, actor) or (supported_here and eligible(engine, actor) and faces(engine, actor, actor.position)):
            available = max(available, climbing)
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
        # What was left was only in a flying or climbing allowance beyond walking.
        # The shared overrun removes those feet without granting any new movement mode.
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
    from .movement_costs import surcharge, elevation_surcharge
    from .posture import walking_extra
    if (mode == "jump" and previous.z == destination.z) or mode == "jump_down":
        mode = "walk"
    elif mode == 'climb':
        from .roof_movement import step_mode
        mode = step_mode(engine, actor, previous, destination)
    # Material routes may connect through dry supported surfaces at any height.
    # Those steps still walk (or crawl), without the medium's posture exemption.
    from .terrain_materials import profile as material_profile, supported as material_support
    capability = material_profile(engine, actor, mode)
    if (capability is not None
            and not material_support(engine, actor, destination, capability)):
        mode = 'walk'
    if mode == "fly" or previous.z or destination.z:
        from .spatial_areas import difficult_at
        from .creature_passage import volume_geometry
        if passage_difficult is None:
            passage_difficult = volume_geometry(engine, actor)[1]
        multiplier = 2 if difficult_at(engine, actor, destination) or set(engine._actor_volume(actor, destination)) & passage_difficult else 1
    else:
        multiplier = engine.grid.movement_step_multiplier(
            previous, destination, footprint=engine._footprint(actor), difficult_cells=difficult)
    if mode == 'climb':
        from .roof_movement import extra_multiplier
        multiplier += extra_multiplier(engine, actor, previous, destination)
    elif mode == 'walk':
        multiplier += walking_extra(engine, actor)
    from .terrain_materials import difficult as material_difficult
    if material_difficult(engine, actor, previous, destination, mode):
        multiplier = max(2, multiplier)
    return (engine.grid.square_size_ft * multiplier + surcharge(engine, actor, mode)
            + elevation_surcharge(engine, actor, previous, destination, mode)) * engine._drag_multiplier(actor)


def step_allowed(engine, actor, previous, destination, *, mode="walk", observed=False):
    capabilities = ext.run_strict("movement_step_capability", engine, actor, previous, destination, mode)
    if any(type(value) is not bool for value in capabilities):
        raise ValueError("movement_step_capability must return bool or None")
    if False in capabilities:
        return False
    from .terrain_materials import profile as material_profile, step_allowed as material_step
    if material_profile(engine, actor, mode) is not None:
        return material_step(engine, actor, previous, destination, mode, observed=observed)
    if mode == "climb":
        from .roof_movement import step_allowed as climb_step
        return climb_step(engine, actor, previous, destination, observed=observed)
    if mode == "jump_down":
        mode = "walk"
    if True in capabilities:
        pass  # Explicit scoped capability; ordinary volume geometry still applies.
    elif mode == "fly":
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
def reachable(engine, actor, *, grant_ft=None, path_selector=None, mode=None):
    """Existing move candidates gain height; no separate altitude action or choice.

    One read-only route search shares terrain queries across its edges. The
    call-local frame is discarded on return/error; execution never inherits it.
    A path selector must obey the existing read-only query contract.

    ``mode`` (optional) restricts the search to one movement mode: ``"walk"``
    returns only walking routes (even for a creature with Fly Speed), ``"fly"``
    only flying routes. None keeps the default merged every-mode answer. A rule
    that prices a movement against the mode that actually governs it (Set Up's
    endpoint exception, combat/ext/retribution_second_pass.py) passes that mode
    so a rule for a walking move never counts a route reachable only by flying.
    Elevated walking continues through the existing supported spatial search;
    the ground-grid answer applies only to ground starts.
    """
    capability = profile(engine, actor)
    requested = mode
    if mode is None:
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
    if actor.position.z and engine.grid.roof_surfaces and mode == "fly":
        walking.update(_roof_walking(engine, actor, walk_budget, path_selector=path_selector))
    if requested is not None and mode == "walk" and not actor.position.z:
        return walking
    if not budget:
        return walking if requested is None else {}
        return walking
    if not budget:
        return walking if requested is None else {}
    if mode == "walk" and not actor.position.z:
        return walking
    start = point(actor.position)
    from .creature_passage import volume_geometry
    occupied, passage_difficult = volume_geometry(engine, actor, observed=True)
    from .creature_passage import endpoint_volumes
    endpoint_occupied = endpoint_volumes(engine, actor, observed=True)
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
    # Geometry is constant throughout this pure search. Reuse cell Positions
    # and diagonal corner offsets rather than validating/building them on
    # every incoming edge; all native fit, price and veto checks still run.
    positions = {}
    def position(cell):
        if cell not in positions:
            positions[cell] = Position(x=cell[0], y=cell[1], z=cell[2])
        return positions[cell]
    corners = {}
    for delta in neighbors:
        axes = [i for i in range(3) if delta[i]]
        corners[delta] = tuple(tuple(delta[i] if i in selected else 0 for i in range(3))
                               for size in range(1, len(axes)) for selected in combinations(axes, size))
    difficult = engine._hostile_difficult_cells(actor)
    from .falling import supported
    # Flight's terrain, occupied-volume and ordinary surcharge price depends
    # only on its destination in this unchanged query. Reuse that base across
    # the up to 26 incoming edges; elevation providers still price each actual
    # segment. Execution continues through the unmodified per-step function.
    fly_prices = {}
    flight_drag = engine._drag_multiplier(actor) if mode == 'fly' else 1
    def search_cost(previous, destination):
        if mode != 'fly':
            return step_cost(engine, actor, previous, destination, mode, difficult,
                             passage_difficult=passage_difficult)
        key = point(destination)
        if key not in fly_prices:
            fly_prices[key] = step_cost(engine, actor, destination, destination, mode, difficult,
                                        passage_difficult=passage_difficult)
        from .movement_costs import elevation_surcharge
        return fly_prices[key] + elevation_surcharge(engine, actor, previous, destination, mode) * flight_drag
    def search():
        while queue:
            spent, cell = heapq.heappop(queue)
            if spent != costs[cell] or spent >= budget:
                continue
            if mode == "walk" and not supported(engine, actor, position(cell)):
                continue
            for delta in neighbors:
                if delta[2] > 0 and not capability.can_ascend:
                    continue
                nxt = (cell[0] + delta[0], cell[1] + delta[1], cell[2] + delta[2])
                if not fits(nxt):
                    continue
                cost = search_cost(position(cell), position(nxt))
                if spent + cost > budget:
                    continue
                if costs.get(nxt, budget+1) < spent+cost or not fits(nxt):
                    continue
                if any(not fits((cell[0] + dx, cell[1] + dy, cell[2] + dz))
                       for dx, dy, dz in corners[delta]):
                    continue
                if engine.grid.roof_surfaces and engine.grid.roof_step_blocked(cell, nxt, footprint):
                    continue
                if fears and blocking_source(engine, actor, position(cell), position(nxt), sources=fears):
                    continue
                if costs.get(nxt) == spent + cost:
                    predecessors[nxt].add(cell)
                else:
                    costs[nxt], parents[nxt], predecessors[nxt] = spent+cost, cell, {cell}
                    heapq.heappush(queue, (spent+cost, nxt))
    # Search never moves this actor. Its current-square terrain exemption is
    # fixed for the entire read-only search, including elevation providers.
    # Walking keeps its existing per-step repricing path.
    from contextlib import nullcontext
    from .motion import repriced
    with repriced(engine, actor) if mode == 'fly' else nullcontext():
        search()
    # Cost strictly increases along every edge. Keep all cost-optimal parents,
    # then minimize horizontal travel independently of flight's 3D price.
    from .spatial_routes import horizontal_steps, projected_path
    horizontal = horizontal_steps(start, predecessors, costs)
    from types import MappingProxyType
    selected = path_selector(start, MappingProxyType({cell: frozenset(rows) for cell, rows in predecessors.items()}),
                             MappingProxyType(costs), MappingProxyType(parents)) if path_selector else {}
    result = {}
    for cell in sorted(parents):
        if not engine.grid.volume_legal(cell, footprint=footprint, occupied_cells=endpoint_occupied):
            continue
        chain = projected_path(start, cell, predecessors, horizontal)
        if cell in selected:
            chosen = selected[cell]
            if chosen[0] != start or chosen[-1] != cell or any(a not in predecessors.get(b, ()) for a, b in zip(chosen, chosen[1:])):
                raise ValueError('Route selection must use an equal-cost native path')
            chain = list(reversed(chosen))
        path = tuple(Position(x=x, y=y, z=z) for x, y, z in reversed(chain))
        result[path[-1]] = (path, costs[cell], mode)
    if requested is None:
        for destination, route in walking.items():
            if destination not in result or route[1] <= result[destination][1]:
                result[destination] = route
    return result


def _roof_walking(engine, actor, allowance, path_selector=None):
    """Ground-speed alternatives on supported roof surfaces, even with flight.

    Equal-cost alternatives are retained in a predecessor DAG and offered to the
    same native route selector the other movement searches use, so the safer of
    two equally short roof approaches wins here too.
    """
    from .falling import supported
    from .voluntary_movement import fear_sources, blocking_source
    if not allowance or not supported(engine, actor):
        return {}
    start = point(actor.position)
    costs, parents, predecessors, positions = {start: 0}, {}, {}, {start: actor.position}
    queue = [(0, start)]
    fears = fear_sources(engine, actor)
    while queue:
        spent, cell = heapq.heappop(queue)
        if spent != costs[cell] or spent >= allowance or not supported(engine, actor, positions[cell]):
            continue
        for dx, dy in product((-1, 0, 1), repeat=2):
            if not (dx or dy):
                continue
            nxt = (cell[0] + dx, cell[1] + dy, cell[2])
            if not (0 <= nxt[0] < engine.grid.width and 0 <= nxt[1] < engine.grid.height):
                continue
            b = positions.setdefault(nxt, Position(x=nxt[0], y=nxt[1], z=nxt[2]))
            a = positions[cell]
            if not step_allowed(engine, actor, a, b, observed=True):
                continue
            if fears and blocking_source(engine, actor, a, b, sources=fears):
                continue
            cost = spent + step_cost(engine, actor, a, b)
            if cost > allowance:
                continue
            if cost < costs.get(nxt, allowance + 1):
                costs[nxt], parents[nxt], predecessors[nxt] = cost, cell, {cell}
                heapq.heappush(queue, (cost, nxt))
            elif cost == costs.get(nxt):
                predecessors[nxt].add(cell)
    from types import MappingProxyType
    selected = path_selector(start, MappingProxyType({cell: frozenset(rows) for cell, rows in predecessors.items()}),
                             MappingProxyType(costs), MappingProxyType(parents)) if path_selector else {}
    from .creature_passage import endpoint_volumes
    occupied = endpoint_volumes(engine, actor, observed=True)
    result = {}
    for cell in sorted(parents):
        if not engine.grid.volume_legal(positions[cell], footprint=engine._footprint(actor), occupied_cells=occupied):
            continue
        chain = [cell]
        while chain[-1] != start:
            chain.append(parents[chain[-1]])
        if cell in selected:
            chosen = selected[cell]
            if chosen[0] != start or chosen[-1] != cell or any(a not in predecessors.get(b, ()) for a, b in zip(chosen, chosen[1:])):
                raise ValueError('Route selection must use an equal-cost native path')
            chain = list(reversed(chosen))
        result[positions[cell]] = (tuple(positions[p] for p in reversed(chain)), costs[cell], 'walk')
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
    ``jump_height_multiplier(engine, actor)`` is the pure multiplier hook for the score-derived height, before
    flat bonuses. ``jump_bonus_ft(engine, actor)`` is the pure `jump_bonus_ft` hook: flat feet added after that
    multiplication (Polearm Vaulter's Bonus Action increase). Both default to no answer and no bonus, so a creature
    with neither jumps exactly as it did before. A jump bonus also supplies the ascent the minimum score gate
    otherwise asks for, because the printed increase does not depend on Strength.
    """
    from .ext.next_jump import bonus as receipt_bonus
    next_bonus = receipt_bonus(engine, actor)
    if not ext.has("jump_ability") and not ext.has("jump_bonus_ft") and not ext.has("jump_height_multiplier"):
        return actor.strength_score, next_bonus
    ability = "STR"
    for answer in ext.run_strict("jump_ability", engine, actor):
        if answer is not None:
            ability = str(answer).upper()
    score = actor.dexterity_score if ability == "DEX" else actor.strength_score
    multiplier = max(1, max((int(value) for value in ext.run_strict("jump_height_multiplier", engine, actor)
                            if isinstance(value, int)), default=1))
    base_height = max(0, 3 + (int(score) - 10) // 2)
    bonus = max(0, max((int(value) for value in ext.run_strict("jump_bonus_ft", engine, actor)
                        if isinstance(value, int)), default=0))
    return int(score), base_height * (multiplier - 1) + bonus + next_bonus


def jump_steps(engine, actor, ground_path):
    """Quote grid height; next-jump receipts add feet after standing reduction."""
    from .falling import supported
    from .ext.next_jump import bonus as receipt_bonus
    if not ground_path or not supported(engine, actor, ground_path[-1]) or not profile(engine, actor).can_ascend:
        return 0
    score, bonus = jump_score(engine, actor)
    next_bonus = receipt_bonus(engine, actor)
    height = max(0, 3 + (score - 10) // 2) + bonus - next_bonus
    flat = max((int(value) for value in ext.run_strict('jump_flat_bonus_ft', engine, actor)), default=0)
    flat = max(0, min(flat, bonus))
    height = (height - flat) // (1 if _running_start(engine, actor, ground_path) else 2) + flat
    # Both next-jump receipts and flat extension bonuses survive standing reduction.
    return (height + next_bonus) // 5


def horizontal_jump_bonus(engine, actor):
    """Default-inert horizontal jump distance bonus in integer feet."""
    return max((int(value) for value in ext.run_strict('jump_distance_bonus_ft', engine, actor)), default=0)


def straight_jump_path(start, end):
    """Integer-grid straight horizontal jump, preserving altitude and adjacent steps."""
    dx, dy = end.x - start.x, end.y - start.y
    steps = max(abs(dx), abs(dy))
    def offset(delta, i):
        return (1 if delta >= 0 else -1) * ((abs(delta) * i + steps // 2) // steps)
    return tuple(start.model_copy(update={'x': start.x + offset(dx, i), 'y': start.y + offset(dy, i)})
                 for i in range(steps + 1)) if steps else (start,)


def horizontal_jump_feet(engine, actor):
    score, _ = jump_score(engine, actor)
    return max(0, score) // (1 if _running_start(engine, actor, (actor.position,)) else 2) + horizontal_jump_bonus(engine, actor)


@pure
def horizontal_jumps(engine, actor):
    """Opt-in straight jumps; native admission prices and checks every crossed edge."""
    from .falling import supported
    if horizontal_jump_bonus(engine, actor) <= 0 or not supported(engine, actor):
        return {}
    distance = min(horizontal_jump_feet(engine, actor), remaining(engine, actor, 'jump')) // engine.grid.square_size_ft
    result = {}
    for x in range(max(0, actor.position.x-distance), min(engine.grid.width, actor.position.x+distance+1)):
        for y in range(max(0, actor.position.y-distance), min(engine.grid.height, actor.position.y+distance+1)):
            end = actor.position.model_copy(update={'x': x, 'y': y})
            path = straight_jump_path(actor.position, end)
            if len(path) < 2 or any(not step_allowed(engine, actor, a, b, mode='jump', observed=True) for a, b in zip(path, path[1:])):
                continue
            cost = sum(step_cost(engine, actor, a, b, 'jump') for a, b in zip(path, path[1:]))
            if cost <= path_allowance(engine, actor, path, 'jump'):
                result[end] = (path, cost, 'jump')
    return result


def valid_jump(engine, actor, path):
    """A high jump may finish with one level step onto adjacent support.

    The ascent alone is bounded by jump height; the landing still pays movement
    and passes the ordinary step/occupancy/slab checks at admission/execution.
    No horizontal air travel or extra ascent is supplied by a landing.
    """
    from .falling import supported
    first = next((i for i in range(1, len(path)) if path[i].z != path[i-1].z), None)
    if first is None:
        return bool(path and horizontal_jump_bonus(engine, actor) > 0
                    and supported(engine, actor, path[0]) and path[0] != path[-1]
                    and tuple(path) == straight_jump_path(path[0], path[-1])
                    and (len(path)-1) * engine.grid.square_size_ft <= horizontal_jump_feet(engine, actor))
    ground, air = path[:first], path[first:]
    if (len(air) >= 2 and air[-1].z == air[-2].z
            and engine.grid.distance_cells(air[-2], air[-1]) == 1
            and supported(engine, actor, air[-1])):
        air = air[:-1]
    start = ground[-1]
    return (len(air) <= jump_steps(engine, actor, ground)
            and all(p.x == start.x and p.y == start.y and p.z == start.z+i
                    for i, p in enumerate(air, 1)))


@pure
def jumps(engine, actor, walking):
    """Grid high jumps: rise whole 5-ft steps, land on adjacent support or fall.

    One pure route search shares perception and terrain queries across its
    vertical steps, just like reachable(). Nothing survives the search or is
    inherited by execution; no actor is moved while these routes are priced.

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
    from .falling import supported
    from .creature_passage import endpoint_volumes
    endpoint_occupied = endpoint_volumes(engine, actor, observed=True)
    footprint = engine._footprint(actor)
    result = {}
    routes = [((actor.position,), 0)] + [(route[0], route[1] * engine._drag_multiplier(actor) if len(route) == 2 else route[1]) for route in walking.values()
                                       if len(route) == 2 or route[2] == "walk"]
    for ground, cost in routes:
        path = list(ground)
        for _ in range(jump_steps(engine, actor, ground)):
            nxt = path[-1].model_copy(update={"z": path[-1].z+1})
            cost += step_cost(engine, actor, path[-1], nxt, "jump")
            if cost > path_allowance(engine, actor, (*path, nxt), 'jump') or not step_allowed(engine, actor, path[-1], nxt, mode="jump", observed=True):
                break
            path.append(nxt)
            if nxt not in result or result[nxt][1] > cost:
                result[nxt] = (tuple(path), cost, "jump")
            # Keep every supported landing at this attainable height. As with
            # flight/climbing, rise outside the eave before stepping onto it.
            for dx, dy in product((-1, 0, 1), repeat=2):
                if not (dx or dy):
                    continue
                landing = nxt.model_copy(update={"x": nxt.x + dx, "y": nxt.y + dy})
                if (not supported(engine, actor, landing)
                        or not engine.grid.volume_legal(landing, footprint=footprint,
                                                       occupied_cells=endpoint_occupied)
                        or not step_allowed(engine, actor, nxt, landing, mode="jump", observed=True)):
                    continue
                landing_cost = cost + step_cost(engine, actor, nxt, landing, "jump")
                if landing_cost <= path_allowance(engine, actor, (*path, landing), 'jump') and (landing not in result or result[landing][1] > landing_cost):
                    result[landing] = (tuple(path) + (landing,), landing_cost, "jump")
    return result
