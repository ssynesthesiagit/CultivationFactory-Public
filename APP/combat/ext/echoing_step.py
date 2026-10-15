"""Echoing Step (Music, Phrase, Bonus Action, 1 CP or 1 Stamina): "Until the end of your turn: ignore nonmagical difficult
terrain; do not provoke Opportunity Attacks from one creature that can perceive your Measure; move through spaces occupied by
willing allies; leave a faint audible, spiritual, or visual echo."

The step sets a turn flag. combat/motion.py ``ignores_difficult`` reads it for the difficult terrain. The "one creature" is the
nearest enemy when the step is taken (ties by id): it makes no Opportunity Attack against the mover (the ``opportunity_allowed``
hook) for the rest of the turn. Moving through willing allies' spaces and the echo are left to the table.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

FLAG = "echoing_step"
CREATURE = "echoing_step_creature"


@effect("echoing_step")
def echoing_step(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    foes = sorted((other for other in engine.state.actors.values() if other.active and other.team_id != actor.team_id),
                  key=lambda other: (engine._distance_actor_to_actor(actor, other), other.entity_id))
    actor.turn_flags[FLAG] = True
    actor.turn_flags[CREATURE] = foes[0].entity_id if foes else ""
    ctx.rider("Echoing Step: nonmagical difficult terrain costs nothing extra until the end of the turn"
              + (f"; {foes[0].display_name} makes no Opportunity Attack against {actor.display_name}." if foes else "."))


@hook("opportunity_allowed")
def echoing_step_no_attack(engine: Any, reactor: Any, mover: Any) -> bool | None:
    if not mover.turn_flags.get(FLAG) or engine.state.current_actor_id != mover.entity_id:
        return None
    return False if mover.turn_flags.get(CREATURE) == reactor.entity_id else None
