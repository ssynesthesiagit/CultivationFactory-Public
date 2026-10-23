"""Poison Touch: an optional paid rider on committed, owned Qi Poison packets.

The catalog action is a trigger resolver, never a separately usable attack.
All saves, damage, refresh, expiry and repeat removal use native typed effects.
"""
from copy import deepcopy
from . import hook

FEATURE = 'tianxia.subpath.qi.poison_cultivator.feature.poison_touch'
PRESENCE = 'tianxia.subpath.qi.poison_cultivator.feature.lord_of_decay'
BLOCK = 'poison_touch'
QI = 'resource:core.qi'
USED = 'poison_touch_round_used'


@hook('compile_block')
def owned_row(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'choice_owner': True}]


@hook('compile_actions')
def resolver(info):
    if FEATURE not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .path_numbers import numbers_for
    numbers = numbers_for(info, 'tianxia.path.qi_cultivation')
    if int(numbers['cl']) < 6:
        return None
    record = info['mechanics'][FEATURE]
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.{FEATURE}",
        display_name='Poison Touch', owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='ANY_CREATURE', parameters={
            'poison_touch_resolver': True,
            'typed': {'source': FEATURE, 'numbers': numbers,
                      'effects': deepcopy(record['effects']), 'riders': [],
                      'duration': {'kind': 'instant'},
                      'authority_contest': {'cultivated': 1, 'bypass_biology': 1, 'decisive_gap': 6,
                                            'damage_types': ['POISON'], 'conditions': ['poisoned']}}})]


@hook('compile_action')
def receipts(action, info):
    if FEATURE not in info['owned_ids']:
        return None
    typed = action.parameters.get('typed')
    if not typed:
        return None
    changes = {}
    if typed.get('source') == PRESENCE and any(e.get('type') == 'feature_state' for e in typed.get('effects', ())):
        changes['display_name'] = 'Decaying Presence'
    enriched = {
        **typed, 'track_damage_provenance': True,
        **({'power_resource_id': 'resource:core.' + str(
            info['powering'].get(action.source_definition_id, info['primary']))}
           if (typed.get('sphere') or typed.get('forged_from') or typed.get('immortal_from'))
              and not typed.get('attack_action') else {}),
        'known_damage_features': list(info['owned_activation_features'])}
    from ..damage_provenance import qi_activation
    if qi_activation(action, enriched) and not typed.get('attack_action'):
        enriched['authority_contest'] = {'cultivated': 1, 'bypass_biology': 1, 'decisive_gap': 6,
                                         'damage_types': ['POISON'], 'conditions': ['poisoned']}
        from .path_numbers import numbers_for
        enriched['numbers'] = {**(typed.get('numbers') or {}),
                               'cl': numbers_for(info, 'tianxia.path.qi_cultivation')['cl']}
    return action.model_copy(update={**changes, 'parameters': {**action.parameters, 'typed': enriched}})


@hook('candidate_allowed')
def triggered_only(engine, actor, candidate, action):
    if action is not None and action.parameters.get('poison_touch_resolver'):
        return False
    return None


@hook('damage_dealt')
def poison_touch(ctx, target, amount):
    rows = (getattr(ctx.engine, 'typed_passive_rows', {}) or {}).get(ctx.actor.entity_id, ())
    if (not target.active or not ctx.actor.active or ctx.actor.current_hp <= 0
            or not any(r.get('feature_id') == FEATURE and r.get('block') == BLOCK for r in rows)):
        return
    action = next((ctx.engine.action_catalog[a] for a in ctx.actor.action_ids
                   if a in ctx.engine.action_catalog and ctx.engine.action_catalog[a].parameters.get('poison_touch_resolver')), None)
    if action is None:
        return
    state = ctx.engine.state
    current = state.actors.get(state.current_actor_id)
    stamp = f'{state.round_number}:{state.current_actor_id}:{current.turns_started if current else 0}'
    if ctx.actor.turn_flags.get(USED) == stamp:
        return
    qualifying = [p for p in ctx.damage_packets if str(p.get('damage_type') or '').upper() == 'POISON'
        and int(p.get('hp_damage') or 0) + int(p.get('temporary_hp_absorbed') or 0) > 0
        and (o := p.get('damage_origin') or {}).get('owned') == 1 and o.get('qi_powered') == 1
        and o.get('component') == 'technique' and o.get('feature_id') != FEATURE
        and (not o.get('weapon_delivery') or o.get('attack_index') == 1)]
    if not qualifying:
        return
    from .feature_state import override_for
    override = (override_for(ctx.actor, FEATURE, source_feature=PRESENCE)
                if PRESENCE in action.parameters['typed'].get('known_damage_features', ()) else {})
    cost = int(override.get('cost', 2))
    cl = int(action.parameters['typed']['numbers']['cl'])
    count = 3 if cl >= 17 else 2 if cl >= 11 else 1
    if int(ctx.actor.resources.get(QI, 0)) < cost:
        return
    from .choice_costs import Payment
    from .rider_choices import pick
    from ..target_knowledge import located
    payment = Payment(QI, cost)
    price = f'Spend {cost} Qi' if cost else 'Use at no Qi cost'
    selected = pick(ctx.engine, ctx.actor, 'poison_touch', 'Poison Touch', ['apply'], subject=target,
        intent=ctx.intent, labels={'apply': f'{price}: Constitution save; Poisoned on failure, {count}d6 Poison damage on success'},
        preferred=['apply'], prompt_context=payment.context(),
        automatic_options=['apply'] if target is ctx.actor or located(ctx.engine, ctx.actor, target) else [],
        prompt=f'Poison Touch: {ctx.action.display_name} dealt Poison damage to {target.display_name}. '
               f'{price}, once this turn? On a failed Constitution save, it is Poisoned for up to 1 minute '
               f'and takes {count}d6 Poison damage at the start of its turns; an end-of-turn Constitution save ends the effect. '
               f'On success it takes {count}d6 Poison damage without the condition.'
               + (' Start-of-turn damage becomes 4d6 while your Decaying Presence is active.' if override else ''))
    if not selected:
        return
    payment.pay(ctx.engine, ctx.actor, action.source_definition_id)
    ctx.actor.turn_flags[USED] = stamp  # before the rider's own packets; no recursive delivery
    typed = deepcopy(action.parameters['typed'])
    # The active-state consumer changes only the start-turn payload; success
    # damage retains the ordinary printed CL scaling.
    effects = typed['effects']
    save = effects[0]
    save['on_success'][0]['dice']['count'] = count
    save['on_fail'][0]['turn_start_effects'][0]['dice']['count'] = count
    from ..typed_executor import Context, run_effects
    run_effects(Context(ctx.engine, ctx.actor, action, ctx.intent, typed, [target], target, {}), effects)


@hook('ongoing_turn_start_effects')
def active_tick(effects, ctx, condition):
    if not ctx.action.parameters.get('poison_touch_resolver'):
        return None
    typed = ctx.action.parameters['typed']
    if PRESENCE not in typed.get('known_damage_features', ()):
        return None
    from .feature_state import override_for
    override = override_for(ctx.actor, FEATURE, source_feature=PRESENCE)
    if 'tick_dice' not in override:
        return None
    result = deepcopy(effects)
    result[0]['dice']['count'] = int(override['tick_dice'])
    return result
