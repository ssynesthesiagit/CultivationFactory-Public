"""Sealed combat grants for the fifth alphabetical Insight lane.

Only newly reviewed, hash-gated rows opt in. Uses native payment, healing,
state-event, start-turn, roll-rewrite and confirmed-hit checkpoints.
"""
from . import hook, effect
from .passive_rows import row_of

BLOCK = 'insights_five'
PREFIX = 'insight.legacy-'
FLESH = PREFIX + 'flesh-regenerator'
CIRCULATION = PREFIX + 'heavenly-circulation'
RESERVES = PREFIX + 'hidden-reserves'
SINEWS = PREFIX + 'immortals-sinews'
BONES = PREFIX + 'iron-bones'
FIST = PREFIX + 'mountain-crushing-fist'
MUSIC = PREFIX + 'musical-resonance'
SCARS = 'insight.lightning-scarred-meridians'


def owned(engine, actor, feature):
    return row_of(engine, actor.entity_id, BLOCK, feature) if actor is not None else None


def stamp(engine):
    return int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)


@hook('compile_block')
def compile_grants(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'kind': row['feature_id'], 'numbers': {k: numbers[k] for k in ('pb','cl','key_mod')}, 'choice_owner': True,
             'player_outcome': spec['outcome']}]


def choose(engine, actor, feature, prompt, options=('use',), labels=None, payment=None, target=None, optional=True,
           name=None, prompt_context=None):
    from .needle import ask, checkpoint_id
    return ask(engine, getattr(engine, '_active_intent', None),
               checkpoint_id(engine, feature, target.entity_id if target else actor.entity_id),
               actor, 'choice:needle.' + feature.split('.')[-1], list(options),
               labels=labels or {'use': prompt}, name=name or prompt.partition(':')[0],
               feature_id=feature, prompt=prompt, allow_decline=optional, default='first',
               target_id=target.entity_id if target else actor.entity_id, payment=payment,
               prompt_context=prompt_context)


def pools(actor):
    from ..typed_executor import CP_POOLS
    return [pool for pool in CP_POOLS if actor.resource_maximums.get(pool, 0) > 0
            and actor.resources.get(pool, 0) < actor.resource_maximums[pool]]


@hook('turn_boundary_start')
def start_recovery(engine, actor):
    from .choice_costs import payable
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..typed_executor import Context, block_healing
    row = owned(engine, actor, FLESH)
    used = 'insights_flesh_round_uses'
    if (row and 0 < actor.current_hp * 2 < actor.maximum_hp
            and int(actor.turn_flags.get(used, 0)) < int(row['numbers']['pb'])):
        price = payable(actor, 'resource:core.stamina', 1)
        if price and choose(engine, actor, FLESH,
                            'Flesh Regenerator: spend 1 Stamina to regain 5 Hit Points at the start of your turn?', payment=price):
            price.pay(engine, actor, FLESH)
            actor.turn_flags[used] = int(actor.turn_flags.get(used, 0)) + 1
            action = ActionDefinition(source_definition_id=FLESH, display_name='Flesh Regenerator',
                                      owner_id=actor.entity_id, economy=EconomyKind.NONE,
                                      resolution_kind='TYPED', target_kind='SELF')
            block_healing(Context(engine, actor, action, getattr(engine, '_active_intent', None),
                                  {'source': FLESH, 'numbers': row['numbers'], 'duration': {'kind': 'instant'}},
                                  [actor], actor, {}), {'type': 'healing', 'applies_to': 'self', 'flat': 5})
    row = owned(engine, actor, CIRCULATION)
    qi = 'resource:core.qi'
    if (row and qi in actor.resources and actor.resources[qi] * 2 < actor.resource_maximums[qi]
            and not actor.turn_flags.get('insights_circulation_round_used')):
        # Printed automatic recovery, no action or Reaction.
        actor.turn_flags['insights_circulation_round_used'] = 1
        engine._gain_resource(actor, qi, max(0, int(row['numbers']['cl']) + int(row['numbers']['key_mod'])), CIRCULATION)


@hook('state_event')
def after_damage(engine, event):
    if event.event_type != 'DAMAGE_COMMITTED':
        return
    from ..relations import ENEMY, relation
    payload = event.payload or {}
    amount = int(payload.get('hp_damage') or 0) + int(payload.get('temporary_hp_absorbed') or 0)
    if amount <= 0:
        return
    for aid in event.target_ids:
        actor = engine.state.actors.get(aid)
        row = owned(engine, actor, RESERVES)
        if (row and int(payload.get('hp_damage') or 0) > 0 and actor.current_hp * 2 <= actor.maximum_hp
                and not actor.turn_flags.get('insights_reserves_round_used')):
            from ..resource_labels import resource_name
            available = pools(actor)
            if available:
                pb = int(row['numbers']['pb'])
                picked = choose(engine, actor, RESERVES,
                                f'Hidden Reserves: regain {2 * pb} cultivation points in one active Path pool (once between Full Cultivation Sessions)?',
                                options=available, labels={p: f'Regain {2 * pb} {resource_name(p)}' for p in available})
                if picked:
                    actor.turn_flags['insights_reserves_round_used'] = 1
                    engine._gain_resource(actor, picked[0], 2 * pb, RESERVES)
        row = owned(engine, actor, SCARS)
        if row and str(payload.get('damage_type', '')).upper() == 'LIGHTNING':
            receipt = defense_receipt(engine, actor, 'LIGHTNING', SCARS)
            if (receipt is not None and receipt.get('first')
                    and actor.turn_flags.get('insights_scars_round_first') != engine.state.round_number):
                actor.turn_flags['insights_scars_round_first'] = engine.state.round_number
                actor.turn_flags['insights_scars_round_variant'] = 'duplicate' if receipt.get('independent') else 'recover'
                if receipt.get('independent'):
                    actor.turn_flags['insights_scars_round_reduction'] = engine.state.round_number
        source = engine.state.actors.get(event.actor_id)
        if (row and str(payload.get('damage_type', '')).upper() == 'LIGHTNING'
                and source is not None and relation(engine, actor, source) == ENEMY
                and actor.turn_flags.get('insights_scars_round_recovery') != engine.state.round_number
                and not duplicate_variant(engine, actor, event.source_definition_id, event.actor_id)):
            qi = 'resource:core.qi'
            if qi in actor.resources:
                actor.turn_flags['insights_scars_round_recovery'] = engine.state.round_number
                engine._gain_resource(actor, qi, 1, SCARS)


def other_resistance(engine, actor, kind, feature, typed=None, source_actor_id=None):
    """Presence of an independent Resistance grant; never count this Insight twice."""
    from ..typed_reactions import _defense_applies
    from .. import ext
    rows = list(getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ()))
    rows += [r for result in ext.run('damage_defenses', engine, actor, kind, typed or {}, source_actor_id) for r in (result or ())]
    return (kind in {str(k).upper() for k in actor.damage_resistances}
            or any(m.target_field in ('damage_resistance', 'damage_resistance_next') and str(m.value).upper() == kind
                   and m.source_definition_id != feature for m in actor.modifiers.values())
            or any(r.get('feature_id') != feature and r.get('kind') == 'resistance'
                   and _defense_applies(engine, actor, r, kind, typed or {}, source_actor_id) for r in rows))


@hook('damage_defenses')
def resistances(engine, target, kind, typed, source_actor_id):
    if owned(engine, target, BONES) and kind == 'BLUDGEONING':
        return [{'feature_id': BONES, 'kind': 'resistance', 'damage_types': [kind]}]
    if owned(engine, target, SCARS) and kind == 'LIGHTNING':
        return [{'feature_id': SCARS, 'kind': 'resistance', 'damage_types': [kind]}]
    return None


@hook('damage_reduction')
def duplicate_resistance(engine, target, kind, typed, source_actor_id, applied=False):
    feature = BONES if kind == 'BLUDGEONING' else SCARS if kind == 'LIGHTNING' else None
    row = owned(engine, target, feature) if feature else None
    if not row:
        return None
    receipt = defense_receipt(engine, target, kind, feature)
    independent = receipt['independent'] if receipt is not None else other_resistance(engine, target, kind, feature, typed, source_actor_id)
    if not independent:
        return None
    if feature == SCARS:
        key = 'insights_scars_round_reduction'
        if (receipt is not None and not receipt['first']) or target.turn_flags.get(key) == engine.state.round_number:
            return None
    return int(row['numbers']['pb'])


@hook('ability_check_mode')
def strength_checks(engine, actor, ability, skill, against):
    return 'ADVANTAGE' if owned(engine, actor, SINEWS) and str(ability).upper() == 'STR' else None


@hook('save_mode')
def strength_saves(engine, subject, ability, dc, source, context):
    return 'ADVANTAGE' if owned(engine, subject, SINEWS) and str(ability).upper() == 'STR' else None


@hook('after_hit_choice')
def crushing_fist(ctx, target, kind):
    from .choice_costs import payable
    from ..typed_executor import run_effects
    actor, engine = ctx.actor, ctx.engine
    row = owned(engine, actor, FIST)
    if (not row or kind != 'unarmed' or target is None or not target.active
            or actor.turn_flags.get('insights_fist_turn') == stamp(engine)):
        return
    price = payable(actor, 'resource:core.stamina', 2)
    if not price or not choose(engine, actor, FIST,
                               f'Mountain-Crushing Fist: spend 2 Stamina for 2d8 extra Bludgeoning damage and a Strength save or push {target.display_name} up to 10 feet (once per turn)?',
                               payment=price, target=target):
        return
    actor.turn_flags['insights_fist_turn'] = stamp(engine)
    price.pay(engine, actor, FIST)
    run_effects(ctx.on_hit_context(target), [
        {'type': 'extra_damage', 'applies_to': 'target', 'dice': {'count': 2, 'sides': 8}, 'damage_types': ['bludgeoning']},
        {'type': 'save', 'applies_to': 'target', 'ability': 'str', 'dc': 'technique_save_dc',
         'on_fail': [{'type': 'insights_five_push', 'applies_to': 'target'}]}])



# Printed outcome choices share the one native d20 rewrite owner.
from .d20_rewrite import Rule, register

WILL = PREFIX + 'will-manifestation'
LUCK = PREFIX + 'heavens-luck'
UNBROKEN = PREFIX + 'unbroken-frame'


def unbroken_release(engine, holder, rc, result):
    actor = holder.actor
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id == 'condition:typed.prone':
            actor.conditions.pop(iid)
            engine._append_event('CONDITION_REMOVED', holder.feature_id, actor_id=actor.entity_id,
                                 target_ids=(actor.entity_id,), payload={'condition_id': condition.condition_id, 'instance_id': iid})
    grips = [c for c in actor.conditions.values() if c.condition_id in ('condition:typed.grappled', 'condition:typed.restrained', 'condition:typed.pinned')
             or (c.data or {}).get('rule', {}).get('grapple')]
    if not grips:
        return
    groups = {}
    for condition in grips:
        groups.setdefault((condition.source_definition_id, condition.source_actor_id), []).append(condition)
    def group_label(group):
        primary = next((c for c in group if c.condition_id == 'condition:typed.pinned'), None) or \
                  next((c for c in group if c.condition_id == 'condition:typed.restrained'), None) or group[0]
        condition_name = primary.condition_id.removeprefix('condition:typed.').replace('_', ' ').title()
        custom = (primary.data or {}).get('label')
        source = engine.state.actors.get(primary.source_actor_id)
        source_name = source.display_name if source is not None else 'an unknown creature'
        action = engine.action_catalog.get(primary.source_definition_id)
        ability_name = getattr(action, 'display_name', None) or str(primary.source_definition_id or 'an effect').replace('-', ' ').title()
        return f'{custom or condition_name} by {source_name} ({ability_name})'
    representatives = {key: group[0] for key, group in groups.items()}
    from .choice_prompt import action_context
    trigger = engine.action_catalog.get(rc.source_id)
    trigger_actor = rc.source_actor or (engine.state.actors.get(trigger.owner_id) if trigger is not None else None)
    trigger_context = action_context(engine, trigger_actor, str(rc.source_id or ''), actor, action=trigger)
    picked = choose(engine, actor, UNBROKEN, 'Unbroken Frame: choose one effect causing you to be Grappled or Restrained to end.',
                    optional=False, options=[c.instance_id for c in representatives.values()],
                    labels={c.instance_id: group_label(groups[key]) for key, c in representatives.items()},
                    name='Unbroken Frame', prompt_context=trigger_context)
    if not picked:
        return
    selected = next(c for c in grips if c.instance_id == picked[0])
    # One source-owned hold can have Grappled, Pinned, and Restrained companions.
    for c in grips:
        if (c.source_definition_id, c.source_actor_id) == (selected.source_definition_id, selected.source_actor_id):
            actor.conditions.pop(c.instance_id)
            engine._append_event('CONDITION_REMOVED', UNBROKEN, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={'condition_id': c.condition_id, 'instance_id': c.instance_id})


register(Rule(WILL, 'Will Manifestation', feature=WILL, rolls=('save',), when='failed',
              op='nat20', outcome='success', limit='fight'))
register(Rule(LUCK, "Heaven's Luck", feature=LUCK, rolls=('save', 'attack'), when='any',
              op='reroll', limit='fight', checkpoint='D20_REWRITE_ROLL',
              ai=lambda engine, holder, rc: rc.succeeded() is False))
register(Rule(UNBROKEN, 'Unbroken Frame', feature=UNBROKEN, rolls=('save',), abilities=('CON',),
              when='failed', op='nat20', outcome='success', limit='fight', after=unbroken_release))

@hook('state_event')
def heart_demon_repeat_success(engine, event):
    """A successful repeat save ends the curse and grants caster-specific immunity."""
    feature = PREFIX + 'heart-demon-manifestation'
    if event.event_type != 'CONDITION_REMOVED' or not (event.payload or {}).get('repeat_save'):
        return
    action = engine.action_catalog.get(event.source_definition_id)
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if typed.get('source') != feature or (event.payload or {}).get('condition_id') != 'condition:typed.frightened':
        return
    from ..typed_executor import Context, run_effects
    caster = engine.state.actors.get(action.owner_id)
    for aid in event.target_ids:
        target = engine.state.actors.get(aid)
        if caster is not None and target is not None:
            run_effects(Context(engine, caster, action, getattr(engine, '_active_intent', None), typed, [target], target, {}),
                        [{'type':'resist_ability', 'applies_to':'target', 'mode':'immune', 'name':'Heart Demon Manifestation',
                          'duration':{'kind':'hours','amount':24}}])

@effect('insights_five_push', harmful=True)
def fist_push(ctx, row):
    from ..typed_executor import run_effects
    target = ctx.target
    if target is None or not target.active:
        return
    picked = choose(ctx.engine, ctx.actor, FIST,
                    f'Mountain-Crushing Fist: choose how far to push {target.display_name}, up to 10 feet; no extra cost.',
                    options=['10','5'], labels={'10':'Push up to 10 feet','5':'Push up to 5 feet'}, target=target)
    if picked:
        run_effects(ctx, [{'type':'directed_forced_movement','applies_to':'target','distance_ft':int(picked[0])}])



@hook('carrying_capacity_scale')
def capacity_scale(info):
    owned_ids = info['owned_ids']
    scale = 1
    if SINEWS in owned_ids:
        scale *= 2
    if PREFIX + 'titans-grip' in owned_ids:
        # Small and Medium share ordinary capacity; Tiny -> Small and every
        # larger virtual step double it. Physical footprint is unchanged.
        size = str((info['owner_sheet'].get('identity') or {}).get('size') or 'medium').lower()
        if size != 'small':
            scale *= 2
    return scale if scale != 1 else None

@hook('compile_action')
def heart_demon_recipient_policy(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    feature = PREFIX + 'heart-demon-manifestation'
    if typed.get('source') != feature or feature not in info['owned_ids']:
        return None
    return action.model_copy(update={'parameters':{**action.parameters, 'harmful':True,
                                                   'insights_five_enemy_auto':1}})


@hook('candidate_allowed')
def heart_demon_auto_targets(engine, actor, candidate, action):
    if not (getattr(action,'parameters',None) or {}).get('insights_five_enemy_auto'):
        return None
    from .needle import ai_controlled
    from ..relations import relation, ENEMY
    if not ai_controlled(engine,actor):
        return None  # human retains the printed any-creature target domain
    return bool(candidate.target_ids) and all(target is not None and relation(engine,actor,target)==ENEMY
               for aid in candidate.target_ids for target in [engine.state.actors.get(aid)])


def defense_receipt(engine, target, kind, feature):
    from ..pending_damage import current, packet_scratch
    packet, scratch = current(engine), packet_scratch(engine)
    if packet is None or scratch is None or packet.target_id != target.entity_id or packet.damage_type != kind:
        return None
    return scratch.get(('insights_five_defense',target.entity_id,kind,feature))


@hook('before_damage_defenses')
def snapshot_independent_resistance(engine, target, amount, kind, source, source_actor_id):
    from ..pending_damage import current, packet_scratch
    feature = BONES if str(kind).upper() == 'BLUDGEONING' else SCARS if str(kind).upper() == 'LIGHTNING' else None
    if not feature or not owned(engine,target,feature):
        return
    packet, scratch = current(engine), packet_scratch(engine)
    if packet is None or scratch is None or packet.target_id != target.entity_id:
        return
    kind = str(kind).upper()
    typed = (getattr(engine.action_catalog.get(source),'parameters',None) or {}).get('typed') or {}
    independent = other_resistance(engine,target,kind,feature,typed,source_actor_id)
    first = True
    if feature == SCARS:
        first = target.turn_flags.get('insights_scars_round_first') != engine.state.round_number
    scratch[('insights_five_defense',target.entity_id,kind,feature)] = {'independent':independent,'first':first}


def duplicate_variant(engine, actor, source, source_actor_id):
    if actor.turn_flags.get('insights_scars_round_first') == engine.state.round_number:
        return actor.turn_flags.get('insights_scars_round_variant') == 'duplicate'
    typed = (getattr(engine.action_catalog.get(source),'parameters',None) or {}).get('typed') or {}
    return other_resistance(engine,actor,'LIGHTNING',SCARS,typed,source_actor_id)
