"""Metal's loose-object interaction and the triggering hit's Sharpen choice.

Uses native map objects, sight/effect rays, object interaction budget and evented
updates. No item is fabricated. Source membership is read from the committed
Loadstone headings, not from inventory names or damage types.
"""
from . import hook, effect
from . import needle

HAND = 'METAL_BASE_MAGNET_HAND'
SHARPEN = 'METAL_BASE_SHARPEN'
LOADSTONE = frozenset({
    'TAL_METAL_COMMAND_THE_HIDDEN_BLADE', 'TAL_METAL_CONDUCTOR_S_PALM',
    'TAL_METAL_LOADSTONE_PRISON', 'TAL_METAL_LOADSTONE_TUG', 'TAL_METAL_MAGNET_STEP',
    'TAL_METAL_MOUNTAIN_ORE_DICTATE', 'TAL_METAL_ORE_ROOT_SNARE',
    'tianxia.talent.metal.loadstone_emperor_scripture'})
METALS = frozenset({'iron', 'steel', 'mithral', 'adamantine'})


@hook('compile_action')
def compile_hand(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') != HAND or HAND not in info['owned_ids']:
        return None
    small = int(info['numbers'].get('cl') or 1) >= 5 and bool(LOADSTONE.intersection(info['owned_ids']))
    return action.model_copy(update={'target_kind': 'SELF', 'range_ft': None,
        'parameters': {**action.parameters, 'inert': False,
            'description': 'Move one visible, unattended Tiny metal object within 30 feet up to 10 feet. Uses your free object interaction; no cultivation points. Cannot attack, disarm or operate mechanisms.',
            'typed': {**typed, 'effects': [{'type': 'magnet_hand', 'small': int(small)}], 'riders': [], 'manual_inline_choice': True}}})


def hand_objects(engine, actor, small):
    from ..senses import perceives_object
    from ..effect_cover import rays
    return {obj.object_id: obj for obj in sorted(engine.state.objects.values(), key=lambda o: o.object_id)
        if not obj.destroyed and obj.unattended
        and (obj.component or {}).get('size') in (('tiny', 'small') if small else ('tiny',))
        and (obj.component or {}).get('metal', int((obj.component or {}).get('material') in METALS)) == 1
        and (obj.component or {}).get('movable', int(not (obj.component or {}).get('structure'))) == 1
        and engine.grid.distance_ft(actor.position, obj.position) <= 30
        and perceives_object(engine, actor, obj)
        and next(rays(engine, (actor.position,), (obj.position,), purpose='effect'), None) is not None}


@hook('candidate_allowed')
def hand_candidate(engine, actor, candidate, action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    rows = [r for r in typed.get('effects') or [] if r.get('type') == 'magnet_hand']
    if typed.get('source') != HAND or not rows:
        return None
    from ..object_interaction import used
    return None if not used(actor) and hand_objects(engine, actor, rows[0].get('small')) else False


@effect('magnet_hand')
def move_hand(ctx, row):
    from .object_displacement import destinations
    from ..object_interaction import claim
    from ..object_rules import label
    from . import run_strict, note
    objects = hand_objects(ctx.engine, ctx.actor, row.get('small'))
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'magnet_hand_object', ctx.actor.entity_id),
        ctx.actor, 'choice:needle.magnet_hand_object', list(objects), labels={k: label(o) for k, o in objects.items()},
        preferred=list(objects)[:1], name='Magnet Hand', feature_id=HAND,
        prompt='Magnet Hand: choose one visible unattended metal object within 30 feet. Move it up to 10 feet using your free object interaction; no cultivation points.')
    if not chosen:
        return
    obj = objects[chosen[0]]
    cells = {needle.cell_id(p): p for p in destinations(ctx.engine, obj, 10)}
    picked = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'magnet_hand_destination', obj.object_id),
        ctx.actor, 'choice:needle.magnet_hand_destination', list(cells),
        labels={k: f'({p.x}, {p.y}, {p.z}), {ctx.engine.grid.distance_ft(obj.position, p)} feet' for k,p in cells.items()},
        preferred=[k for k,p in cells.items() if p != obj.position][:1], name='Magnet Hand', feature_id=HAND,
        target_id=obj.object_id, prompt=f'Magnet Hand: choose where to move {label(obj)}, up to 10 feet. Staying in place is legal. This cannot open containers, operate mechanisms or guarantee trap safety.')
    if not picked:
        return
    if False in run_strict('object_operation_gate', ctx.engine, ctx.actor, obj, 'move', ctx.source, ctx.intent):
        return
    claim(ctx.engine, ctx.actor, ctx.source)
    if cells[picked[0]] != obj.position:
        ctx.engine._update_object(obj.model_copy(update={'position': cells[picked[0]]}), ctx.source, ctx.actor.entity_id)
    note(ctx.engine, ctx.source, ctx.actor, f'Magnet Hand moves {label(obj)} up to 10 feet.', targets=(obj.object_id,))


@hook('effect_allowed')
def sharpen_choice(ctx, row):
    target = ctx.target or ctx.damage_cache.get('_object')
    if row.get('source_modifier') != SHARPEN or target is None:
        return None
    target_id = getattr(target, 'entity_id', None) or target.object_id
    from ..object_rules import label as object_label
    target_name = getattr(target, 'display_name', None) or object_label(target)
    # A Domain bonus already supplied the expression on this triggering hit.
    from .riders_metal import domain_supplied_expression
    if ctx.target is not None and domain_supplied_expression(ctx, ctx.target):
        return None
    key = ('sharpen_type', target_id, ctx.damage_cache.get('_damage_bonus_occurrence', 0))
    picked = needle.ask(ctx.engine, ctx.intent,
        needle.checkpoint_id(ctx.engine, 'sharpen_type', ctx.actor.entity_id, target_id, ctx.damage_cache.get('_damage_bonus_occurrence', 0)),
        ctx.actor, 'choice:needle.sharpen_type', ['SLASHING', 'PIERCING'],
        labels={'SLASHING': 'Extra Slashing damage', 'PIERCING': 'Extra Piercing damage'}, preferred=['SLASHING'],
        allow_decline=True, name='Sharpen', feature_id=SHARPEN, target_id=target_id,
        prompt=f'Sharpen: {ctx.action.display_name} hit {target_name}. Add {ctx.actor.proficiency_bonus} magical Metal Qi damage, once on your turn, with no cultivation points? Choose Slashing or Piercing, or decline.')
    if not picked:
        return False
    ctx.damage_cache[key] = picked[0]
    return None


@hook('damage_type_choice')
def sharpen_type(ctx, kinds, targets):
    if ctx.source != 'passive:' + SHARPEN:
        return None
    values = [v for k,v in ctx.damage_cache.items() if isinstance(k,tuple) and k and k[0] == 'sharpen_type']
    return values[-1] if values and values[-1] in kinds else None


@hook('effect_resolution_scope')
def sharpen_origin(ctx, row):
    """The actual eligible Sharpen row produces these packet-scoped facts."""
    if row.get('source_modifier') != SHARPEN:
        return None
    from contextlib import contextmanager
    @contextmanager
    def scope():
        previous = ctx.damage_source_flags
        ctx.damage_source_flags = (*previous, 'magical', 'metal_qi')
        try:
            yield
        finally:
            ctx.damage_source_flags = previous
    return scope()


@hook('attack_magical')
def magical_sharpen(engine, source_actor_id, typed):
    from ..pending_damage import current
    packet = current(engine)
    if packet is not None and packet.source_actor_id == source_actor_id and 'metal_qi' in packet.source_flags and 'magical' in packet.source_flags:
        return True
    return None
