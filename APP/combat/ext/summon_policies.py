"""Shared policies for summoned bodies: timed dismissal, owner choices and default travel.

Each handler requires data on the summoned actor, so unrelated actors and legacy
summons with no policy remain unchanged.
Duration conditions remain visible on the table. A persisted summon clock owns
new dismissal events; condition-driven dismissal is retained for legacy records
without that clock, so two expiry paths cannot dismiss the same creature.
"""

from __future__ import annotations

from typing import Any

from . import hook

DURATION_SOURCE = "system:combat.summon_duration"
DURATION_CONDITION = "condition:core.summon_duration"


@hook("status_description")
def describe_summon_duration(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    """Explain the internal duration marker in plain language on the table."""
    if row.get("source_definition_id") != DURATION_SOURCE:
        return None
    record = getattr(holder, "summon", None) or {}
    owner = engine.state.actors.get(record.get("owner") or "")
    owner_name = getattr(owner, "display_name", None) or "its summoner"
    group = str(record.get("group") or "")
    source = {"bone_guard": "Bone Guard Manifestation", "talisman_spirit": "Talisman Spirit"}.get(
        group.casefold(), group.replace("_", " ").title() or "Summoning")
    return {"source_ability": source,
            "rules": f"{source} summons this companion for 1 minute. It vanishes at the start of {owner_name}'s turn when that time ends."}


@hook("event", nested=True)
def record_summon_duration(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Attach configured rounds to an appeared summon through replayable condition events."""
    if event_type != "SUMMON_APPEARED":
        return
    for actor_id in kwargs.get("target_ids") or ():
        creature = engine.state.actors.get(actor_id)
        record = getattr(creature, "summon", None) or {}
        rounds = int(record.get("duration_rounds") or 0)
        if creature is None or rounds <= 0:
            continue
        from . import effect_durations

        engine._apply_condition(creature, DURATION_CONDITION, DURATION_SOURCE, record["owner"],
                                expires_on=effect_durations.round_token(engine, rounds))


@hook("effect_expiring")
def dismiss_expired_summon(engine: Any, holder: Any, row: Any) -> None:
    """A due duration removes its summoned body; dismissal is recorded in the event journal."""
    if getattr(row, "source_definition_id", None) != DURATION_SOURCE:
        return
    record = getattr(holder, "summon", None) or {}
    if record.get('expires_on'):
        return  # The persisted summon clock owns dismissal; this condition is its display marker.
    if record.get("status") == "present":
        from .. import summons

        summons._leave(engine, holder, "dismissed", "DURATION_ENDED")


@hook("uncommanded_summon_turn")
def default_companion_movement(engine: Any, actor: Any) -> None:
    """Follow a linked owner before Dodge when an uncommanded summon has a follow policy."""
    record = getattr(actor, "summon", None) or {}
    policy = record.get("default_movement") or {}
    owner = engine.state.actors.get(record.get("owner") or "")
    if (not policy or policy.get("kind") != "follow_owner" or owner is None or not owner.active or not actor.active
            or record.get("status") != "present" or record.get("commanded") or record.get("command") == "free"
            or record.get("mountable")):
        return
    from .companion_movement import move_toward_owner

    move_toward_owner(engine, actor, owner, int(policy.get("within_ft") or 0))
