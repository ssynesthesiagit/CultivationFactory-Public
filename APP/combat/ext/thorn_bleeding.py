"""Thorn-Flesh Armory's delayed, refreshing Bleeding record.

``thorn_bleeding`` stores the source PB, chosen Piercing/Slashing type and
cumulative willing movement. MOVEMENT_COMMITTED counts physical path distance,
excluding forced movement, teleportation and carrying. ``attack_resolved``
consumes it after a typed attack, hit or miss. Legacy attacks are recognized
by ATTACK_ROLLED and consume it on a rolled miss or their committed damage.
The action_completed hook catches a legacy hit negated before damage.
The record is removed before its packet to prevent nested responses firing it
twice. Event-hook packets remain GM instructions until the locked event
dispatcher supports downstream riders for nested damage. Typed attack completion
and legacy action completion outside that hook still resolve normally.
"""
from __future__ import annotations

from . import effect, hook

BLEEDING = "condition:typed.bleeding"


def _held(actor):
    return [(key, c) for key, c in actor.conditions.items()
            if c.condition_id == BLEEDING and (c.data or {}).get("thorn_bleeding")]


def _remove(engine, actor, key, condition):
    del actor.conditions[key]
    engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=actor.entity_id,
                        target_ids=(actor.entity_id,), payload={"condition_id": BLEEDING, "instance_id": key})


@effect("thorn_bleeding")
def apply(ctx, row):
    from .. import typed_executor

    for target in typed_executor._default_subject(ctx, row, harmful=True):
        if not target.active or typed_executor.condition_immune(ctx.engine, target, "bleeding"):
            continue
        for key, old in _held(target):
            if old.source_actor_id == ctx.actor.entity_id:
                _remove(ctx.engine, target, key, old)
        ctx.engine._apply_condition(target, BLEEDING, ctx.source, ctx.actor.entity_id,
            expires_on=typed_executor.effect_expiry(ctx, row, target, condition=True),
            data={"thorn_bleeding": {"pb": int(ctx.numbers["pb"]), "damage_type": str(row["damage_type"]).upper(), "moved_ft": 0},
                  "label": "Bleeding: first 10 feet of willing movement or next attack deals PB damage"})


def _update(engine, actor, key, condition, rule):
    from .effect_durations import apply_condition_preserving_clock
    data = {**condition.data, "thorn_bleeding": rule}
    _remove(engine, actor, key, condition)
    apply_condition_preserving_clock(engine, actor, condition, BLEEDING, condition.source_definition_id, condition.source_actor_id,
                            expires_on=condition.expires_on, data=data)


def _pulse(engine, actor, key, condition):
    rule = condition.data["thorn_bleeding"]
    _remove(engine, actor, key, condition)
    if getattr(engine, "_ext_in_event", False):
        engine._append_event("GM_RIDER", condition.source_definition_id, actor_id=condition.source_actor_id,
            target_ids=(actor.entity_id,), payload={"rider": f"Thorn-Flesh Armory: after {actor.display_name}'s "
                f"triggering movement or attack commits, apply {int(rule['pb'])} {str(rule['damage_type']).title()} "
                "damage and resolve its damage riders. Bleeding ended; this packet needs GM resolution "
                "until lock round 3 supports nested event damage."})
        return
    previous = getattr(engine, "_typed_pending_damage_type", None)
    previous_packet = getattr(engine, "_typed_damage_packet", None)
    engine._typed_damage_packet = None
    engine._typed_pending_damage_type = str(rule["damage_type"])
    try:
        engine._commit_damage(actor, int(rule["pb"]), str(rule["damage_type"]), condition.source_definition_id,
                              condition.source_actor_id, getattr(engine, "_active_intent", None), reaction_depth=1)
    finally:
        engine._typed_pending_damage_type = previous
        engine._typed_damage_packet = previous_packet


def _trigger(engine, actor, records):
    """End exact triggered records; overlapping casters never add damage."""
    if len(records) > 1:
        packets = []
        for key, condition in records:
            rule = condition.data["thorn_bleeding"]
            source = engine.state.actors.get(condition.source_actor_id)
            packets.append(f"{source.display_name if source else condition.source_actor_id}: "
                           f"{int(rule['pb'])} {str(rule['damage_type']).title()}")
            _remove(engine, actor, key, condition)
        engine._append_event("GM_RIDER", records[-1][1].source_definition_id,
            actor_id=records[-1][1].source_actor_id, target_ids=(actor.entity_id,),
            payload={"rider": f"Thorn-Flesh Armory: {actor.display_name}'s movement or attack triggered "
                "overlapping casters' Bleeding. Resolve one nonstacking delayed packet, including downstream "
                "riders, from these source records: " + "; ".join(packets) + ". Triggered records ended; "
                "caster precedence/refresh is GM-adjudicated, no damage was silently added."})
    elif records:
        _pulse(engine, actor, *records[0])


@hook("attack_resolved")
def after_attack(ctx, target, hit, attack):
    _trigger(ctx.engine, ctx.actor, _held(ctx.actor))


@hook("action_completed")
def after_legacy_action(engine, actor, economy, source):
    if actor.entity_id in getattr(engine, "typed_actor_ids", set()):
        return
    _trigger(engine, actor, [(key, condition) for key, condition in _held(actor)
        if condition.data["thorn_bleeding"].get("attack_source") == source])


@hook("event")
def committed(engine, event_type, kwargs):
    if event_type not in ("MOVEMENT_COMMITTED", "ATTACK_ROLLED", "ATTACK_MISSED", "DAMAGE_COMMITTED"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None or not actor.active:
        return
    payload = kwargs.get("payload") or {}
    if event_type == "MOVEMENT_COMMITTED":
        if payload.get("forced") or payload.get("teleport") or payload.get("carried_by"):
            return
        from ..gate2_runtime_models import Position
        path = [Position.model_validate(cell) for cell in payload.get("path") or []]
        distance = sum(int(engine.grid.distance_ft(a, b)) for a, b in zip(path, path[1:]))
        triggered = []
        for key, condition in _held(actor):
            rule = {**condition.data["thorn_bleeding"]}
            rule["moved_ft"] += distance
            if rule["moved_ft"] >= 10:
                triggered.append((key, condition))
            elif distance:
                _update(engine, actor, key, condition, rule)
        _trigger(engine, actor, triggered)
    elif actor.entity_id not in getattr(engine, "typed_actor_ids", set()):
        source = engine.events[-1].source_definition_id
        triggered = []
        for key, condition in _held(actor):
            rule = {**condition.data["thorn_bleeding"]}
            if event_type == "ATTACK_ROLLED":
                if payload.get("provisional_hit") is False:
                    triggered.append((key, condition))
                else:
                    rule["attack_source"] = source
                    _update(engine, actor, key, condition, rule)
            elif rule.get("attack_source") == source:
                triggered.append((key, condition))
        _trigger(engine, actor, triggered)
