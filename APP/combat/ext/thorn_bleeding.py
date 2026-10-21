"""Thorn-Flesh Armory's delayed, refreshing Bleeding record.

``thorn_bleeding`` stores the source PB, chosen Piercing/Slashing type and
cumulative willing movement. Committed-step receipts count physical path distance,
excluding forced movement, teleportation and carrying. ``attack_resolved``
consumes it after a typed attack, hit or miss. Legacy attacks are recognized
by ATTACK_ROLLED and consume it on a rolled miss or their committed damage.
The action_completed hook catches a legacy hit negated before damage.
The record is removed before its packet to prevent nested responses firing it
twice. The strict native state_event checkpoint settles committed movement and
legacy attack packets through the normal damage/defense pipeline; player-choice
pauses roll back the enclosing transaction. Every new family application
refreshes the one supernatural record, independently of ordinary bleeding.
"""
from __future__ import annotations

from . import effect, hook

# A supernatural Body condition is not the ordinary bleeding immunity category.
BLEEDING = "condition:typed.thorn_bleeding"


def _held(actor):
    return [(key, c) for key, c in actor.conditions.items()
            if c.condition_id == BLEEDING and (c.data or {}).get("thorn_bleeding")]


def _remove(engine, actor, key, condition):
    engine._remove_condition_instance(actor, key, condition.source_definition_id)


@effect("thorn_bleeding")
def apply(ctx, row):
    from .. import typed_executor

    for target in typed_executor._default_subject(ctx, row, harmful=True):
        if not target.active or typed_executor.condition_immune(ctx.engine, target, "thorn_bleeding"):
            continue
        for key, old in _held(target):
            _remove(ctx.engine, target, key, old)
        ctx.engine._apply_condition(target, BLEEDING, ctx.source, ctx.actor.entity_id,
            expires_on=typed_executor.effect_expiry(ctx, row, target, condition=True),
            data={"thorn_bleeding": {"pb": int(ctx.numbers["pb"]), "source_cl": int(ctx.numbers.get('cl') or 0),
                                    "damage_type": str(row["damage_type"]).upper(), "moved_ft": 0},
                  "label": f"Bleeding: {target.display_name}'s next attack or first 10 feet of willing movement deals "
                           f"{int(ctx.numbers['pb'])} {str(row['damage_type']).title()} damage, then ends; "
                           f"expires at the start of {ctx.actor.display_name}'s next turn"})


def _update(engine, actor, key, condition, rule):
    data = {**condition.data, "thorn_bleeding": rule}
    engine._update_condition_data(actor, condition, data, condition.source_definition_id)


def _pulse(engine, actor, key, condition):
    rule = condition.data["thorn_bleeding"]
    _remove(engine, actor, key, condition)
    previous = getattr(engine, "_typed_pending_damage_type", None)
    previous_packet = getattr(engine, "_typed_damage_packet", None)
    engine._typed_damage_packet = None
    engine._typed_pending_damage_type = str(rule["damage_type"])
    try:
        from .black_thorn_demon_body import spine_damage
        with spine_damage(engine, condition.source_actor_id):
            engine._commit_damage(actor, int(rule["pb"]), str(rule["damage_type"]), condition.source_definition_id,
                                  condition.source_actor_id, getattr(engine, "_active_intent", None), reaction_depth=1)
    finally:
        engine._typed_pending_damage_type = previous
        engine._typed_damage_packet = previous_packet


def _trigger(engine, actor, records):
    """New applications refresh the single record, so delayed damage never stacks."""
    if records:
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


@hook("state_event")
def committed(engine, event):
    event_type = event.event_type
    kwargs = {'actor_id': event.actor_id, 'payload': event.payload}
    if event_type not in ("ATTACK_ROLLED", "ATTACK_MISSED", "DAMAGE_COMMITTED"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None or not actor.active:
        return
    payload = kwargs.get("payload") or {}
    if actor.entity_id not in getattr(engine, "typed_actor_ids", set()):
        source = event.source_definition_id
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


@hook("movement_progress_committed")
def moved_step(engine, mover, receipt):
    """Count only actual willing steps committed while the record is present.

    Counting the final route would incorrectly include earlier movement when
    a Crown or an entry field applied Bleeding partway through that route.
    Forced landings, carried bodies and teleports never count as willing steps.
    """
    if not receipt.get('voluntary') or int(receipt.get('distance_ft') or 0) <= 0:
        return
    for key, condition in _held(mover):
        rule = {**condition.data['thorn_bleeding']}
        rule['moved_ft'] += int(receipt['distance_ft'])
        if rule['moved_ft'] >= 10:
            rule['owed'] = 1
        _update(engine, mover, key, condition, rule)


@hook("movement_step_settled", priority=-1000)
def settle_step(engine, mover, previous, destination, intent):
    """Settle owed damage before entered-space effects can refresh the record."""
    _trigger(engine, mover, [(key, condition) for key, condition in _held(mover)
                            if condition.data['thorn_bleeding'].get('owed')])
