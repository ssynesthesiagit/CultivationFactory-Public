"""Real identities and locations for Temper Glass Surface.

Consumers: glass_refraction's single existing effect and all its surface queries.
Body/equipment follow possession; touched objects follow native object updates;
touched floor remains at its recorded square. No copies of items are created.
"""
from . import needle
from .condition_ownership import remove_instance

TEMPERED = 'condition:typed.glass_tempered'


def choices(engine, actor):
    from .. import carry
    from .hand_occupancy import weapon_grips, occupancy
    from .surface_contact import solid_contact, SOLID_MATERIALS
    from .. import object_rules
    options = {'body': {'kind': 'body', 'label': 'your body'}}
    grips = weapon_grips(engine, actor)
    held = {v for values in occupancy(engine, actor, grips=grips).values() for v in values}
    for item in (carry.carrying_of(engine, actor.entity_id) or {}).get('items') or []:
        key = item['key']
        if not carry.holds(engine, actor, key):
            continue
        weapon = item.get('weapon_action')
        location = carry.owned_item_location(actor, key)
        if item.get('worn') or weapon in grips or 'shield:' + key in held or (location or '').startswith('hand:'):
            options['item:' + key] = {'kind': 'item', 'item_key': key, 'label': item['name']}
    for obj in engine.state.objects.values():
        if (not obj.destroyed and engine.grid.distance_ft(actor.position, obj.position) <= 5
                and str((obj.component or {}).get('material') or '').lower() in SOLID_MATERIALS
                and engine.grid.line_of_physical_transmission(actor.position, obj.position)):
            options['object:' + obj.object_id] = {'kind': 'object', 'object_id': obj.object_id, 'label': object_rules.label(obj)}
    if solid_contact(engine, actor):
        p = actor.position
        options[f'ground:{p.x}:{p.y}:{p.z}'] = {'kind': 'ground', 'x': p.x, 'y': p.y, 'z': p.z,
            'label': f'the solid surface you touch at ({p.x}, {p.y}), {p.z * 5} feet high'}
    return options


def cells(engine, actor):
    """Current cells of the owner's existing tempered surfaces; no events."""
    from .. import carry
    from .hand_occupancy import weapon_grips, occupancy
    result = set()
    current = choices(engine, actor)
    for c in actor.conditions.values():
        if c.condition_id != TEMPERED or c.source_actor_id != actor.entity_id:
            continue
        data = c.data or {}
        kind = data.get('surface_kind')
        if kind is None:  # historical saved body-only effect
            result.update(tuple(p) for p in engine._actor_cells(actor))
        elif kind == 'body':
            result.update(tuple(p) for p in engine._actor_cells(actor))
        elif kind == 'item':
            from .surface_identities import item_position
            point = item_position(engine,actor.entity_id,data.get('item_key'))
            if point is not None: result.add((point.x,point.y))
        elif kind == 'object':
            obj = engine.state.objects.get(data.get('object_id'))
            if obj is not None and not obj.destroyed:
                result.add((obj.position.x, obj.position.y))
        elif kind == 'ground':
            result.add((data['x'], data['y']))
    return result


def temper(ctx):
    from .effect_durations import round_token
    options = choices(ctx.engine, ctx.actor)
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'temper_surface', ctx.source),
        ctx.actor, 'choice:needle.temper_surface', list(options), preferred=['body'],
        labels={key: row['label'] for key, row in options.items()}, name='Temper Glass Surface',
        prompt='Temper Glass Surface: choose your body, worn armor, a held item, or a solid surface you touch. A Bonus Action, no Cultivation Point cost, for one minute; tempering your body does not change its defenses or make it fragile.')
    if not chosen:
        return
    key = chosen[0]; surface = options[key]
    held = [(iid, c) for iid, c in ctx.actor.conditions.items() if c.condition_id == TEMPERED and c.source_actor_id == ctx.actor.entity_id]
    same = [iid for iid, c in held if (c.data or {}).get('surface_identity', 'body') == key]
    maximum = 1 + int(ctx.numbers.get('cl', 1) >= 5) + int(ctx.numbers.get('cl', 1) >= 11) + int(ctx.numbers.get('cl', 1) >= 17)
    if not same and len(held) >= maximum:
        replacement = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'temper_replace', ctx.source),
            ctx.actor, 'choice:needle.temper_replace', [iid for iid, _ in held],
            labels={iid: c.data.get('label', 'Tempered surface') for iid, c in held},
            prompt=f'Temper Glass Surface: you can maintain {maximum} surfaces. Choose which existing surface ends when you temper {surface["label"]}.',
            name='Temper Glass Surface')
        same += replacement
    for iid in same:
        remove_instance(ctx.engine, ctx.actor, iid, ctx.source)
    ctx.engine._apply_condition(ctx.actor, TEMPERED, ctx.source, ctx.actor.entity_id,
        expires_on=round_token(ctx.engine, 10), data={'label': 'Tempered Glass Surface: ' + surface['label'],
            'surface_identity': key, 'surface_kind': surface['kind'],
            **{k: v for k, v in surface.items() if k not in ('label', 'kind')}})
