"""Actual references for Temper Glass Surface, never invented objects.

Body, worn armor, held gear, runtime objects and authored solid terrain retain
their identities and durability. A reference is not an attack-ray receipt.
"""
from . import hook

SOURCE = 'GLASS_BASE_TEMPER_GLASS_SURFACE'
CONDITION = 'condition:typed.glass_tempered'


def owns(engine, actor):
    return any(((engine.action_catalog[aid].parameters or {}).get('typed') or {}).get('source') == SOURCE
        for aid in actor.action_ids if aid in engine.action_catalog)


@hook('carried_item_interactions')
def enable_holding(engine, actor):
    return True if owns(engine, actor) else None


def profiles(engine, owner):
    """Current source-owned references, each on its ordinary expiry clock."""
    return [c for c in owner.conditions.values() if c.condition_id == CONDITION
        and c.source_actor_id == owner.entity_id and c.data.get('surface_kind')
        in ('body', 'armor', 'shield', 'weapon', 'held_object', 'object', 'terrain')]


def item_location(engine, identity):
    """Actual carrier and native hand/worn state; unknown grants no location."""
    from .scoundrel_riders import possessions, held_possessions
    for actor in sorted(engine.state.actors.values(), key=lambda actor: actor.entity_id):
        item = next((item for item in possessions(engine, actor) if item['object'] == identity), None)
        if item is not None:
            held = any(value['object'] == identity for value in held_possessions(engine, actor))
            return actor, item, held
    return None


def body_tempered(engine, owner):
    """A held weapon/object is not the printed body/armor/shield trigger."""
    for profile in profiles(engine, owner):
        kind = profile.data['surface_kind']
        if kind == 'body' and profile.data['surface_ref'] == owner.entity_id:
            return True
        if kind in ('armor', 'shield'):
            located = item_location(engine, profile.data['surface_ref'])
            if located and located[0] is owner and (located[1].get('worn') if kind == 'armor' else located[2]):
                return True
    return any(c.condition_id == 'condition:typed.glass_incarnation' for c in owner.conditions.values())


def object_owners(engine, obj):
    """Only actual object references grant tempered-surface authority."""
    return [actor for actor in engine.state.actors.values() if actor.active
        and any(c.data['surface_kind'] == 'object' and c.data['surface_ref'] == obj.object_id
            for c in profiles(engine, actor))]


def cells(engine, owner):
    """Squares containing referenced surfaces, not inferred attack crossings."""
    from ..object_geometry import target_cells
    out = set()
    regions = {row['region_id']: row for row in (engine.battlefield_document or {}).get('terrain_regions', ())}
    for profile in profiles(engine, owner):
        kind, ref = profile.data['surface_kind'], profile.data['surface_ref']
        if kind == 'body' and ref == owner.entity_id:
            out.update(engine._actor_cells(owner))
        elif kind in ('armor', 'shield', 'weapon', 'held_object'):
            located = item_location(engine, ref)
            if located and (located[1].get('worn') or located[2]):
                out.update(engine._actor_cells(located[0]))
        elif kind == 'object':
            obj = engine.state.objects.get(ref)
            if obj is not None and not obj.destroyed:
                out.update((cell.x, cell.y) for cell in target_cells(engine, obj))
        elif kind == 'terrain' and ref in regions:
            out.update((cell['x'], cell['y']) for cell in regions[ref].get('cells', ()))
    return out


def options(ctx):
    """Every currently represented legal self/held/touched surface by identity."""
    engine, actor = ctx.engine, ctx.actor
    if not owns(engine, actor):
        return {}
    from .scoundrel_riders import possessions, held_possessions
    from ..asset_anchor_runtime import touches_object
    from ..object_rules import label, solid_surface
    from ..senses import perceives_object
    from ..gate2_runtime_models import Position
    out = {'body:' + actor.entity_id: ('body', actor.entity_id, 'Your body (does not become fragile)')}
    held = {item['object'] for item in held_possessions(engine, actor)}
    for item in possessions(engine, actor):
        kind = ('armor' if item.get('worn') and not item.get('shield') else
            'shield' if item.get('shield') and item['object'] in held else
            'weapon' if item.get('weapon_action') and item['object'] in held else
            'held_object' if item['object'] in held else '')
        if kind:
            out['item:' + item['object']] = (kind, item['object'],
                ('Your worn ' if kind == 'armor' else 'Your held ') + str(item.get('name') or 'object'))
    actor_cells = tuple(engine._actor_volume(actor))
    for obj in sorted(engine.state.objects.values(), key=lambda obj: obj.object_id):
        if (not obj.destroyed and solid_surface(obj) is True and perceives_object(engine, actor, obj)
                and touches_object(engine, actor, obj)):
            out['object:' + obj.object_id] = ('object', obj.object_id, 'Touch ' + label(obj))
    for region in (engine.battlefield_document or {}).get('terrain_regions', ()):
        if region.get('terrain_type') != 'BLOCKED':
            continue
        reachable = any(engine.grid.terrain_at((cell['x'], cell['y'], actor.position.z), 'BLOCKED')
            and engine.grid.distance_between_cell_sets_ft(actor_cells,
                (Position(x=cell['x'], y=cell['y'], z=actor.position.z),)) <= 5
            for cell in region.get('cells', ()))
        if reachable:
            ref = region['region_id']
            out['terrain:' + ref] = ('terrain', ref, 'Touch ' + str(region.get('description') or 'this solid wall surface'))
    return out


def temper(ctx):
    """Resolve the actual source choice/cap and its printed one-minute clock."""
    from .needle import ask, checkpoint_id
    from .effect_durations import round_token
    pool = options(ctx)
    if not pool:
        return
    actor, engine = ctx.actor, ctx.engine
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, 'TEMPER_GLASS_SURFACE', actor.entity_id), actor,
        'choice:needle.temper_glass_surface', list(pool), labels={key: value[2] for key, value in pool.items()},
        preferred=[next(iter(pool))], name='Temper Glass Surface',
        prompt='Temper Glass Surface: choose your body, worn armor, a held weapon/shield/object, '
            'or a solid surface you can touch. Bonus Action, 0 Cultivation Points, lasts 1 minute. '
            'Your body does not become fragile.')
    if not chosen:
        return
    kind, ref, name = pool[chosen[0]]
    held = profiles(engine, actor)
    same = [c for c in held if c.data['surface_kind'] == kind and c.data['surface_ref'] == ref]
    cl = int(ctx.numbers.get('cl') or 1)
    cap = 4 if cl >= 17 else 3 if cl >= 11 else 2 if cl >= 5 else 1
    if not same and len(held) >= cap:
        ended = ask(engine, ctx.intent, checkpoint_id(engine, 'TEMPER_GLASS_REPLACE', actor.entity_id), actor,
            'choice:needle.temper_glass_replace', [c.instance_id for c in held],
            labels={c.instance_id: 'End ' + c.data.get('surface_label', 'this tempered surface') for c in held},
            preferred=[held[0].instance_id], name='Temper Glass Surface',
            prompt=f'Temper Glass Surface: you can maintain {cap} surface' + ('s' if cap != 1 else '')
                + '. Choose one to end before tempering the new surface. No additional cost.')
        if not ended:
            return
        same = [next(c for c in held if c.instance_id == ended[0])]
    for old in same:
        engine._remove_condition_instance(actor, old.instance_id, ctx.source)
    engine._apply_condition(actor, CONDITION, ctx.source, actor.entity_id,
        expires_on=round_token(engine, 10), data={'surface_kind': kind, 'surface_ref': ref,
            'surface_label': name, 'source_cl': cl,
            'label': 'Tempered Glass Surface: ' + name + '. Lasts 1 minute; keeps its existing durability.'})
