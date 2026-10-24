"""Migrate saved deferred-hit spending for the shared typed executor.

The old modifier-instance flag has no turn identity. Its first event after
reload anchors it to the current turn, before hits, refreshes or turn advancement.
Only actors carrying that legacy flag and its live modifier are changed.
"""
from __future__ import annotations

from typing import Any

from . import hook


@hook("event")
def migrate_spent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    current = engine.state.actors[engine.state.current_actor_id]
    turn = f"{engine.state.round_number}:{engine.state.current_slot_index}:{current.entity_id}:{current.turns_started}"
    for actor in engine.state.actors.values():
        for legacy, spent in list(actor.turn_flags.items()):
            if not legacy.startswith("typed_on_hit:") or not spent:
                continue
            modifier = actor.modifiers.get(legacy.removeprefix("typed_on_hit:"))
            if modifier is None or modifier.target_field != "typed_on_hit":
                continue
            parts = str(modifier.value).split("|", 2)
            if len(parts) < 2:
                continue
            evidence = parts[1]
            key = f"_round_typed_on_hit:{modifier.source_definition_id}:{evidence}"
            actor.turn_flags[key] = turn
            del actor.turn_flags[legacy]
