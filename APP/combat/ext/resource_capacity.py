"""Temporary represented-pool capacity, bound to an explicit condition anchor."""
from . import effect, hook

STATE = 'condition:typed.resource_capacity'


@effect('resource_capacity')
def grant(ctx, spec):
    """Positive capacity only; independent sources stack; a source is idempotent."""
    actor, engine = ctx.actor, ctx.engine
    pool, anchor = spec['resource_id'], spec['anchor']
    amount = int(spec['amount'])
    if amount <= 0 or pool not in actor.resources or not any(c.condition_id == anchor for c in actor.conditions.values()):
        return
    held = [c for c in actor.conditions.values() if c.condition_id == STATE and c.data['resource_id'] == pool]
    if any(c.source_definition_id == ctx.source for c in held):
        return
    from ..resource_labels import resource_name
    base = int(held[0].data['base']) if held else actor.resource_maximums[pool]
    engine._apply_condition(actor, STATE, ctx.source, actor.entity_id, expires_on='UNTIL_REMOVED',
                            data={'resource_id': pool, 'anchor': anchor, 'amount': amount, 'base': base,
                                  'retain_removal_data': True,
                                  'label': f'Maximum {resource_name(pool)} increases by {amount} while its source is active'})


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
            active = [(iid, c) for iid, c in held
                      if any(a.condition_id == c.data['anchor'] for a in actor.conditions.values())]
            maximum = base + sum(int(c.data['amount']) for iid, c in active)
            source = held[0][1].source_definition_id if held else removed['source_definition_id']
            engine._set_resource_maximum(actor, pool, maximum, source)
            for iid, c in held:
                if not any(iid == kept for kept, _ in active):
                    drop_condition(engine, actor, iid, c.source_definition_id)
