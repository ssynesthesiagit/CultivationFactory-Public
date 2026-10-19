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


def routes(engine: Any, mover: Any, feet: int, *, want: Callable[[Any], bool] | None = None,
           step_allowed: Callable[[Any, Any], bool] | None = None) -> dict[Any, tuple[Any, ...]]:
    """One forced route per square ``mover`` may be put on within ``feet``: ``{destination: (start, ..., destination)}``.

    Every step is an adjacent space on the mover's own altitude and is legal by the engine's own
    altitude-aware volume test against the live occupancy (walls, creatures and the mover's own footprint),
    so the printed "any horizontal direction" has somewhere legal to land even for a creature in the air.
    The search is breadth-first over the eight neighbours, so a route is the shortest one at that distance,
    and destinations come out in a stable row-then-column order. ``want(cell)`` narrows them to one further
    rule (Orbit-Breaking Guard's "adjacent to you"). ``step_allowed(previous, next)``
    constrains every traversed step (Pull of the River's "toward you"), before
    marking a square visited. None preserves unrestricted routes for other users."""
    from ..gate2_runtime_models import Position

    start = mover.position
    limit = max(0, int(feet) // engine.grid.square_size_ft)
    occupied = engine._occupied_volumes_except(mover.entity_id)
    footprint = engine._footprint(mover)
    found: dict[Any, tuple[Any, ...]] = {}
    seen = {(start.x, start.y, start.z)}
    frontier = [(start, (start,))]
    for _ in range(limit):
        following = []
        for cell, path in frontier:
            for dx, dy in NEIGHBORS:
                x, y = cell.x + dx, cell.y + dy
                if (x, y, cell.z) in seen or not engine.grid.in_bounds((x, y)):
                    continue
                nxt = Position(x=x, y=y, z=cell.z)
                if step_allowed is not None and not step_allowed(cell, nxt):
                    continue
                if not engine.grid.volume_step_legal(cell, nxt, occupied_cells=occupied, footprint=footprint):
                    continue
                seen.add((x, y, cell.z))
                route = (*path, nxt)
                if want is None or want(nxt):
                    found[nxt] = route
                following.append((nxt, route))
        frontier = following
        if not frontier:
            break
    return {cell: found[cell] for cell in sorted(found, key=lambda cell: (cell.y, cell.x))}


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
