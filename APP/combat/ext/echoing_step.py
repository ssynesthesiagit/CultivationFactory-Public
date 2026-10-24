"""Echoing Step (Music, Phrase, Bonus Action, 1 CP or 1 Stamina): "Until the end of your turn: ignore nonmagical difficult
terrain; do not provoke Opportunity Attacks from one creature that can perceive your Measure; move through spaces occupied by
willing allies; leave a faint audible, spiritual, or visual echo."

The step sets a turn flag. combat/motion.py ``ignores_difficult`` reads it for difficult terrain. The user chooses one creature
that perceives the Measure through the transactional choice transport; AI prefers the nearest known enemy. That creature makes
no Opportunity Attack against the mover (``opportunity_allowed``) for the rest of the turn. Willing ally passage remains open.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

FLAG = "echoing_step"
CREATURE = "echoing_step_creature"


def recipients(engine: Any, actor: Any) -> list[Any]:
    """Known recipients of the audible, visual or spiritual Measure.

    Remembering a creature permits choosing it without locating it now. Rank
    remembered enemies by their observed position, never their hidden position.
    Hearing uses the native Deafened and sound-path rules independently of sight.
    """
    from .. import senses, speech
    from ..target_knowledge import knowledge

    known = []
    for other in engine.state.actors.values():
        if not other.active or other is actor:
            continue
        info = knowledge(engine, actor, other)
        if info is None:
            continue
        if not (senses.perceives(engine, other, actor)
                or speech.can_hear_from(engine, actor, other, "tianxia.talent.music.echoing_step")):
            continue
        observed = other.model_copy(update={"position": info.position})
        known.append((other, engine._distance_actor_to_actor(actor, observed)))
    return [other for other, distance in sorted(known, key=lambda pair: (
        pair[0].team_id == actor.team_id, pair[1], pair[0].entity_id))]


@effect("echoing_step")
def echoing_step(ctx: Any, eff: dict[str, Any]) -> None:
    from .needle import ask
    from .choice_prompt import action_context

    engine, actor = ctx.engine, ctx.actor
    pool = recipients(engine, actor)
    chosen = ask(engine, ctx.intent, "TECHNIQUE_USE", actor, "choice:needle.echoing_step_creature",
                 [other.entity_id for other in pool],
                 labels={other.entity_id: f"{other.display_name}: no Opportunity Attacks against you this turn"
                         for other in pool}, preferred=[other.entity_id for other in pool[:1]],
                 name="Echoing Step", feature_id="tianxia.talent.music.echoing_step",
                 prompt_context=action_context(engine, actor, ctx.action.source_definition_id, actor, action=ctx.action),
                 prompt=f"Echoing Step: choose one creature that perceives {actor.display_name}'s rhythm. "
                        "Your movement does not provoke Opportunity Attacks from that creature until this turn ends. "
                        "The choice has no extra cost beyond Echoing Step's Bonus Action and 1 Cultivation Point (CP) or 1 Stamina.")
    actor.turn_flags[FLAG] = True
    actor.turn_flags[CREATURE] = chosen[0] if chosen else ""
    ctx.rider("Echoing Step: nonmagical difficult terrain costs nothing extra until the end of the turn"
              + (f"; {engine.state.actors[chosen[0]].display_name} makes no Opportunity Attack against {actor.display_name} this turn."
                 if chosen else "."))


@hook("opportunity_allowed")
def echoing_step_no_attack(engine: Any, reactor: Any, mover: Any) -> bool | None:
    if not mover.turn_flags.get(FLAG) or engine.state.current_actor_id != mover.entity_id:
        return None
    return False if mover.turn_flags.get(CREATURE) == reactor.entity_id else None
