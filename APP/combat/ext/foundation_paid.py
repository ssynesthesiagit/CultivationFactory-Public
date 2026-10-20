"""Public settled Foundation payment/value receipts.

Consumers: foundations3 Strike; Red Lotus Heart-Ash's paid-value rider can
subscribe to foundation_paid_value_bonus. Generation/Garden consumers use
qualifying_hit, which reads the same native pre-damage source/target snapshot.
Unknown sources remain unqualified; no sphere or display-name inference.
"""
from . import run_strict


def qualifying_hit(ctx, target, family):
    """Pure query of an actual native hit snapshot, never a staged damage offer."""
    receipt = (ctx.hit_snapshots or {}).get('foundation:' + family) or {}
    attack = ctx.attack_damage_context
    from ..relations import relation, ENEMY
    methods = hit_methods(ctx, target)
    aligned = receipt.get('alignment') == family or any(family in tags for tags in methods.values())
    return bool(attack and attack.target_id == target.entity_id
                and receipt.get('target') == target.entity_id
                and receipt.get('source') == ctx.action.source_definition_id
                and receipt.get('target_qualified', receipt.get('qualifies')) and aligned
                and target.current_hp < target.maximum_hp
                and relation(ctx.engine, ctx.actor, target) == ENEMY)


def record_hit_method(ctx, target, source):
    """Record a real completed on-hit method's reviewed source classifications.

    Called by Coated Weapon after its native damage/save effects. Source data
    comes from the sealed actual casting action; no sphere/name inference or
    fight-state mutation occurs. The roll and target bind the transient receipt.
    """
    from .source_eligibility import catalog_action
    attack = getattr(ctx, 'attack_damage_context', None)
    if attack is None or target is None or attack.target_id != target.entity_id:
        return
    action = catalog_action(ctx.engine, source)
    typed = action.parameters.get('typed') or {} if action else {}
    tags = typed.get('foundation_alignment') or []
    if not tags:
        return
    key = attack.roll_id + '|' + target.entity_id
    methods = ctx.damage_cache.setdefault('foundation:hit_methods', {})
    methods.setdefault(key, {})[source] = list(tags)


def hit_methods(ctx, target):
    """Pure read of this exact native hit's completed method receipts."""
    attack = ctx.attack_damage_context
    if attack is None:
        return {}
    return (ctx.damage_cache.get('foundation:hit_methods') or {}).get(attack.roll_id + '|' + target.entity_id, {})


def paid_receipt(ctx, target, source, resource):
    """Return this hit's actual spend event after prior-held resource validation.

    Only the final-hit window supplies the snapshot. A payment must follow its
    native roll, name this owner and feature, and spend exactly one unit. This
    is suitable for a one-numeric-value rider, not a generation entitlement.
    """
    attack = ctx.attack_damage_context
    snapshot = (ctx.hit_snapshots or {}).get('foundation:ash') or {}
    if not attack or not snapshot.get('prior_ash') or not qualifying_hit(ctx, target, 'ash'):
        return None
    for event in reversed(ctx.engine.events):
        if event.event_type == 'ATTACK_ROLLED' and event.payload.get('roll_id') == attack.roll_id:
            break
        if event.event_type == 'RESOURCE_SPENT' and event.actor_id == ctx.actor.entity_id \
                and event.source_definition_id == source:
            payload = event.payload or {}
            if payload.get('resource_id') == resource and int(payload.get('amount') or 0) == 1:
                return event
    return None


def settled_hit_receipt(engine, actor_id, roll_id, family):
    """Public committed source fact for generation/Garden after hit settlement.

    A receipt contains no inferred sphere or hidden HP values. The native
    producer records the exact action, target and roll and the pre-hit gate;
    callers still own their costs, clocks, source restrictions and generation.
    """
    return next((e for e in reversed(engine.events)
                 if e.event_type == 'PASSIVE_TRIGGERED' and e.actor_id == actor_id
                 and e.payload.get('trigger') == 'foundation_hit_settled'
                 and e.payload.get('family') == family and e.payload.get('roll_id') == roll_id), None)


def paid_value(ctx, target, source, resource, value):
    """Aggregate the raw signed base and one owned paid-value rider before clamping.

    Providers receive the validated payment event; unrelated/unpaid calls are
    inert. Values are integer additions, never replacements or extra packets.
    """
    payment = paid_receipt(ctx, target, source, resource)
    if payment is None:
        return None
    bonuses = run_strict('foundation_paid_value_bonus', ctx, target, source, int(value), payment)
    if any(type(v) is not int or v < 0 for v in bonuses):
        raise ValueError('foundation_paid_value_bonus requires nonnegative integer additions')
    return max(0, int(value) + sum(bonuses))
