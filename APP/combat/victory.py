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

That defeat is a rule of the 2024 dying rules, exactly as the turn-boundary
caller already treats it (``resolve_stable_opponents`` only runs for
``rules["zero_hp"] == "dying_2024"``). A fight without those rules marks a
creature out of the fight with ``active=False`` and keeps it on the field at 0
Hit Points otherwise, so a life state alone never decides it: main's recovery
consumers set a Dying creature up and then commit and reload the fight before
its own saving throw (``test_riders_c8_recovery``). One rule for both callers,
and one rule for every control mode: a seat's control mode never decides who
may still come back.

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


def uses_new_dying_rules(engine: Any) -> bool:
    """Whether this fight decides defeat by life state instead of ``active``."""
    rules = getattr(engine.state, "rules", None) or {}
    return rules.get("zero_hp") == "dying_2024"


def still_fighting(engine: Any, actor: Any) -> bool:
    """Whether the creature counts as a fighter on its side right now.

    New-rule fights: awake and able, or able to come back by itself. Legacy
    fights: the engine has not marked it out of the fight. See the module
    docstring for why a life state alone cannot defeat a legacy side.
    """
    if not uses_new_dying_rules(engine):
        return bool(actor.active)
    return can_act(actor) or recovers_alone(engine, actor)


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
    if not any(actor.primary_combatant for actor in state.actors.values()):
        return None
    # A companion may remain on its original side after its owner changes sides.
    teams = {actor.team_id for actor in state.actors.values()}
    team_actors = {team: [actor for actor in state.actors.values() if actor.team_id == team] for team in teams}
    live = {team for team, rows in team_actors.items() if any(still_fighting(engine, actor) for actor in rows)}
    contenders = sorted(live)
    from .relations import ENEMY, enabled, relation
    if enabled(engine):
        # Hostility is between creatures still able to participate, not every
        # primary on a surviving team. Summons can keep their side fighting too.
        remaining = [actor for actor in state.actors.values()
                     if actor.team_id in contenders and still_fighting(engine, actor)]
        if any(relation(engine, a, b) == ENEMY for a in remaining for b in remaining):
            return None
        fighters = [a for a in remaining if any(relation(engine, a, b) == ENEMY for b in state.actors.values())]
        if fighters:
            winners = {a.team_id for a in fighters}
            return (TerminalKind.VICTORY, next(iter(winners)) if len(winners) == 1 else None,
                    'All opposing combatants are down and cannot recover.')
        return TerminalKind.DRAW_SIMULTANEOUS, None, 'No opposing primary combatants remain.'
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
