"""Inimical Gaze (The Hidden Eye, Action, Expend Martial Focus): "Choose one Approach you know. Make one Analyze check using that
Approach and compare the result against the Analyze DC of each creature within your Analyze range that the Approach can validly
target. On each success, learn one Analyzable Characteristic of that creature and it becomes Analyzed by you."

One Analyze roll (combat/ext/mind_hidden_eye.py ``analyze_roll``: a chosen Approach
for reviewed lane 14 bundles) is set against each enemy in the actor's Analyze range; each success
makes that enemy Analyzed by the gazer. Allies are not rolled against (nothing to learn from them); which characteristic is
learned stays the GM's. It is a self-aimed action: with no enemy in range and sight the choice is not offered, so the Martial
Focus is not spent on nothing.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .mind_hidden_eye import analyze_result, analyze_roll

REACH = 60


def _in_gaze(engine: Any, actor: Any) -> list[Any]:
    from .riders14_eye import analyze_range, attempts_left, has
    from .. import stealth

    reviewed = has(engine, actor, "analysis_limits")

    return sorted((other for other in engine.state.actors.values()
                   if other.active and other.entity_id != actor.entity_id and (reviewed or other.team_id != actor.team_id)
                   and engine._distance_actor_to_actor(actor, other) <= analyze_range(engine, actor)
                   and attempts_left(engine, actor, other)
                   and (stealth.sees(engine, actor, other) if reviewed else engine._line_of_sight_actor_to_actor(actor, other))),
                  key=lambda other: (engine._distance_actor_to_actor(actor, other), other.entity_id))


def _row(action: Any) -> bool:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    return any(isinstance(row, dict) and row.get("type") == "analyze_all" for row in typed.get("effects") or [])


@hook("candidate_allowed")
def gaze_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    return bool(_in_gaze(engine, actor)) if _row(action) else None


@effect("analyze_all")
def analyze_all(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    seen = _in_gaze(engine, actor)
    if not seen:
        ctx.rider("Inimical Gaze: no valid creature within Analyze range that you can perceive.")
        return
    roll = analyze_roll(engine, actor)
    for target in seen:
        analyze_result(ctx, roll, target)
