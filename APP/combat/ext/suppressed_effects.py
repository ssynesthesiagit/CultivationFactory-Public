"""Shared suppression lifetimes for Radiance, Destruction and Disease.

Convert relative engine tokens to absolute counted clocks before hiding an effect.
Concentration is bound to its original cast, including held copies, never a later
cast of the same technique. Kept models and deadlines contain only JSON values.
"""
from typing import Any
from .effect_durations import due, token, parse, skipped_expiry_slots, expiry_key
from . import hook

_HIDDEN = "hidden_expiry_round_skipped:"


def saved_lifetime(holder: Any, marker: Any) -> dict[str, Any]:
    """Read/retire a hidden original's runtime clock for Spirit and benefit suppression."""
    key = _HIDDEN + marker.instance_id
    clock = (marker.data or {}).get("lifetime") or {}
    return {**clock,
            "skipped": int(clock.get("skipped", 0)) + int(holder.turn_flags.pop(key, 0)),
            "expired": int(holder.turn_flags.pop(key + ":expired", 0))}


@hook("nominal_slot_boundary", priority=-100)
def nominal_hidden_lifetimes(engine: Any, actor: Any, checkpoint: str) -> None:
    """Advance only captured lifetime records; never restore or activate gameplay."""
    for holder in engine.state.actors.values():
        for marker in holder.conditions.values():
            clock = (marker.data or {}).get("lifetime")
            if not isinstance(clock, dict):
                continue
            parsed = parse(clock.get("expiry"))
            if parsed is None or parsed[1] != actor.entity_id:
                continue
            key = _HIDDEN + marker.instance_id
            if checkpoint == "START_OF_TURN":
                holder.turn_flags[key] = int(holder.turn_flags.get(key, 0)) + 1
            skipped = int(clock.get("skipped", 0)) + int(holder.turn_flags.get(key, 0))
            if due(engine, clock.get("expiry"), actor.entity_id if checkpoint == "END_OF_TURN" else None,
                   skipped=skipped):
                holder.turn_flags[key + ":expired"] = 1


def lifetime(engine: Any, holder: Any, effect: Any) -> dict[str, Any]:
    expiry = str(effect.expires_on or "")
    source = engine.state.actors.get(effect.source_actor_id or "")
    if expiry == "START_OF_SOURCE_NEXT_TURN" and source is not None:
        expiry = token("start", source.entity_id, int(source.turns_started) + 1)
    elif expiry in ("START_OF_SELF_NEXT_TURN", "START_OF_TARGET_NEXT_TURN"):
        expiry = token("start", holder.entity_id, int(holder.turns_started) + 1)
    elif expiry == "END_OF_CURRENT_TURN":
        current = engine.state.actors.get(engine.state.current_actor_id)
        if current is not None:
            expiry = token("end", current.entity_id, int(current.turns_started))
    elif expiry == "END_OF_HOLDER_NEXT_TURN":
        turn = int(holder.turns_started) + (engine.state.current_actor_id != holder.entity_id)
        expiry = token("end", holder.entity_id, turn)
    elif expiry.startswith("END_OF_SOURCE_TURN_AT:") and source is not None:
        expiry = token("end", source.entity_id, int(expiry.rsplit(":", 1)[-1]))
    bound = 0
    if expiry == "CONCENTRATION_END" and source is not None:
        from ..concentration import held, made_at
        casts = [c for _, c in held(source)] + ([source.concentration] if source.concentration else [])
        sequence = made_at(getattr(effect, "instance_id", None) or getattr(effect, "modifier_id", ""), effect)
        casts = [c for c in casts if c.source_definition_id == effect.source_definition_id
                 and (sequence is None or int(c.started_sequence) <= sequence)]
        if casts:
            bound = max(int(c.started_sequence) for c in casts)
    skipped = skipped_expiry_slots(holder, effect)
    return {"expiry": expiry, "cast": bound, "source_actor_id": effect.source_actor_id or "",
            "source": effect.source_definition_id, **({"skipped": skipped} if skipped else {})}


def alive(engine: Any, clock: dict[str, Any]) -> bool:
    if clock.get("expired"):
        return False
    expiry = clock.get("expiry")
    if expiry == "CONCENTRATION_END":
        from ..concentration import held
        source = engine.state.actors.get(clock.get("source_actor_id"))
        if source is None or not source.active:
            return False
        casts = [c for _, c in held(source)] + ([source.concentration] if source.concentration else [])
        return any(c.source_definition_id == clock.get("source") and int(c.started_sequence) == int(clock.get("cast") or 0)
                   for c in casts)
    return not due(engine, expiry, skipped=int(clock.get("skipped", 0)))


def restore(engine: Any, holder: Any, document: dict[str, Any], clock: dict[str, Any], *, modifier: bool = False) -> None:
    """Restore original provenance/lifetime; explicit source flags may survive inactivity."""
    persists = (document.get("data") or {}).get("persists_while_inactive") == 1
    if (not holder.active and not persists) or not alive(engine, clock):
        return
    from ..gate2_runtime_models import ConditionInstance, ModifierInstance
    model = (ModifierInstance if modifier else ConditionInstance).model_validate(document)
    model.expires_on = clock.get("expiry") or model.expires_on
    if clock.get("skipped"):
        holder.turn_flags[expiry_key(model)] = int(clock["skipped"])
    if modifier:
        holder.modifiers[model.modifier_id] = model
    else:
        holder.conditions[model.instance_id] = model
    from .retained_updates import record_instance_update

    record_instance_update(engine, holder, "modifier" if modifier else "condition",
                           model.modifier_id if modifier else model.instance_id, model)
