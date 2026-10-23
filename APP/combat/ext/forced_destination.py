"""Shared helper: the square a forced move puts a creature on, asked of the creature that caused it.

Users: ``gravity.py`` -- Orbit-Breaking Guard ("Move the attacker 10 feet to an unoccupied space adjacent
to you") and Weight-Borrowing Throw ("move the target 5 feet in any horizontal direction"), and
``water_pull.py`` -- Pull of the River ("pull the target 10 feet"), which is the one caller that
offers the printed "you may" and therefore passes ``allow_decline=True``. One
implementation of that printed choice: :func:`routes` enumerates the legal destinations with the engine's
own altitude-aware volume legality (``grid.volume_step_legal``, the same check a typed push or pull stops
at), :func:`ask` puts the answer to the creature that caused the move with ``needle.ask`` in the engine's
own cell labels, and :func:`moved` carries it out through the engine's own forced path
(``movement_paths.resolve(kind='forced')``).

Two printed facts shape the enumeration. "In any horizontal direction" never climbs or descends, so every
destination sits on the mover's own level and keeps its altitude (a creature fighting at twenty feet is
offered squares twenty feet up, not squares on the floor). Forced displacement spends no walking movement,
so the range is the printed displacement distance counted in squares -- difficult terrain, terrain cost and
the mover's own Speed are not consulted, because a thrown creature does not walk.

The displacement distance is the *printed* one. A rule that states a destination without stating how far the
creature walks ("Move it to a legal space adjacent to you") is not a rule with a smaller budget: pass
``feet=None`` with the destination set as ``goals`` and the search runs until every legal destination is
reached, however far round the obstacles the route has to go. Reusing a nearby number from the same printed
paragraph -- the action's Range, say -- would quietly drop legal destinations on the far side of the chooser,
because a destination is often further from the creature being moved than the chooser is.

The move itself is a real forced path: the standing cut, the moved creature's own forced-moved reaction and
ally answers, its ``forced_movement_reduction`` hooks (Store the Collision, Willow-Bend Defense) and the
per-step ``forced_movement_attempt``/``forced_movement_step`` checkpoints all apply, exactly as they do to
a typed Shove, and the result is one recorded MOVEMENT_COMMITTED carrying the route actually walked. Nothing
here is stored on the fight: a forced move is already recorded by that event.

Each caller keeps its own checkpoint, choice id, prompt and menu name (they appear in the saved fight),
supplies its own ``Context`` so the moved creature's reductions run on the activation that caused the move,
and may add its own non-square options as ``(option_id, label, handler)`` triples, asked after every square
(Weight-Borrowing Throw's "knock it Prone").
"""

from __future__ import annotations

from typing import Any, Callable

# The eight neighbouring spaces, in the row-then-column order the engine labels squares by.
NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1))

# "Adjacent" is the engine's own measure everywhere it tests it (the forced-move reaction and defense
# checks, the reach tests): one square, measured between the two creatures' own volumes.
ADJACENT_FT = 5


def _footprint_reach(footprint: Any) -> int:
    """How far, in cells, a footprint's own volume can sit from its anchor.

    A footprint is anchored top-left and may reach right and down (``combat.footprints``), and the
    engine's 3D volume adds one layer per row of that span on top (``combat.space._volume``). The
    bounding-box span here is deliberately the same arithmetic as that volume derivation, so the
    result never understates how far an occupied cell can be from the anchor it is placed by.
    """
    if footprint is None:
        return 0
    cells = tuple(footprint.occupied_relative_cells)
    horizontal = max(max(abs(cell.x), abs(cell.y)) for cell in cells)
    xs, ys = [cell.x for cell in cells], [cell.y for cell in cells]
    vertical = max(max(xs) - min(xs) + 1, max(ys) - min(ys) + 1) - 1
    return max(horizontal, vertical)


def adjacent_spaces(engine: Any, who: Any, occupant: Any = None, *, grid: Any = None) -> tuple[Any, ...]:
    """Every space adjacent to ``who`` in the stable row-then-column order.

    Adjacency is the engine's own measure -- within :data:`ADJACENT_FT` between the occupant's own volume and
    ``who``'s, the same test every forced move uses -- so a Large occupant can be offered a square a Medium
    one could not stand in. Without an ``occupant`` every in-bounds neighbour is returned; with one, the
    squares are also filtered by whether its footprint could legally hold it there under the live occupancy
    (walls, other creatures and itself), through the engine's own volume test.

    Candidate anchors are enumerated around *both* creatures' real footprints, never around a single
    anchor's eight neighbours. Footprints are anchored top-left and extend right and down
    (``combat.footprints.ActorFootprintDefinition.occupied_cells``), while the engine measures separation
    between the two occupied *cell sets* (``Gate2Combatant._distance_actor_to_actor``). For a multi-cell
    creature those are different shapes, so the eight offsets of ``who``'s own anchor omit anchors that are
    genuinely legal: a 2x2 target two cells west of a Medium chooser's anchor is still one cell from the
    chooser's body, and a Medium target two cells east of a 2x2 chooser's anchor is still one cell from that
    chooser's body. Losing those arrivals is a player-visible loss of legal destinations, and when the
    eight neighbouring sides are blocked a paid draw would otherwise do nothing.

    The enumeration below is a provable *superset*, not the answer. Any anchor kept by the engine's own
    separation test has some occupied cell ``a + r`` within ``k`` cells of a cell ``b`` of ``who`` (the
    engine measures Chebyshev separation between cell sets), with ``max|r|`` bounded by the occupant's
    own footprint reach, so ``cheb(a, b) <= k + footprint reach``. Every such anchor therefore lies
    within that radius of one of ``who``'s own occupied cells, which is exactly what is walked. The
    distance and ``volume_legal`` filters are the engine's own and stay the sole authority, so a
    wider bound costs a few extra candidates and can never widen the offered set.

    This is the ``goals`` set for a forced move whose printed text names a place beside somebody rather than
    a distance: it bounds the answer without pretending the creature may only walk a shorter distance."""
    from ..gate2_runtime_models import Position

    grid = grid if grid is not None else engine.grid
    if occupant is None:
        spaces = []
        for dx, dy in NEIGHBORS:
            x, y = who.position.x + dx, who.position.y + dy
            if not grid.in_bounds((x, y)):
                continue
            spaces.append(Position(x=x, y=y, z=who.position.z))
        return tuple(sorted(spaces, key=lambda cell: (cell.y, cell.x)))

    # The routes that consume these goals preserve the moved creature's altitude. Build the goal
    # anchors on that same level so a chooser and mover at different heights can still agree on a
    # legal arrival. The engine's 3D volume distance below remains the authority on adjacency.
    arrival_z = occupant.position.z
    occupied = engine._occupied_volumes_except(occupant.entity_id)
    footprint = engine._footprint(occupant)
    # The engine's own separation measure in cells; volume_legal/terrain filter what survives.
    budget = ADJACENT_FT // grid.square_size_ft
    reach = budget + _footprint_reach(footprint)
    found: dict[tuple[int, int, int], Any] = {}
    for base in engine._actor_cells(who):
        for x in range(base[0] - reach, base[0] + reach + 1):
            for y in range(base[1] - reach, base[1] + reach + 1):
                if not grid.in_bounds((x, y)):
                    continue
                key = (x, y, arrival_z)
                if key in found:
                    # A multi-cell chooser reaches the same anchor from more than one of its own
                    # cells; the space is one space and must be offered once.
                    continue
                cell = Position(x=x, y=y, z=arrival_z)
                if engine._distance_actor_to_actor(occupant, who, actor_position=cell) > ADJACENT_FT:
                    continue
                if not grid.volume_legal(cell, footprint=footprint, occupied_cells=occupied):
                    continue
                found[key] = cell
    return tuple(sorted(found.values(), key=lambda cell: (cell.y, cell.x)))


def routes(engine: Any, mover: Any, feet: int | None, *, want: Callable[[Any], bool] | None = None,
           step_allowed: Callable[[Any, Any], bool] | None = None,
           goals: Any = None, grid: Any = None) -> dict[Any, tuple[Any, ...]]:
    """One forced route per square ``mover`` may be put on within ``feet``: ``{destination: (start, ..., destination)}``.

    Every step is an adjacent space on the mover's own altitude and is legal by the engine's own
    altitude-aware volume test against the live occupancy (walls, creatures and the mover's own footprint),
    so the printed "any horizontal direction" has somewhere legal to land even for a creature in the air.
    The search is breadth-first over the eight neighbours, so a route is the shortest one at that distance,
    and destinations come out in a stable row-then-column order. ``want(cell)`` narrows them to one further
    rule (Orbit-Breaking Guard's "adjacent to you"). ``step_allowed(previous, next)``
    constrains every traversed step (Pull of the River's "toward you"), before
    marking a square visited. None preserves unrestricted routes for other users.

    ``feet`` is the printed displacement distance, or ``None`` when the printed text states a destination and
    no distance. Then ``goals`` (:func:`adjacent_spaces` and friends) is the whole destination set and only
    those squares are offered: the search stops as soon as every one of them has been found, and otherwise
    runs until the space reachable from ``mover`` is exhausted, so a destination that needs a long detour
    round an obstacle is still offered and a walled-in one simply never appears. This caps nothing."""
    from ..gate2_runtime_models import Position

    grid = grid if grid is not None else engine.grid
    start = mover.position
    limit = None if feet is None else max(0, int(feet) // grid.square_size_ft)
    destinations = None if goals is None else {(goal.x, goal.y, goal.z) for goal in goals}
    outstanding = None if destinations is None else destinations - {(start.x, start.y, start.z)}
    occupied = engine._occupied_volumes_except(mover.entity_id)
    footprint = engine._footprint(mover)
    found: dict[Any, tuple[Any, ...]] = {}
    seen = {(start.x, start.y, start.z)}
    frontier = [(start, (start,))]
    depth = 0
    while frontier and depth != limit and outstanding != set():
        following = []
        for cell, path in frontier:
            for dx, dy in NEIGHBORS:
                x, y = cell.x + dx, cell.y + dy
                if (x, y, cell.z) in seen or not grid.in_bounds((x, y)):
                    continue
                nxt = Position(x=x, y=y, z=cell.z)
                if step_allowed is not None and not step_allowed(cell, nxt):
                    continue
                if not grid.volume_step_legal(cell, nxt, occupied_cells=occupied, footprint=footprint):
                    continue
                seen.add((x, y, cell.z))
                route = (*path, nxt)
                if want is not None:
                    keep = bool(want(nxt))
                elif destinations is not None:
                    keep = (x, y, cell.z) in destinations
                else:
                    keep = True
                if keep:
                    found[nxt] = route
                    if outstanding is not None:
                        outstanding.discard((x, y, cell.z))
                following.append((nxt, route))
        frontier = following
        depth += 1
    return {cell: found[cell] for cell in sorted(found, key=lambda cell: (cell.y, cell.x))}


def directional_routes(engine: Any, mover: Any, origin: Any, feet: int | None, *,
                       away: bool = False, nearest: bool = False, stay: bool = False, grid: Any = None) -> dict[Any, tuple[Any, ...]]:
    """Reusable legal push/pull destinations, preserving body and volume legality.

    Distance is measured between actual bodies. Destinations must lie in the
    printed direction; a legal route may detour around an obstacle. ``nearest`` retains every equally nearest reachable
    arrival for a mandatory pull that cannot reach adjacency. ``stay`` is for
    'up to' movement, where zero feet is also a legal owner decision. It never
    truncates destinations or substitutes movement through an undersized gap.
    Used by Palm Across Emptiness's Draw fallback and chosen Cast distance.
    """
    distance = lambda cell: engine._distance_actor_to_actor(mover, origin, actor_position=cell)
    start_distance = distance(mover.position)
    found = routes(engine, mover, feet, grid=grid, want=lambda cell:
                   distance(cell) > start_distance if away else distance(cell) < start_distance)
    if nearest and found:
        closest = min(distance(cell) for cell in found)
        found = {cell: path for cell, path in found.items() if distance(cell) == closest}
    if stay:
        found[mover.position] = (mover.position,)
    return found


def squares(engine: Any, mover: Any, feet: int, *, want: Callable[[Any], bool] | None = None) -> list[Any]:
    """The destinations :func:`routes` offers, in the same stable order."""
    return list(routes(engine, mover, feet, want=want))


def moved(engine: Any, mover: Any, route: Any, *, source: str, intent: Any, chooser: Any, ctx: Any = None) -> int:
    """Carry out the chosen forced move and return the physical feet it travelled (0 when a defense
    stopped it). ``chooser`` is the creature causing the move and ``ctx`` its resolution Context, so the
    moved creature's own forced-movement defenses answer against this activation."""
    from ..movement_paths import resolve as resolve_path

    route = tuple(route)
    return resolve_path(engine, mover, route, source, kind="forced",
                        feet=(len(route) - 1) * engine.grid.square_size_ft, intent=intent,
                        provokes=False, source_actor_id=chooser.entity_id, ctx=ctx)


def ask(engine: Any, intent: Any, chooser: Any, mover: Any, cells: Any, *, source: str, checkpoint: str,
        choice_id: str, prompt: str, name: str = "", target_id: str | None = None, ctx: Any = None,
        also: Any = (), allow_decline: bool = False, prompt_context: dict[str, str] | None = None) -> str | None:
    """Put ``chooser``'s answer into effect and return the option id it chose, or ``None`` when nobody
    answered. ``cells`` is a :func:`routes` mapping; a square moves ``mover`` there through the engine's own
    forced path, keeping the altitude it was offered at, and an ``also`` option runs its own handler instead.

    ``allow_decline`` is for a printed "you may": the chooser can decline the whole move, which
    returns ``None`` and leaves ``mover`` exactly where it was. ``prompt_context``
    forwards explicit action metadata for nested attacks (Borrowed Momentum). It defaults off, so the callers
    that must move something keep their existing behaviour."""
    from .needle import ask as ask_choice, cell_id

    where = {cell_id(cell): cell for cell in cells}
    options = list(where)
    labels = {option: f"Put it at {option.split(':', 1)[1]}" for option in options}
    for option_id, label, _handler in also:
        options.append(option_id)
        labels[option_id] = label
    if not options:
        return None
    picked = ask_choice(engine, intent, checkpoint, chooser, choice_id, options, labels=labels, name=name,
                        target_id=target_id or mover.entity_id, prompt=prompt, allow_decline=allow_decline,
                        prompt_context=prompt_context)
    if not picked:
        return None
    for option_id, _label, handler in also:
        if picked[0] == option_id:
            handler()
            return picked[0]
    moved(engine, mover, cells[where[picked[0]]], source=source, intent=intent, chooser=chooser, ctx=ctx)
    return picked[0]
