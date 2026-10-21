"""Thorn-Flesh Armory's delayed, refreshing Bleeding record.

``thorn_bleeding`` stores the source PB, chosen Piercing/Slashing type and
cumulative willing movement. MOVEMENT_COMMITTED counts physical path distance,
excluding forced movement, teleportation and carrying. ``attack_resolved``
consumes it after a typed attack, hit or miss. Legacy attacks are recognized
by ATTACK_ROLLED and consume it on a rolled miss or their committed damage.
The action_completed hook catches a legacy hit negated before damage.
The record is removed before its packet to prevent nested responses firing it
twice. Native state_event delivers movement after its commit and supports the
normal nested damage/reaction path. Multiple sources retain their own clocks,
but a trigger consumes them together and deals only the largest PB packet
(latest application breaks ties), never stacked damage or a GM placeholder.
"""
from __future__ import annotations

from . import effect, hook

BLEEDING = "condition:typed.bleeding"


def _held(actor):
    return [(key, c) for key, c in actor.conditions.items()
            if c.condition_id == BLEEDING and (c.data or {}).get("thorn_bleeding") and not c.data.get("suppressed")]


def _remove(engine, actor, key, condition):
    engine._remove_condition_instance(actor, key, condition.source_definition_id)


def _supernatural_immunity(engine, target):
    """Ordinary wound immunity is not immunity to this supernatural Body state.

    Inspect the actual immunity's Source Rule, not the creature's anatomy or
    the fact that another provider happens to use the word 'bleeding'. Unknown
    ordinary immunity supplies no expanded supernatural permission. Explicit
    supernatural-bleeding immunity retains the normal native query.
    """
    import re
    from ..typed_executor import condition_immune
    from ..rule_help import printed_rule_text
    from .ability_source import mechanic_at
    if condition_immune(engine, target, "supernatural_bleeding"):
        return True
    sources = [m.source_definition_id for m in target.modifiers.values()
               if m.target_field == "condition_immunity" and str(m.value).lower() == "bleeding"]
    sources += [r.get("feature_id", "") for r in
                (getattr(engine, "typed_passive_rows", {}) or {}).get(target.entity_id, [])
                if "bleeding" in (r.get("conditions") or r.get("condition_immunities") or [])]
    for condition in target.conditions.values():
        if "bleeding" in (condition.data.get("rule", {}).get("condition_immunities") or []):
            sources.append(condition.source_definition_id)
    for source in sources:
        text = printed_rule_text(mechanic_at(engine, source) or source)
        for clause in re.split(r"[.\n]", text):
            lower = clause.lower()
            if "immun" in lower and "bleeding" in lower and ("ordinary" not in lower or "supernatural" in lower):
                return True
    return False


@effect("thorn_bleeding")
def apply(ctx, row):
    from .. import typed_executor

    for target in typed_executor._default_subject(ctx, row, harmful=True):
        if not target.active or _supernatural_immunity(ctx.engine, target):
            continue
        # Preserve native source-sensitive prevention/consent without applying
        # the unrelated generic ordinary-bleeding immunity a second time.
        from . import run_checkpoint, CheckpointError
        replies = run_checkpoint("condition_application_attempt", ctx.engine, target, BLEEDING, ctx.source, ctx.actor.entity_id)
        if any(type(reply) is not bool for reply in replies):
            raise CheckpointError("condition_application_attempt must return bool or None")
        if any(reply is False for reply in replies):
            continue
        for key, old in _held(target):
            if old.source_actor_id == ctx.actor.entity_id:
                _remove(ctx.engine, target, key, old)
        ctx.engine._apply_condition(target, BLEEDING, ctx.source, ctx.actor.entity_id,
            expires_on=typed_executor.effect_expiry(ctx, row, target, condition=True),
            data={"thorn_bleeding": {"pb": int(ctx.numbers["pb"]), "damage_type": str(row["damage_type"]).upper(), "moved_ft": 0},
                  "supernatural_body": 1,
                  "source_cl": int(ctx.numbers.get("cl", 0)),
                  "label": f"Thorn-Flesh Armory Bleeding: after your next attack (even a miss) or 10 feet of willing movement, "
                           f"take {int(ctx.numbers['pb'])} {str(row['damage_type']).title()} damage once. "
                           f"Ends when {ctx.actor.display_name}'s next turn starts."}, unavoidable=True)


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
    """End exact triggered records; overlapping casters never add damage."""
    if not records:
        return
    # A suppressed source's existing state is dormant, not spent or refunded.
    from .black_thorn_demon_body import body_numbers
    live = []
    for key, condition in records:
        owner = engine.state.actors.get(condition.source_actor_id)
        numbers = body_numbers(engine, owner) if owner is not None else {}
        if numbers and int(numbers.get("cl", 0)) < 3:
            continue
        live.append((key, condition))
    if not live:
        return
    chosen = max(live, key=lambda item: (int(item[1].data["thorn_bleeding"]["pb"]), item[1].applied_sequence))
    for key, condition in live:
        if key != chosen[0]:
            _remove(engine, actor, key, condition)
    _pulse(engine, actor, *chosen)


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
def committed_event(engine, event):
    committed(engine, event.event_type, {"actor_id": event.actor_id, "payload": event.payload,
                                        "source_definition_id": event.source_definition_id})


def committed(engine, event_type, kwargs):
    if event_type not in ("MOVEMENT_COMMITTED", "ATTACK_ROLLED", "ATTACK_MISSED", "DAMAGE_COMMITTED"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None or not actor.active:
        return
    payload = kwargs.get("payload") or {}
    if event_type == "MOVEMENT_COMMITTED":
        if payload.get("forced") or payload.get("teleport") or payload.get("carried_by") or payload.get("fall_distance_ft"):
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
        source = kwargs.get("source_definition_id") or engine.events[-1].source_definition_id
        triggered = []
        for key, condition in _held(actor):
            rule = {**condition.data["thorn_bleeding"]}
            if event_type == "ATTACK_ROLLED":
                # A provisional roll has not committed even a missed attack.
                # Wait for ATTACK_MISSED, damage, or completed negated action.
                rule["attack_source"] = source
                _update(engine, actor, key, condition, rule)
            elif rule.get("attack_source") == source:
                triggered.append((key, condition))
        _trigger(engine, actor, triggered)
