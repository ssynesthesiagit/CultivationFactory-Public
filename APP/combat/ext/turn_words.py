"""Shared plain words for when a turn-bounded effect ends.

Consumers: ``approach_lock.py`` (Held at distance) and ``resistance_bypass.py`` (an ignored
Resistance).  Both put a condition on a creature and must tell the player in the condition pill and
in the refusal how long it lasts, in the words the printed rule uses ("until the start of Mo Ruo's
next turn") rather than an expiry name from the engine.

``until_words`` reads the expiry name the executor already resolved, so the sentence and the real
expiry cannot disagree.  It returns "" for an expiry that is not a turn edge (a round clock, the end
of the fight, "until removed"), and the caller then leaves the length out rather than guess.
"""

from __future__ import annotations

from typing import Any

#: The engine's own names for a turn edge, and whose turn it names.
_FILED_UNDER_ACTOR = {"START_OF_SOURCE_NEXT_TURN": "start"}
_FILED_UNDER_HOLDER = {"END_OF_HOLDER_NEXT_TURN": "end"}


def until_words(engine: Any, expires_on: Any, *, actor: Any = None, holder: Any = None) -> str:
    """"until the start of Mo Ruo's next turn" for one expiry name, or "" when it names no turn.

    ``actor`` is the creature whose turn the ability's wording counts from ("your next turn"), and
    ``holder`` the creature the condition sits on.  Neither is read from the name except where the
    name carries an actor id, so a saved name stays readable after a reload.
    """
    name = str(expires_on or "")
    if name == "END_OF_CURRENT_TURN":
        return "until the end of this turn"
    if name in _FILED_UNDER_ACTOR:
        return _words("start", actor)
    if name in _FILED_UNDER_HOLDER:
        return _words("end", holder or actor)
    if name.startswith("END_OF_SOURCE_TURN_AT:"):
        return _words("end", actor)
    from . import effect_durations

    parsed = effect_durations.parse(name)
    if parsed is None:
        return ""
    edge, actor_id, _turn = parsed
    named = (holder if holder is not None and holder.entity_id == actor_id
             else actor if actor is not None and actor.entity_id == actor_id
             else (engine.state.actors.get(actor_id) if engine is not None else None))
    return _words(edge, named)


def _words(edge: str, who: Any) -> str:
    name = str(getattr(who, "display_name", "") or "")
    return f"until the {'start' if edge == 'start' else 'end'} of {name}'s next turn" if name else ""