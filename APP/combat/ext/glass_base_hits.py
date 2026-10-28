"""Actual Glass base hits share owned mark capacity for creatures and objects.

Specific Faultline Strike/Glass Shard text says the hit target gains a mark;
those hit effects remain automatic, unlike the general optional surface trigger.
Faultline Strike's physical delivery siblings reuse the actual compiled normal
weapon/unarmed profiles. Their damage, ability, reach, thrown range and physical
identity remain native; no independent Cultivation Attack damage die is invented.
"""
from copy import deepcopy
from . import effect, hook

STRIKE = 'GLASS_BASE_FAULTLINE_STRIKE'
SHARD = 'GLASS_BASE_GLASS_SHARD'
HITS = (STRIKE, SHARD)
MARK = 'Faultline Mark'


@hook('compile_actions')
def strike_physical_deliveries(info):
    if STRIKE not in info.get('owned_ids', ()):
        return None
    template = next((action for action in info.get('actions', ())
        if (action.parameters.get('typed') or {}).get('source') == STRIKE), None)
    if template is None:
        return None
    from ..weapon_delivery import physical_weapon_id
    result = []
    for original in info.get('actions', ()):
        typed = original.parameters.get('typed') or {}
        tail = original.source_definition_id.split('.natural.', 1)[-1].split('#', 1)[0]
        natural = '.natural.' in original.source_definition_id and '.' not in tail and '+' not in tail
        weapon = typed.get('weapon') and str(typed.get('source') or '').startswith('tianxia.mortal.weapon.')
        if not (natural or weapon) or str(getattr(original.economy, 'value', original.economy)) != 'ACTION':
            continue
        attacks = [row for row in typed.get('effects', ()) if row.get('type') == 'attack']
        if len(attacks) != 1 or not any(row.get('type') == 'damage' and row.get('weapon_damage')
                for row in attacks[0].get('on_hit', ())):
            continue
        # Derived martial maneuvers are separate techniques. Bind the actual
        # physical base or its native thrown/range profile, not another talent.
        identity = physical_weapon_id(original.source_definition_id, original.parameters)
        if not natural and original.source_definition_id.split('#')[0] != identity:
            continue
        parameters = deepcopy(original.parameters)
        bound = parameters['typed']
        bound.update(source=STRIKE, weapon_source_id=identity)
        bound.pop('attack_action', None)
        parameters.pop('attack_action', None)
        attack = next(row for row in bound['effects'] if row.get('type') == 'attack')
        count = max(1, int(attack.get('count') or 1))
        attack['count'] = 1  # This Action makes one attack, not the Attack action.
        attack.setdefault('on_hit', []).append({'type': 'mark', 'mark': MARK,
            'applies_to': 'target', 'duration': {'kind': 'until_end_of_your_next_turn'}})
        parameters.update(harmful=True, faultline_delivery=original.source_definition_id, variant_of=identity,
            expected_damage=max(0, int(original.parameters.get('expected_damage') or 0) // count),
            description='Faultline Strike: make one normal ' + original.display_name +
                ' against a creature or object. Deals its normal damage and places your Faultline Mark '
                'until your next turn ends. Action; no extra Cultivation Point cost. '
                'The actual weapon keeps its normal costs, ammunition, readiness and range requirements.')
        result.append(original.model_copy(update={
            'source_definition_id': template.source_definition_id + '#delivery:' + original.source_definition_id,
            'display_name': 'Faultline Strike: ' + original.display_name,
            'parameters': parameters, 'target_kind': 'ANY_CREATURE'}))
    return result


@hook('compile_bundle')
def finish_unarmed_delivery(bundle, info):
    """The shared plain Unarmed Strike is added after compile_actions.

    Extend only the actual sealed physical profile at this final public phase;
    earlier weapon/natural siblings retain their normal immutable passes.
    """
    if not any((row.get('parameters', {}).get('typed') or {}).get('source') == STRIKE
            for row in bundle.get('action_catalog', ())):
        return bundle
    from ..gate2_runtime_models import ActionDefinition
    actions = [ActionDefinition.model_validate(row) for row in bundle['action_catalog']]
    template = next((action for action in actions
        if (action.parameters.get('typed') or {}).get('source') == STRIKE
        and not action.parameters.get('faultline_delivery')), None)
    natural = next((action for action in actions
        if action.source_definition_id.endswith('.natural.unarmed_strike')), None)
    if template is None or natural is None:
        return bundle
    existing = {action.source_definition_id for action in actions}
    made = strike_physical_deliveries({'owned_ids': [STRIKE], 'actions': [template, natural]}) or []
    made = [compile_hits(action, {'owned_ids': [STRIKE]}) for action in made
        if action.source_definition_id not in existing]
    if not made:
        return bundle
    return {**bundle, 'action_catalog': [*bundle['action_catalog'],
        *(action.model_dump(mode='json') for action in made)],
        'actor_template': {**bundle['actor_template'], 'action_ids': [
            *bundle['actor_template']['action_ids'], *(action.source_definition_id for action in made)]}}


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
        if source == SHARD or source == STRIKE and params.get('faultline_delivery'):
            attack.update(object_target='any', object_on_hit_effects=['glass_base_hit_mark'])
    return action.model_copy(update={'target_kind': 'ANY_CREATURE',
        'parameters': {**params, 'harmful': True}})


@hook('damage_type_override')
def strike_glass_damage_type(ctx, kinds, targets):
    if ctx.typed.get('source') != STRIKE or not ctx.action.parameters.get('faultline_delivery'):
        return None
    from .glass_surface_profiles import body_is_surface, profiles
    from ..item_use_checkpoint import attack_item
    delivery = ctx.action.parameters['faultline_delivery']
    item = attack_item(ctx)
    glass = ('.natural.' in delivery and body_is_surface(ctx.engine, ctx.actor))
    glass = glass or item is not None and any(profile.data.get('surface_ref') == item['object']
        and profile.data.get('surface_kind') in ('weapon', 'held_object')
        for profile in profiles(ctx.engine, ctx.actor))
    if not glass:
        return None
    from .needle import ask, checkpoint_id
    from ..object_rules import label
    obj = ctx.damage_cache.get('_object')
    target = next(iter(targets), None)
    name = label(obj) if obj is not None else getattr(target, 'display_name', 'the hit target')
    options = list(dict.fromkeys([*(str(kind).upper() for kind in kinds), 'SLASHING', 'PIERCING']))
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'FAULTLINE_STRIKE_TYPE', ctx.source,
        obj.object_id if obj is not None else getattr(target, 'entity_id', '')),
        ctx.actor, 'choice:needle.faultline_strike_damage_type', options,
        labels={kind: kind.title() + ' damage' for kind in options}, preferred=options[:1],
        name='Faultline Strike damage', target_id=obj.object_id if obj is not None else getattr(target, 'entity_id', None),
        prompt=f'Faultline Strike hits {name} using your tempered Glass Surface. Keep its normal damage type '
            'or use Slashing or Piercing for the glass edge or crystalline strike. No extra Action or resource cost.')
    return selected[0] if selected else options[0]


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
