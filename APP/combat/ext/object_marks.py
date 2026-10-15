"""Owner-qualified marks on actual native objects.

Public add/marked/spend APIs use evented OBJECT_UPDATED snapshots and the
recognized END_OF_MARKER_NEXT_TURN clock. Earth Clod is the first producer;
Earth response consumers can query or spend the same object identity. Creature
and object marks share each owner's printed cap, ordered by event sequence.
No mark records means no changes to ordinary objects or historical saves.
"""
from copy import deepcopy
from . import hook
KEY = 'cultivation_marks'


def marked(obj, owner_id, name):
    return any(r['owner_id'] == owner_id and r['name'] == name for r in (obj.component or {}).get(KEY, ()))


def component_spend(engine, obj, owner_id, name, source, instance_id=None):
    component = deepcopy(obj.component or {})
    rows = component.get(KEY, [])
    kept = [r for r in rows if not (r['owner_id'] == owner_id and r['name'] == name
            and (instance_id is None or r.get('instance_id') == instance_id))]
    if kept == rows: return False
    if kept: component[KEY] = kept
    else: component.pop(KEY, None)
    engine._update_object(obj.model_copy(update={'component': component}), source, owner_id)
    return True


def spend(engine, obj, owner_id, name, source):
    from .condition_ownership import remove_instance
    matches = [r for r in (obj.component or {}).get(KEY, ()) if r['owner_id'] == owner_id and r['name'] == name]
    if not matches: return False
    owner = engine.state.actors.get(owner_id)
    for row in matches:
        if owner is not None and row.get('instance_id') in owner.conditions:
            remove_instance(engine,owner,row['instance_id'],source)
    component_spend(engine,engine.state.objects[obj.object_id],owner_id,name,source)
    return True


def add(ctx, obj, name, cap=None, *, duration=None, data=None):
    from ..typed_executor import mark_condition_id
    from .condition_ownership import remove_instance
    owner = ctx.actor.entity_id
    spend(ctx.engine, obj, owner, name, ctx.source)
    obj = ctx.engine.state.objects[obj.object_id]
    if cap:
        existing = [(c.applied_sequence, ('creature', a, iid)) for a in ctx.engine.state.actors.values()
                    for iid, c in a.conditions.items() if c.condition_id == mark_condition_id(name, owner)]
        existing += [(r['sequence'], ('object', o, '')) for o in ctx.engine.state.objects.values()
                     for r in (o.component or {}).get(KEY, ()) if r['owner_id'] == owner and r['name'] == name]
        for _, (kind, holder, iid) in sorted(existing, key=lambda r: r[0])[:max(0, len(existing) - cap + 1)]:
            if kind == 'creature': remove_instance(ctx.engine, holder, iid, ctx.source)
            else: spend(ctx.engine, holder, owner, name, ctx.source)
    import re
    cid = 'condition:source.object_mark.' + re.sub('[^a-z0-9]+','_',name.lower()) + ':' + obj.object_id
    from .. import object_rules
    before = set(ctx.actor.conditions)
    from ..typed_executor import effect_expiry
    expiry=effect_expiry(ctx, {'duration':duration}, ctx.actor, condition=True) if duration else 'END_OF_MARKER_NEXT_TURN'
    ctx.engine._apply_condition(ctx.actor,cid,ctx.source,owner,expires_on=expiry,
        data={'label': name + ' on ' + object_rules.label(obj), 'marker_turn': ctx.actor.turns_started,
              'object_mark_name': name, 'object_id': obj.object_id, 'retain_removal_data': 1, **(data or {})})
    placed = [c for iid,c in ctx.actor.conditions.items() if iid not in before and c.condition_id == cid]
    if not placed: return
    iid = placed[0].instance_id
    component = deepcopy(ctx.engine.state.objects[obj.object_id].component or {})
    component[KEY] = [*component.get(KEY, []), {'owner_id': owner, 'name': name,
        'expires_on': expiry, 'marker_turn': ctx.actor.turns_started,
        'sequence': ctx.engine.state.event_sequence + 1, 'source': ctx.source, 'instance_id': iid}]
    ctx.engine._update_object(ctx.engine.state.objects[obj.object_id].model_copy(update={'component': component}), ctx.source, owner)


@hook('state_event')
def expired(engine,event):
    event_type=event.event_type
    kwargs={'payload':event.payload,'source_definition_id':event.source_definition_id}
    if event_type != 'CONDITION_REMOVED': return
    row = (kwargs.get('payload') or {}).get('removed_condition') or {}
    data = row.get('data') or {}
    if not data.get('object_mark_name'): return
    obj = engine.state.objects.get(data.get('object_id'))
    if obj is not None:
        component_spend(engine,obj,row['source_actor_id'],data['object_mark_name'],
                        kwargs.get('source_definition_id') or 'system:object_mark_expired',row['instance_id'])


@hook('mark_applied')
def share_creature_cap(ctx, name, subject):
    from ..typed_executor import mark_capacity, mark_condition_id
    from .condition_ownership import remove_instance
    owner = ctx.actor.entity_id
    objects = [(r['sequence'], 'object', o, '') for o in ctx.engine.state.objects.values()
               for r in (o.component or {}).get(KEY, ()) if r['owner_id'] == owner and r['name'] == name]
    if not objects:
        return
    cap = mark_capacity(ctx, name)
    if not cap:
        return
    all_marks = objects + [(c.applied_sequence, 'creature', a, iid) for a in ctx.engine.state.actors.values()
        for iid,c in a.conditions.items() if c.condition_id == mark_condition_id(name, owner)]
    for _,kind,holder,iid in sorted(all_marks, key=lambda r:r[0])[:max(0,len(all_marks)-cap)]:
        if kind == 'creature': remove_instance(ctx.engine,holder,iid,ctx.source)
        else: spend(ctx.engine,holder,owner,name,ctx.source)
