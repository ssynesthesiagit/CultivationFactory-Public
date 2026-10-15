"""Actual Glass base hits share owned mark capacity for creatures and objects.

Specific Faultline Strike/Glass Shard text says the hit target gains a mark;
those hit effects remain automatic, unlike the general optional surface trigger.
Only Glass Shard opts into direct object damage here; no missing normal damage
profile is invented for Faultline Strike's separate delivery modes.
"""
from copy import deepcopy
from . import effect, hook

STRIKE = 'GLASS_BASE_FAULTLINE_STRIKE'
SHARD = 'GLASS_BASE_GLASS_SHARD'
HITS = (STRIKE, SHARD)
MARK = 'Faultline Mark'


@hook('compile_action')
def compile_hits(action, info):
    source = (action.parameters.get('typed') or {}).get('source')
    if source not in HITS or source not in (info.get('owned_ids') or ()):
        return None
    params = deepcopy(action.parameters)
    for attack in params['typed'].get('effects', ()):
        if attack.get('type') != 'attack':
            continue
        for index, row in enumerate(attack.get('on_hit', ())):
            if row.get('type') == 'mark' and row.get('mark') == MARK:
                row['type'] = 'glass_base_hit_mark'
            elif source == SHARD and row.get('type') == 'damage':
                # Resolve the printed type only after the actual hit. The
                # object adapter reads this same nested ordinary damage row.
                attack['on_hit'][index] = {'type': 'glass_shard_damage', 'effects': [row]}
        if source == SHARD:
            attack.update(object_target='any', object_on_hit_effects=['glass_base_hit_mark'])
    return action.model_copy(update={'target_kind': 'ANY_CREATURE',
        'parameters': {**params, 'harmful': True}})


@effect('glass_shard_damage')
def shard_damage(ctx, row):
    if ctx.typed.get('source') == SHARD:
        from ..typed_executor import run_effects
        run_effects(ctx, row.get('effects') or [])


@effect('glass_base_hit_mark')
def hit_mark(ctx, row):
    if ctx.typed.get('source') not in HITS:
        return
    from .glass_faultline_marks import OWNER, place_object_mark
    if not any(value.get('feature_id') == OWNER
            for value in ctx.engine.typed_passive_rows.get(ctx.actor.entity_id, ())):
        return
    object_id = row.get('recipient_object_id')
    if object_id is not None:
        obj = ctx.engine.state.objects.get(object_id)
        if obj is None:
            raise ValueError('The actual hit object is no longer present.')
        place_object_mark(ctx, obj, row)
    else:
        from ..typed_executor import block_mark
        block_mark(ctx, {**row, 'type': 'mark'})


@hook('damage_type_choice')
def shard_damage_type(ctx, kinds, targets):
    if ctx.typed.get('source') != SHARD or not kinds:
        return None
    from .needle import ask, checkpoint_id
    from ..object_rules import label
    obj = ctx.damage_cache.get('_object')
    target = next(iter(targets), None)
    name = label(obj) if obj is not None else getattr(target, 'display_name', 'the hit creature')
    options = [str(kind).upper() for kind in kinds]
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'GLASS_SHARD_TYPE', ctx.actor.entity_id,
        obj.object_id if obj is not None else getattr(target, 'entity_id', '')),
        ctx.actor, 'choice:needle.glass_shard_damage_type', options,
        labels={kind: kind.title() + ' damage' for kind in options}, preferred=options[:1],
        name='Glass Shard damage', target_id=obj.object_id if obj is not None else getattr(target, 'entity_id', None),
        prompt=f'Glass Shard hits {name}: choose Piercing or Slashing damage for this shard. '
            'The target also gains your Faultline Mark; no extra Action or resource cost.')
    return selected[0] if selected else options[0]
