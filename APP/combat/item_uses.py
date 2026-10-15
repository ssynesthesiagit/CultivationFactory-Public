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
