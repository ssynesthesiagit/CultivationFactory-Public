"""One synchronous ending checkpoint for native and extension effect lifetimes.

All recorded removals and summon departures use ``dispatch`` on Gate2,
including its Gate3/Gate4 subclasses. Deadlines, manual removal and nested
dependent cleanup therefore notify the same event subscribers. Event/reducer
schemas stay unchanged.

``remove_instance`` is the exact-instance mutation seam. ``ended_effect`` is a
detached snapshot supplied to live subscribers only; it identifies the original
source when the recorded removal is attributed to an expiry system or a turn
boundary. Recorded replay applies events without invoking these subscribers.
"""
from __future__ import annotations

from typing import Any

ENDING_EVENTS = frozenset({
    "CONDITION_REMOVED", "MODIFIER_REMOVED", "ZONE_REMOVED",
    "CONCENTRATION_ENDED", "SUMMON_DISMISSED",
})
MAX_ENDING_DEPTH = 64
_ORIGINAL_ACTOR = object()


def is_ending_event(engine: Any, event: Any) -> bool:
    """Defeat ends a summon's lifetime without changing its recorded identity.

    Ordinary actor defeats retain their existing observational delivery. A
    destroyed summon uses the same strict cleanup as a dismissed summon while
    keeping its ``ENTITY_DEFEATED`` event and ``destroyed`` status.
    """
    if event.event_type in ENDING_EVENTS:
        return True
    if event.event_type != "ENTITY_DEFEATED":
        return False
    creature = engine.state.actors.get(event.actor_id)
    return creature is not None and creature.summon is not None


def _checkpoint(function: Any, *args: Any) -> Any:
    """A failed cleanup must unwind even through an observational turn hook."""
    from .ext import CheckpointError

    try:
        return function(*args)
    except CheckpointError:
        raise
    except Exception as exc:
        raise CheckpointError(f"Effect ending failed: {exc}") from exc


def remove_instance(engine: Any, holder: Any, kind: str, key: str, source: str, *,
                    actor_id: Any = _ORIGINAL_ACTOR, payload: dict[str, Any] | None = None,
                    expected: Any = None, expiring: bool = False, before_event: Any = None) -> bool:
    """Remove one live instance once, then synchronously finish its subscribers.

    ``expected`` prevents a snapshot sweep from removing a replacement. Only
    deadline callers set ``expiring``: both native and extension clocks offer
    the same strict expiry choice/aftermath hooks before committing the removal.
    A hook that removes/replaces the instance or changes its expiry retains its
    result. Manual removals use the same post-removal subscribers, without an
    opportunity to extend a lifetime that is being dispelled or consumed.
    """
    if kind not in {"condition", "modifier"}:
        raise ValueError(f"Unknown effect instance kind: {kind}")
    rows = holder.conditions if kind == "condition" else holder.modifiers
    row = rows.get(key)
    if row is None or (expected is not None and row is not expected):
        return False
    from . import ext
    if any(value is False for value in ext.run_strict("effect_removal_allowed", engine, holder, kind, row, source)):
        return False
    if rows.get(key) is not row:
        return False  # an interceptor replaced the instance with a retained remainder
    if expiring:
        from . import ext

        pending = engine.__dict__.setdefault("_expiring_effect_instances", set())
        identity = (id(holder), kind, key, id(row))
        if identity in pending:
            return False
        pending.add(identity)
        expiry = row.expires_on
        try:
            for point in ("effect_expiring_choice", "effect_expiring"):
                for subscriber in ext.subscribers(point):
                    _checkpoint(subscriber, engine, holder, row)
                    if rows.get(key) is not row or row.expires_on != expiry:
                        return False
        finally:
            pending.discard(identity)
    # Mandatory handover finishes while outgoing support still exists: removal
    # events can immediately settle falling or damage.
    from . import ext
    pending = engine.__dict__.setdefault('_ending_effect_instances', set())
    identity = (id(holder), kind, key, id(row))
    if identity not in pending:
        pending.add(identity)
        try:
            for subscriber in ext.subscribers('effect_ending_choice'):
                _checkpoint(subscriber, engine, holder, row)
                if rows.get(key) is not row:
                    return False
        finally:
            pending.discard(identity)
    # Capture provenance before callbacks can alter or replace retained rows.
    ended_effect = row.model_dump(mode="json")
    del rows[key]
    from .ext.effect_durations import expiry_key

    holder.turn_flags.pop(expiry_key(row), None)
    if before_event is not None:
        _checkpoint(before_event)
    if payload is None:
        payload = {"instance_id": key, "condition_id": row.condition_id} if kind == "condition" else {"modifier_id": key}
    if kind == "condition" and row.data.get("retain_removal_data"):
        payload = {**payload, "removed_condition": ended_effect}
    engine._append_event(
        "CONDITION_REMOVED" if kind == "condition" else "MODIFIER_REMOVED", source,
        actor_id=row.source_actor_id if actor_id is _ORIGINAL_ACTOR else actor_id,
        target_ids=(holder.entity_id,), payload=payload, _ended_effect=ended_effect,
    )
    if kind == "condition":
        engine._reconcile_reaction_after_condition_removal(holder, [row])
    return True


def dispatch(engine: Any, event: Any, ended_effect: dict[str, Any] | None = None) -> None:
    """Deliver a recorded ending once, including inside another event/turn hook.

    Subscribers run in their registered priority order, ties in registration
    order; the snapshot is fixed before delivery. Nested endings finish depth
    first before their parent resumes. The exact recorded event and detached
    instance provenance survive any nested log writes. Exceptions and player
    pauses propagate for transaction rollback; an excessive cascade fails the
    action instead of committing with some subscribers silently skipped.

    Ending depth is independent of Gate4's ordinary nested-observation limit.
    Non-ending events emitted by a subscriber retain their nested-only policy.
    """
    if not is_ending_event(engine, event):
        return
    from . import ext

    depth = getattr(engine, "_effect_ending_depth", 0)
    if depth >= MAX_ENDING_DEPTH:
        raise ext.CheckpointError("An effect ending repeated too many times; the action was cancelled.")
    ordinary_depth = getattr(engine, "_ext_event_depth", 0)
    in_event = getattr(engine, "_ext_in_event", False)
    previous_event = getattr(engine, "_ext_recorded_event", None)
    engine._effect_ending_depth = depth + 1
    engine._ext_event_depth = max(1, ordinary_depth)
    engine._ext_in_event = True
    try:
        payload = dict(event.payload or {})
        if ended_effect is not None and "condition_id" in ended_effect:
            payload.setdefault("condition_id", ended_effect["condition_id"])
        kwargs = {"actor_id": event.actor_id, "target_ids": event.target_ids,
                  "source_definition_id": event.source_definition_id,
                  "payload": payload, "originating_event": event,
                  "ended_effect": ended_effect}
        for subscriber in ext.subscribers("event"):
            # Older observers may use the shared identity seam. Reset it for
            # every subscriber as children can have emitted their own events.
            ext.remember_recorded_event(engine, event)
            _checkpoint(subscriber, engine, event.event_type, kwargs)
        _checkpoint(_finish_dependents, engine, event)
    finally:
        engine._effect_ending_depth = depth
        engine._ext_event_depth = ordinary_depth
        engine._ext_in_event = in_event
        engine._ext_recorded_event = previous_event


def _finish_dependents(engine: Any, event: Any) -> None:
    """Native area membership and summon ownership share the ending boundary."""
    if event.event_type == "ZONE_REMOVED":
        from . import zones

        zones.on_zone_removed(engine, str((event.payload or {}).get("zone_id") or ""))
        zones.sync_walls(engine)
        zones.sync_inside(engine, event.source_definition_id)
    elif event.event_type in {"SUMMON_DISMISSED", "ENTITY_DEFEATED"}:
        from . import concentration, zones

        creature = engine.state.actors.get(event.actor_id)
        if creature is None:
            return
        reason = str((event.payload or {}).get("reason") or event.event_type)
        concentration.end_all_copies(engine, creature, reason)
        for zone in list(engine.state.zones.values()):
            profile = zone.trigger_profile
            if zone.active and zone.owner_id == creature.entity_id and (
                    profile.get("ends_with_owner") or profile.get("follows_owner")):
                zones.remove(engine, zone, reason)
        # Derived aura zones are no longer supplied once their owner leaves;
        # remove their persisted inside effects at this same boundary.
        zones.sync_inside(engine, event.source_definition_id, removals_only=True)
    elif event.event_type in {"CONDITION_REMOVED", "MODIFIER_REMOVED", "CONCENTRATION_ENDED"}:
        from . import zones

        # An aura supplied by a pure provider can disappear when its enabling
        # effect ends, without ever having a stored ZoneState to remove. This
        # only prunes obsolete membership: recreating a still-valid but missing
        # effect here would immediately undo intentional suppression/removal.
        zones.sync_inside(engine, event.source_definition_id, removals_only=True)
