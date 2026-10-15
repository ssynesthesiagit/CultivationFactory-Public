"""Native physical-item use checkpoint shared by source-owned Action providers.

Callers resolve their own costs, choices and printed outcome. This helper binds
the use to an actual current possession, runs item_use_begin before the outcome,
and records item_use_committed afterwards. Neither a declaration nor a receipt
grants an item or fabricates an attack/check. No provider means no added effect.
"""
from . import ext


def possessions(engine, actor):
    """Current native carried/transferred identities with remaining quantity."""
    from .ext.scoundrel_riders import possessions as current
    from .carry import quantity_exhausted
    return [item for item in current(engine, actor)
        if not quantity_exhausted(engine, actor, item)]


def attack_item(ctx):
    """The actual current physical weapon, shared by all its attack modes."""
    from .ext.weapon_hits import weapon_identity
    identity = weapon_identity(ctx)
    if not identity:
        return None
    return next((item for item in possessions(ctx.engine, ctx.actor)
        if str(item.get('weapon_action') or '').split('#')[0] == identity.split('#')[0]), None)


def pending_attack(ctx):
    """At the final validated pre-draw checkpoint, begin an opted-in item use.

    Pure item_use_tracking(engine,actor) -> bool | None requests tracking only
    for a source-owned trigger/condition. No requester means no event, query of
    inventory, cache entry or mode change. item_roll_pending(ctx,item,kind)
    returns {bonus:int,modes:[ADVANTAGE|DISADVANTAGE]} or None. Modes are still
    independent contributions and must be folded before native cancellation.
    """
    tracking = ext.run_strict('item_use_tracking', ctx.engine, ctx.actor)
    if any(type(value) is not bool for value in tracking):
        raise ValueError('Item-use tracking must be a boolean.')
    if not any(tracking):
        return {'bonus': 0, 'modes': []}
    item = attack_item(ctx)
    if item is None:
        return {'bonus': 0, 'modes': []}
    ext.run_strict('item_use_begin', ctx, item, 'attack')
    current = attack_item(ctx)
    if current is None or current['object'] != item['object']:
        raise ValueError('The actual weapon is no longer available for this roll.')
    ctx.damage_cache['_pending_item_attack'] = dict(item)
    return pending_roll(ctx, item, 'attack')


def pending_roll(ctx, item, kind):
    """Fold only contributions scoped to this actual item's attack/check."""
    if kind not in ('attack', 'check'):
        raise ValueError('An item roll must be an attack or ability check.')
    result = {'bonus': 0, 'modes': []}
    for answer in ext.run_strict('item_roll_pending', ctx, item, kind):
        if (not isinstance(answer, dict) or set(answer) - {'bonus', 'modes'}
                or type(answer.get('bonus', 0)) is not int
                or not isinstance(answer.get('modes', []), (list, tuple))
                or any(mode not in ('ADVANTAGE', 'DISADVANTAGE') for mode in answer.get('modes', []))):
            raise ValueError('Item roll contributions require an integer bonus and known independent modes.')
        result['bonus'] += answer.get('bonus', 0)
        result['modes'].extend(answer.get('modes', []))
    return result


def complete_attack(ctx, roll, hit, critical):
    """Commit the opted-in receipt only after a native attack actually rolled."""
    item = ctx.damage_cache.pop('_pending_item_attack', None)
    if item is None or not isinstance(roll, dict) or not roll.get('roll_id'):
        return
    ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=ctx.actor.entity_id,
        payload={'checkpoint': 'ITEM_USE_COMMITTED', 'item_identity': item['object'], 'purpose': 'attack',
            'attack_roll_id': roll['roll_id'], 'hit': int(bool(hit)), 'critical': int(bool(critical))})
    ext.run_strict('item_use_committed', ctx, item, 'attack', int(bool(hit)))


def resolve(ctx, identity, purpose, operation):
    """Resolve one actual use; operation(item) returns its printed outcome.

    item_use_begin(ctx,item,purpose) -> None may ask the actual trigger owner.
    item_use_committed(ctx,item,purpose,outcome) -> None observes the resolved
    use. Both receive the validated exact possession and actual Action context;
    providers must guard their own source ownership and subject/expiry rules.
    """
    if type(identity) is not str or type(purpose) is not str or not purpose.strip():
        raise ValueError('An item use requires its current physical identity and purpose.')
    def held():
        return next((i for i in possessions(ctx.engine, ctx.actor) if i['object'] == identity), None)
    item = held()
    if item is None:
        raise ValueError('This creature no longer possesses that usable item.')
    ext.run_strict('item_use_begin', ctx, item, purpose)
    item = held()
    if item is None:
        raise ValueError('The triggering item is no longer available to use.')
    outcome = operation(item)
    ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=ctx.actor.entity_id,
        payload={'checkpoint': 'ITEM_USE_COMMITTED', 'item_identity': identity, 'purpose': purpose})
    ext.run_strict('item_use_committed', ctx, item, purpose, outcome)
    return outcome


def resolve_scene(session, actor_id, identity, purpose, operation, *, seconds=0):
    """Actual elapsed-scene use, sharing identity/quantity with native combat.

    Strict journey_item_use_begin(session,actor_id,item,purpose) and
    journey_item_use_committed(session,actor_id,item,purpose,outcome) are inert
    without providers. Callers own printed costs/outcomes; no receipt grants an
    item, check, healing or synthetic combat event.
    """
    from .journey import require
    from .journey_inventory import possessions as current
    require(session.state['phase'] == 'travel' and actor_id in session.state['actors']
        and type(identity) is str and type(purpose) is str and bool(purpose.strip())
        and type(seconds) is int and seconds >= 0, 'Choose an actual item use during travel.')
    def held():
        return next((item for item in current(session, actor_id) if item['object'] == identity), None)
    item = held()
    require(item is not None, 'This creature no longer possesses that usable item.')
    ext.run_strict('journey_item_use_begin', session, actor_id, item, purpose)
    session.tick(seconds)
    item = held()
    if item is None or session.state['actors'][actor_id]['incapacitated']:
        session.emit('ITEM_USE_INTERRUPTED', actor_id, item_identity=identity, purpose=purpose,
            text='The creature or its item could not finish this use after the elapsed time.')
        return None
    outcome = operation(item)
    session.emit('ITEM_USE_COMMITTED', actor_id, item_identity=identity, purpose=purpose)
    ext.run_strict('journey_item_use_committed', session, actor_id, item, purpose, outcome)
    return outcome
