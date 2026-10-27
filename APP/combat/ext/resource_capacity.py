"""Temporary represented-pool capacity, bound to an explicit condition anchor."""
from . import effect, hook

STATE = 'condition:typed.resource_capacity'


@effect('resource_capacity')
def grant(ctx, spec):
    """Positive capacity only; independent sources stack; a source is idempotent.

    Two row shapes share this one effect. An ``anchor`` row is the represented-pool
    ledger: the maximum grows only while that named anchor condition is still held,
    and the ledger is withdrawn when its anchor goes. A counted ``duration`` row with
    no anchor is the ordinary timed grant: the maximum grows for that duration and
    reverts when the condition itself ends. Either way the condition carries
    ``retain_removal_data`` so its ending still knows the base it must restore.
    """
    actor, engine = ctx.actor, ctx.engine
    pool = spec['resource_id']
    anchor = spec.get('anchor')
    if anchor:
        amount = int(spec['amount'])
        if amount <= 0 or pool not in actor.resources:
            return
        if not any(c.condition_id == anchor for c in actor.conditions.values()):
            return
    else:
        # Timed grant: the printed duration decides, and it must be one the engine removes.
        if pool not in actor.resource_maximums or type(spec['bonus']) is not int or spec['bonus'] <= 0:
            raise ValueError('A temporary capacity grant requires an existing pool and positive integer bonus')
        amount = int(spec['bonus'])
        from ..typed_executor import effect_expiry
        expiry = effect_expiry(ctx, spec, actor, condition=True)
        if not expiry:
            raise ValueError('A temporary capacity grant requires a recognized expiry')
    held = [c for c in actor.conditions.values() if c.condition_id == STATE and c.data['resource_id'] == pool]
    if any(c.source_definition_id == ctx.source for c in held):
        return
    from ..resource_labels import resource_name
    base = int(held[0].data['base']) if held else actor.resource_maximums[pool]
    if anchor:
        expires_on, label = 'UNTIL_REMOVED', f'Maximum {resource_name(pool)} increases by {amount} while its source is active'
    else:
        expires_on = expiry
        label = f'Maximum {resource_name(pool)} +{amount} for the duration'
    data = {'resource_id': pool, 'amount': amount, 'base': base,
            'retain_removal_data': True, 'label': label}
    if anchor:
        data['anchor'] = anchor
    engine._apply_condition(actor, STATE, ctx.source, actor.entity_id, expires_on=expires_on, data=data)


@hook('event', nested=True)
def synchronize(engine, event_type, kwargs):
    if event_type not in {'CONDITION_APPLIED', 'CONDITION_REMOVED'}:
        return
    from .condition_events import drop_condition
    removed = (kwargs.get('payload') or {}).get('removed_condition') or {}
    for actor in engine.state.actors.values():
        pools = {}
        withdrawn = (removed.get('data') or {}) if (removed.get('condition_id') == STATE
                      and removed.get('target_id') == actor.entity_id) else {}
        if withdrawn:
            pools[withdrawn['resource_id']] = []
        for iid, c in list(actor.conditions.items()):
            if c.condition_id == STATE:
                pools.setdefault(c.data['resource_id'], []).append((iid, c))
        for pool, held in pools.items():
            base = int(held[0][1].data['base'] if held else withdrawn['base'])
            # An anchored ledger counts only while its anchor is held; a timed grant
            # has no anchor and stays active for as long as the condition exists.
            active = [(iid, c) for iid, c in held
                      if c.data.get('anchor') is None
                      or any(a.condition_id == c.data['anchor'] for a in actor.conditions.values())]
            maximum = base + sum(int(c.data['amount']) for iid, c in active)
            source = held[0][1].source_definition_id if held else removed['source_definition_id']
            engine._set_resource_maximum(actor, pool, maximum, source)
            for iid, c in held:
                if not any(iid == kept for kept, _ in active):
                    drop_condition(engine, actor, iid, c.source_definition_id)