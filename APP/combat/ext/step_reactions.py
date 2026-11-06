"""Shared movement checkpoint for reactions that must answer at the step that meets them, and a way for them to end the move.

Reactions to a willing creature entering a watcher's range, or having moved N feet within it, normally answer after the
whole move (typed_reactions.on_moved_geometry). A reaction whose trigger reading sets ``at_step`` is answered here instead,
from the existing ``movement_step`` checkpoint, right after the step that meets it has been paid and entered: ``enters_range``
when this step crosses into the watcher's range, ``moved`` when the feet walked inside the watcher's range this turn first reach
``min_move_ft`` on this step. The route is the read-only one movement_steps.route supplies; the feet already counted are kept in
the mover's ordinary turn flags, so the count carries from one committed route to the next and resets at its next turn.

``stop_movement`` is the effect such a reaction (or any effect on a moving creature) uses to end the move in the space where it
now stands: it raises the engine's existing movement_interrupted_sequence turn flag, which the native step loop already
honours, and does nothing for a creature that is not mid-move. Forced movement never reaches this checkpoint.

Shared helpers used: typed_reactions.dispatch_creature_reactions (the same rows, consent, costs and use limits as any creature
event). Consumers: Crown of Black Thorns (its trigger reading); a later "stops in the space where it triggered" effect needs
only the effect row.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook


def _feet(engine: Any, a: Any, b: Any) -> int:
    return int(engine.grid.distance_ft(a, b))


def _walked(engine: Any, mover: Any, previous: Any, nxt: Any) -> list[Any]:
    from ..movement_steps import route

    path = list((route(engine, mover) or {}).get("path") or ())
    return path[:path.index(nxt) + 1] if nxt in path else [previous, nxt]


@hook("movement_step")
def answer_at_step(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> None:
    if not mover.active or mover.position != nxt or not getattr(engine, "typed_actor_ids", None):
        return None
    from .. import typed_reactions

    walked = _walked(engine, mover, previous, nxt)

    def inside(watcher: Any, radius: int, steps: list[Any]) -> int:
        return sum(_feet(engine, a, b) for a, b in zip(steps, steps[1:])
                   if _feet(engine, a, watcher.position) <= radius and _feet(engine, b, watcher.position) <= radius)

    def radius(row: dict[str, Any], watcher: Any) -> int:
        if row.get("natural_reach"):
            from .reach_bonus import natural_reach_ft

            return natural_reach_ft(engine, watcher)
        return int(row.get("range_ft") or 5)

    def entered(row: dict[str, Any], watcher: Any) -> bool:
        radius_ft = radius(row, watcher)
        anchors = [watcher] if row.get("self_only") else [a for a in engine.state.actors.values() if a.active and a.team_id == watcher.team_id]
        return any(_feet(engine, previous, a.position) > radius_ft >= _feet(engine, nxt, a.position) for a in anchors)

    def reached(row: dict[str, Any], watcher: Any) -> bool:
        radius_ft, need = radius(row, watcher), int(row.get("min_move_ft") or 0)
        if need <= 0:
            return False
        key = f"step_reaction_distance:{row.get('feature_id')}:{watcher.entity_id}"
        prior = int(mover.turn_flags.get(key, 0) or 0)
        before, now = inside(watcher, radius_ft, walked[:-1]), inside(watcher, radius_ft, walked)
        # ``prior`` already counts the feet walked inside the range on the earlier steps of this route and on the routes
        # committed before it, so this step adds only what it walked itself (``now - before``). The threshold is met on a step
        # when the running total passes it, not when the route's own earlier feet are counted a second time.
        step_ft = max(0, now - before)
        mover.turn_flags[key] = prior + step_ft
        return prior < need <= prior + step_ft

    total = sum(_feet(engine, a, b) for a, b in zip(walked, walked[1:]))
    typed_reactions.dispatch_creature_reactions(engine, mover, "enters_range", accept=entered, at_step=True)
    if mover.active and mover.position == nxt:
        typed_reactions.dispatch_creature_reactions(engine, mover, "moved", moved_ft=total, accept=reached, at_step=True)
    return None


@effect("stop_movement")
def stop_movement(ctx: Any, row: dict[str, Any]) -> None:
    """The creature's current move ends where it stands (a failed save against a trap on its path)."""
    from ..movement_steps import context

    for target in ctx.targets or ([ctx.target] if ctx.target is not None else []):
        if target is None or not target.active or not context(ctx.engine, target):
            continue
        target.turn_flags["movement_interrupted_sequence"] = ctx.engine.state.event_sequence + 1
        ctx.engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                                 payload={"log": f"{target.display_name}'s movement ends here."})
