"""Modifiers that last as long as a Concentration technique come off when it ends (expiry-clock fix 2026-09-28: effects stamped
CONCENTRATION_END were removed for conditions only, so a "+2 AC while you concentrate" or a stat penalty stayed on the target
for the rest of the fight).

The sealed engine's _end_concentration (gate2) takes off the CONCENTRATION_END *conditions* and then emits
CONCENTRATION_ENDED; it never looks at ``modifiers``. This hook takes the same step for them, with the same kind of event
(MODIFIER_REMOVED, reason as the ending's). The ones a fighter holds beside its current technique end through
combat/concentration.py end_held, which calls the same helper.

Replays derive the same result: it reads only the ended technique's id and the start of the ended copy (started_sequence)
off the CONCENTRATION_ENDED event and the modifiers that are filed with that id, and stores nothing. A technique held more
than once (owner ruling 2026-09-29) loses only the modifiers its ended copy made (combat/concentration.py); one held once
loses them all. A Lingering Conflagration handover (zone_persists) is not an ending of the technique's own effects, so it
is left alone; "REPLACED" (the one held longest, at the limit) ends before the new technique's modifiers exist (gate2
_start_concentration runs before the effects), so those are never touched.
"""

from __future__ import annotations

from typing import Any

from . import hook


@hook("event")
def concentration_ended(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONCENTRATION_ENDED":
        return
    event = engine.events[-1]
    payload = kwargs.get("payload") or {}
    if payload.get("zone_persists") or not event.source_definition_id:
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or event.actor_id)
    if actor is None:
        return
    from .. import concentration

    started = payload.get("started_sequence")
    concentration.end_modifiers(engine, actor, str(event.source_definition_id), str(payload.get("reason") or "CONCENTRATION_ENDED"),
                                int(started) if started is not None else None)
