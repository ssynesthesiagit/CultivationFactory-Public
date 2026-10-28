"""Drunken Fist Subpath riders (rider lane C7, 2026-09-30).

Heavenly Drunk, "Standing from Prone costs no movement": the native stand_cost
query returns zero while its state is active. The shared posture transition owns
the condition removal and STOOD_UP event, for turn starts and explicit standing.
Inert without the state. The walking_cost hook also implements "Crawl at your
full Speed" by waiving the extra crawl cost, without ignoring difficult terrain.
"""

from __future__ import annotations

from typing import Any

from . import hook

STATE = "heavenly_drunk"


@hook("choice_reactors")
def heavenly_drunk_choice_reactors(engine: Any) -> tuple[str, ...]:
    """Enroll active manual Heavenly Drunk owners for off-turn miss-step choices."""
    from ..tabletop_service import MANUAL_MODES
    from .states import active

    modes = getattr(engine, "typed_control_modes", {}) or {}
    return tuple(sorted(actor.entity_id for actor in engine.state.actors.values()
                        if actor.active and active(engine, actor, STATE)
                        and modes.get(actor.owner_id or actor.entity_id, "MANUAL") in MANUAL_MODES))


@hook('walking_cost')
def normal_crawl(engine: Any, actor: Any, normal_extra: int) -> int | None:
    from .states import active
    if actor.active and active(engine, actor, STATE):
        return 0
    return None


@hook("stand_cost")
def free_stand(engine: Any, actor: Any, normal_cost: int) -> int | None:
    from .states import active

    if actor.active and active(engine, actor, STATE):
        return 0
    return None


@hook("movement_pass_through")
def hostile_spaces_are_difficult(engine: Any, mover: Any, occupant: Any) -> bool | None:
    """Heavenly Drunk (tianxia.subpath.body.drunken_fist.feature.heavenly_drunk): while it is active, enemy-occupied spaces are difficult terrain you may pass through. Ending the move in an occupied space is still not allowed."""
    from ..relations import ENEMY, relation
    from .states import active

    if mover.active and occupant is not None and relation(engine, mover, occupant) == ENEMY and active(engine, mover, STATE):
        return True
    return None


@hook("after_miss")
def heavenly_drunk_miss_step(ctx: Any, target: Any) -> None:
    """Offer the active owner a free post-miss step, limited to one accepted move per round.

    The attack has resolved before this callback. A declined choice consumes
    nothing. Every hostile creature is exempted from opportunity attacks using
    the shared athletics.opportunity_reactors query. See the Heavenly Drunk
    record (tianxia.subpath.body.drunken_fist.feature.heavenly_drunk).
    """
    from ..relations import ENEMY, relation
    from . import rider_choices
    from .athletics import opportunity_reactors
    from .states import active

    engine, attacker = ctx.engine, ctx.actor
    if target is None or not target.active or not attacker.active or relation(engine, target, attacker) != ENEMY:
        return
    if not active(engine, target, STATE):
        return
    once = "once_per_round:heavenly_drunk"
    if target.turn_flags.get(once) == engine.state.round_number:
        return
    if not rider_choices.step(engine, target, "heavenly_drunk_after_a_miss", "Heavenly Drunk", attacker, 10, ctx.source,
                              ctx.intent, trigger=(f"{attacker.display_name} misses {target.display_name}; move up to 10 feet "
                                                  "without provoking any Opportunity Attack"),
                              ignored_oa=opportunity_reactors(engine, target)):
        return
    target.turn_flags[once] = engine.state.round_number
