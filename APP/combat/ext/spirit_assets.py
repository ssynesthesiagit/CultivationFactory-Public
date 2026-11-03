"""Shared map assets for Ancestral Legion and Kami's Messenger, with no turns, evented movement and optional shared HP.

Asset objects are damageable using the ordinary object attack/action transport.
Profiles are sealed by their owning ability. No creature, initiative slot, action
catalog mutation or independent AI is created. Public helpers: assets, manifest,
move, origins. All state is JSON in RuntimeObjectState.component.
"""
from . import hook

TAG = 'spirit_asset'


def assets(engine, owner, kind, *, live=True):
    return sorted((o for o in engine.state.objects.values()
                   if o.owner_id == owner.entity_id and (o.component.get(TAG) or {}).get('kind') == kind
                   and (not live or not o.destroyed)), key=lambda o: o.object_id)


def legal_spaces(engine, start, reach, *, empty=True):
    """Public traversal-free placement query used by asset-owning plug-ins."""
    from ..gate2_runtime_models import Position
    from ..object_geometry import target_cells
    from ..space import point
    occupied = {cell for a in engine.state.actors.values() if a.active for cell in engine._actor_volume(a)}
    occupied.update(point(cell) for o in engine.state.objects.values() if not o.destroyed
                    for cell in target_cells(engine, o))
    return [Position(x=x, y=y, z=start.z) for y in range(engine.grid.height) for x in range(engine.grid.width)
            if engine.grid.distance_ft(start, Position(x=x, y=y, z=start.z)) <= reach
            and (x, y) not in engine.grid.blocked
            and (not empty or (x, y, start.z) not in occupied)
            and not any(p in engine.grid.blocked for p in engine.grid.ray_cells(start, Position(x=x, y=y))[1:])]


def _choose(engine, owner, intent, positions, label, *, decline=False):
    from . import needle
    from ..senses import perceives_cell
    if needle.ai_controlled(engine, owner):
        positions = [p for p in positions if perceives_cell(engine, owner, p)]
    options = {f'cell:{p.x},{p.y},{p.z}': p for p in positions}
    if not options:
        return None
    picks = needle.ask(engine, intent, needle.checkpoint_id(engine, 'SPIRIT_ASSET', label), owner,
                       'choice:needle.spirit_asset.space', list(options),
                       labels={k: f'({p.x}, {p.y})' for k, p in options.items()},
                       preferred=[next(iter(options))], allow_decline=decline,
                       prompt=label, name=label)
    return options.get(next(iter(picks or []), ''))


def manifest(ctx, kind, *, count, hp_pb, speed, resist=(), immune=(), offices=()):
    from ..gate2_runtime_models import RuntimeObjectState
    engine, owner = ctx.engine, ctx.actor
    if assets(engine, owner, kind, live=False):
        return  # One asset per scene; destroyed assets need cultivation recharge.
    pool = f'{kind}:{owner.entity_id}:{engine.state.event_sequence}'
    # Gather every choice before creating any asset. A declined or unavailable
    # placement must not leave a paid, partial Legion on the map.
    chosen = []
    for index in range(count):
        occupied = {(p.x, p.y, p.z) for p in chosen}
        choices = [p for p in legal_spaces(engine, owner.position, 30)
                   if (p.x, p.y, p.z) not in occupied]
        where = _choose(engine, owner, ctx.intent, choices,
                        f'{kind}: place {index + 1} of {count} in an empty space within 30 feet.')
        if where is None:
            return
        chosen.append(where)
    for index, where in enumerate(chosen):
        obj = RuntimeObjectState(object_id=f'object:spirit_asset:{pool}:{index}', object_kind='SPIRIT_ASSET',
             position=where, unattended=False, flammable=False, owner_id=owner.entity_id,
             ac=int(ctx.numbers.get('save_dc') or 10), current_hp=hp_pb * int(ctx.numbers.get('pb') or 2),
             maximum_hp=hp_pb * int(ctx.numbers.get('pb') or 2), damage_immunities=tuple(immune),
             component={'name': f'{kind} {index + 1}', 'size': 'Small', 'resist': list(resist),
                        'created_by': ctx.source, TAG: {'kind': kind, 'pool': pool, 'speed': speed,
                        'source_cl': int(ctx.numbers.get('cl') or 1),
                        'office': offices[index % len(offices)] if offices else ''}})
        engine._update_object(obj, ctx.source, owner.entity_id)


def move(engine, owner, obj, distance, intent, source):
    from .object_subjects import movement_held
    if movement_held(obj):
        return
    where = _choose(engine, owner, intent, legal_spaces(engine, obj.position, distance),
                    f'{obj.component.get("name")}: choose a destination up to {distance} feet along a clear planar path, or stay. '
                    'The helper does not apply travel-mode terrain or crossed hazards; resolve those with the GM.', decline=True)
    if where is not None:
        engine._update_object(obj.model_copy(update={'position': where}), source, owner.entity_id)


def origins(engine, owner, kind):
    return [{'id': obj.object_id, 'label': obj.component['name'], 'position': obj.position.model_dump(mode='json')}
            for obj in assets(engine, owner, kind)]


@hook('turn_end')
def asset_movement(engine, owner, *, nominal=False):
    if nominal:
        return
    for obj in list(engine.state.objects.values()):
        record = obj.component.get(TAG)
        if record and obj.owner_id == owner.entity_id and not obj.destroyed:
            # This is a player-directed tabletop placement helper. It checks a
            # clear planar path; mode-specific terrain and crossed hazards are
            # intentionally left for the table to resolve manually.
            move(engine, owner, obj, int(record['speed']), engine._active_intent, obj.component['created_by'])


@hook('event')
def shared_health(engine, event_type, kwargs):
    if event_type != 'OBJECT_UPDATED' or not (kwargs.get('payload') or {}).get('damage'):
        return
    doc = kwargs['payload']['object']
    record = doc.get('component', {}).get(TAG)
    if not record:
        return
    intent = getattr(engine, '_active_intent', None)
    action = engine.action_catalog.get(getattr(engine, '_active_action_source_id', ''))
    for obj in list(engine.state.objects.values()):
        if obj.object_id == doc['object_id'] or (obj.component.get(TAG) or {}).get('pool') == record['pool']:
            component = {**obj.component, TAG: {**obj.component[TAG], **({'last_area_intent': intent.intent_id} if intent and action and (action.parameters.get('typed') or {}).get('area') else {})}}
            engine._update_object(obj.model_copy(update={'current_hp': doc['current_hp'], 'destroyed': doc['destroyed'], 'component': component}),
                                  kwargs.get('source_definition_id') or doc['component']['created_by'], doc['owner_id'])


@hook('object_damage_admission')
def one_area_hit_per_pool(engine, actor, obj, packets, source, *, area_scope_resolved=False):
    record = obj.component.get(TAG) or {}
    intent = getattr(engine, '_active_intent', None)
    action = engine.action_catalog.get(getattr(engine, '_active_action_source_id', ''))
    if record and intent and action and (area := (action.parameters.get('typed') or {}).get('area')):
        owner = engine.state.actors.get(obj.owner_id)
        if owner is None or (not area_scope_resolved and not area_recipient(actor, owner, area)):
            return False
        return record.get('last_area_intent') != intent.intent_id
    return None


def area_recipient(actor, owner, area):
    """Use the shared harmful-area policy for a damageable asset owner."""
    from ..area_recipients import harmful_area_subject_allowed
    return harmful_area_subject_allowed(actor, owner, area, {'type': 'damage'},
                                        recipient_is_creature=False)


@hook('technique_used', priority=50)
def areas_damage_assets(ctx):
    """Damageable spirit bodies in damaging areas, enemies unless explicitly scoped.

    Object-specific area handling owns ordinary structures; asset bodies also
    receive damaging areas that do not name structures. One pool per activation.
    """
    from .. import typed_executor as te
    from ..action_geometry import point
    from .objects import deal
    area = ctx.typed.get('area') or {}
    if not area.get('size_ft'):
        return
    aim = ctx.damage_cache.get('_checkpoint_aim') or point(ctx.engine, ctx.actor)
    cells = set(te.area_cells(ctx.engine, point(ctx.engine, ctx.actor), aim, area, include_altitude=True))
    # Admit geometric spirit pools; per-payload scopes are resolved below
    # against each owner before any packet is rolled. Area defaults must not
    # preempt an explicit damage row or its enclosing save. This hook is called
    # for every typed action, and irrelevant areas must stay inert.
    admitted = []
    seen = set()
    for obj in list(ctx.engine.state.objects.values()):
        record = obj.component.get(TAG)
        owner = ctx.engine.state.actors.get(obj.owner_id)
        if (not record or obj.destroyed or obj.position not in cells or owner is None
                or record.get('last_area_intent') == getattr(ctx.intent, 'intent_id', None)
                or record['pool'] in seen):
            continue
        seen.add(record['pool'])
        admitted.append(obj)
    if not admitted:
        return
    # Use the executor's documented typed-effect eligibility/branch seam:
    # objects fail save branches (no save of their own), while menus and other
    # common gates are honored. This avoids summing mutually exclusive rows.
    rows_by_object = {}
    all_rows = {}
    for obj in admitted:
        owner = ctx.engine.state.actors.get(obj.owner_id)
        rows = te.area_damage_rows(ctx, ctx.typed.get('effects') or [], owner=owner)
        rows_by_object[obj.object_id] = rows
        all_rows.update({id(row): row for row in rows})
    packets_by_key, row_keys = {}, {}
    for row in all_rows.values():
        key = f"damage_bonus_roll:{row['damage_bonus_group']}" if row.get('damage_bonus_group') else id(row)
        row_keys[id(row)] = key
        packets_by_key.setdefault(key, te._damage_roll(ctx, row))
    if not packets_by_key:
        return
    for obj in admitted:
        keys = dict.fromkeys(row_keys[id(row)] for row in rows_by_object[obj.object_id])
        packets = [packets_by_key[key] for key in keys]
        if packets:
            deal(ctx.engine, ctx.actor, ctx.engine.state.objects[obj.object_id], packets, ctx.source,
                 area_scope_resolved=True)
