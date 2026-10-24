"""The shared rule for when a match is decided.

One implementation, used by two callers:

* ``Gate2Engine._check_victory`` at damage and resolution boundaries;
* ``combat.ext.life_state.resolve_stable_opponents`` at a turn boundary, so a
  helpless last opponent ends the fight after end-of-turn effects instead of
  waiting for a saving throw.

A side is defeated when every creature on it is down (Dying, Stable or
otherwise unable to act) and none of them owns an in-combat way back by itself.
A summon or ally that can act keeps its side live. ``self_recovery`` is the
pure, default-inert plug-in query for a way back; a natural 20 on a death
saving throw is not one, because an enemy would finish the creature off.

The caller decides nothing about the result: this module only reports it.
"""
from __future__ import annotations

from typing import Any

from .gate2_runtime_models import TerminalKind


def can_act(actor: Any) -> bool:
    """Whether the creature can take its turn now.

    Dying and Stable creatures are unconscious. A Conscious-at-zero creature
    still can act. Inactive creatures are off the field: a defeated fighter, a
    destroyed summon or a departed soul. A life state of ``None`` is the legacy
    zero-HP representation for a creature the engine has not marked down, so it
    can act whatever its Hit Points; only DYING/STABLE marks a creature down.
    """
    if not actor.active:
        return False
    return actor.life_state not in ("DYING", "STABLE")


def recovers_alone(engine: Any, actor: Any) -> bool:
    """Whether a downed creature itself can come back without another creature's help."""
    if not actor.active or actor.life_state not in ("DYING", "STABLE"):
        return False
    from . import ext

    for answer in ext.run_strict("self_recovery", engine, actor):
        if type(answer) is not bool:
            raise ValueError("self_recovery must return bool or None")
        if answer:
            return True
    return False


def decide(engine: Any) -> tuple[TerminalKind, str | None, str] | None:
    """The match result now, or None while at least two sides can still continue."""
    state = engine.state
    teams = {actor.team_id for actor in state.actors.values() if actor.primary_combatant}
    if not teams:
        return None
    team_actors = {team: [actor for actor in state.actors.values() if actor.team_id == team] for team in teams}
    live = {team for team, rows in team_actors.items() if any(can_act(actor) for actor in rows)}
    defeated = {team for team, rows in team_actors.items()
                if team not in live and not any(recovers_alone(engine, actor) for actor in rows)}
    contenders = sorted(teams - defeated)
    if len(contenders) == 1:
        team = contenders[0]
        opponents = [actor for actor in state.actors.values() if actor.team_id != team]
        reason = ("Opposing primary combatants are inactive."
                  if all(not actor.active for actor in opponents)
                  else "All opposing combatants are down and cannot recover.")
        return TerminalKind.VICTORY, team, reason
    if not contenders:
        return (TerminalKind.DRAW_SIMULTANEOUS, None,
                "Mutual knockout: no combatant on any side can act.")
    return None
