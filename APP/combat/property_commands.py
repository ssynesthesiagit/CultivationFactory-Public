"""Public opt-in property-command effects, shared by dispels and overwrites.

Source producers publish property_command_source(engine, creator, action) with
one descriptor {dc?: int, pattern_rank?: int, pb?: int, key_mod?: int}. An active
condition or modifier from that exact creator/action is required. No descriptor
means unknown, never permission from an effect's name, team or numeric sign.
DC precedence: explicit DC, 10 + Pattern Rank, 10 + creator PB + key modifier.
The source must supply the numbers; absent numbers are not replaced with guesses.
"""
from . import ext


def active(engine, holder):
    found={}
    instances=[]
    if hasattr(holder,'conditions'):
        instances.extend((holder,kind,key,item) for kind,items in
                         (('condition',holder.conditions),('modifier',holder.modifiers)) for key,item in items.items())
    for rows in ext.run_strict('property_command_instances',engine,holder):
        if rows is None:
            continue
        for owner,kind,key in rows:
            if engine.state.actors.get(owner.entity_id) is not owner or kind not in {'condition','modifier'}:
                raise ValueError('Property-command instances must name a native holder.')
            item=(owner.conditions if kind=='condition' else owner.modifiers).get(key)
            if item is not None:
                instances.append((owner,kind,key,item))
    for owner,kind,key,item in instances:
        if False in ext.run_strict('property_command_subject_instance_allowed',engine,holder,owner,kind,key,item):
            continue
        if (kind=='condition' and item.condition_id.startswith('condition:typed.suppressed.')) or (kind=='modifier' and item.target_field.startswith('suppressed:')):
            continue
        source=item.source_definition_id
        action=engine.action_catalog.get(source)
        creator=engine.state.actors.get(item.source_actor_id)
        if action is None or creator is None or action.owner_id!=creator.entity_id:
            continue
        if False in ext.run_strict('property_command_instance_allowed',engine,creator,action,owner,kind,item):
            continue
        specs=[spec for spec in ext.run_strict('property_command_source',engine,creator,action) if spec is not None]
        if not specs:
            specs=[spec for spec in ext.run_strict('property_command_source_fallback',engine,creator,action) if spec is not None]
        if not specs:
            continue
        if len(specs)!=1 or not isinstance(specs[0],dict):
            raise ValueError('A property-command source requires exactly one descriptor.')
        spec=specs[0]
        if set(spec)-{'dc','pattern_rank','pb','key_mod'} or any(type(v) is not int for v in spec.values()):
            raise ValueError('Property-command metadata uses named integer statistics.')
        if 'dc' in spec:
            dc=spec['dc']
        elif 'pattern_rank' in spec:
            dc=10+spec['pattern_rank']
        elif {'pb','key_mod'}<=set(spec):
            dc=10+spec['pb']+spec['key_mod']
        else:
            continue
        if dc < 0:
            raise ValueError('Property-command DC must be nonnegative.')
        entry=found.setdefault(source,{'creator':creator,'action':action,'dc':dc,'instances':[]})
        entry['instances'].append((owner,kind,key,item))
    return found


def settle(ctx,holder,record,mode):
    """End/suppress only the selected source's actual retained instances."""
    from .ext.end_effect import remove_instance,suppress
    if mode not in {'end','suppress'}:
        raise ValueError('Choose ending or suppression.')
    for owner,kind,key,item in record['instances']:
        current=owner.conditions.get(key) if kind=='condition' else owner.modifiers.get(key)
        if current is not item:
            continue
        if mode=='suppress':
            suppress(owner,kind,key,item,by=ctx.actor,engine=ctx.engine,boundary='end')
        else:
            remove_instance(ctx,owner,kind,key,item)
