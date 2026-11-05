"""Queue player-owned Ask-me reactions from Initiative for the first table transaction.

The constructor has no manual controller provider. This general adapter uses the
existing fight-setup queue so every Initiative reaction row can ask before it spends.
"""

from typing import Any

from . import hook


@hook("fight_setup_tasks")
def ask_initiative_tasks(engine: Any) -> list[dict[str, str]] | None:
    tasks = []
    control_modes = getattr(engine, "_roster_setup", {}).get("participant_control_modes", {})
    for actor_id, rows in sorted((getattr(engine, "typed_reaction_rows", {}) or {}).items()):
        sources = sorted({str(row.get("feature_id") or "") for row in rows
                          if row.get("block") == "generic" and row.get("kind") == "initiative"
                          and row.get("ask") and not row.get("held_back")
                          and not row.get("free") and row.get("feature_id")})
        if sources and control_modes.get(actor_id, "MANUAL") in {"MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"}:
            # One setup task runs this actor's complete Initiative checkpoint, including
            # automatic rows and any further Ask-me rows, exactly once.
            tasks.append({"actor_id": actor_id, "source_id": sources[0]})
    return tasks or None


@hook("fight_setup")
def resolve_ask_initiative(engine: Any, actor: Any, source_id: str, intent: Any) -> bool | None:
    rows = (getattr(engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, ())
    if not any(row.get("block") == "generic" and row.get("kind") == "initiative"
               and row.get("ask") and not row.get("free") and row.get("feature_id") == source_id for row in rows):
        return None
    from .. import typed_reactions

    if actor.turn_flags.get("once_per_turn:_round_initiative_checkpoint_handled") is None:
        turns_started = int(actor.turns_started)
        actor.turn_flags["once_per_turn:_round_initiative_checkpoint_handled"] = turns_started
        engine._append_event("ONCE_PER_TURN_CLAIMED", "system:combat.initiative", actor_id=actor.entity_id,
                             payload={"scope": "_round_initiative_checkpoint_handled",
                                      "turns_started": turns_started})
    typed_reactions.on_own_event(engine, actor, None, "initiative")
    return True
