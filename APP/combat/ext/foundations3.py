"""Foundation combat boons and objective completed-event resource triggers.

Scope tags name this save's printed consequence, never an affinity sphere or
an action-name guess. Fresh reviewed effects opt in; frozen catalogs remain
unchanged. Native pressure owns generation, cap, round allowance and expiry.
Outward support is credited from its committed healing/temp-HP or reduction receipt so the
actual provider receives the trigger even when it resolves as a reaction
during another creature's turn.
"""
from . import effect, hook, note


def _feed_bonus(engine, holder, rc):
    return int(holder.numbers['pb']) + int(holder.numbers['key_mod'])


def _feed_eligible(engine, holder, rc):
    """Only the native caller's explicit Concentration source is supported.

    No CON-save, action-name or skill inference stands in for a maintenance
    contract. Future supported callers must carry an explicit native contract.
    Payment uses the existing prior-event guard, not another Dew ledger.
    """
    from ..gate2_engine import SYSTEM_CONCENTRATION
    from ..typed_reactions import _holds
    from .d20_rewrite import pool_id
    resource = pool_id(holder.actor, 'spirit_source_dew')
    return (rc.kind == 'save' and rc.source_id == SYSTEM_CONCENTRATION
            and rc.ability == 'CON' and resource is not None
            and _holds(engine, holder.actor, resource, 1))


def _feed_accept(engine, holder, rc):
    from .needle import ask, CHOICE
    return bool(ask(engine, None, f'foundations3_feed_accept:{rc.roll.roll_id}:{holder.actor.entity_id}',
        rc.roller, CHOICE + 'foundations3_feed_accept', ['accept'], allow_decline=True,
        labels={'accept': 'Accept the bonus to this failed Concentration save'},
        target_id=rc.roller.entity_id, feature_id=holder.feature_id, name='Feed the Living Circuit',
        prompt=f'Feed the Living Circuit: {rc.roller.display_name}, accept {holder.actor.display_name}\'s '
               f'help with your failed Concentration saving throw (total {rc.total}, DC {rc.dc})? '
               f'They spend a Reaction and 1 Spirit-Source Dew from an earlier event to add {_feed_bonus(engine, holder, rc):+d}. '
               f'If this turns your failure into a success, you gain {holder.numbers["pb"]} temporary Hit Points. '
               'You pay no action or resource.'))


def _feed_settled(engine, holder, rc, result, amount):
    """Retain a primitive receipt; the declared native save decides the reward."""
    from dataclasses import replace
    if (rc.dc is not None and rc.total < rc.dc <= rc.total + amount
            and replace(rc, roll=result).succeeded() is True):
        from ..paid_relocation import preserve_pending
        preserve_pending(engine, '_foundations3_feed_rewards')
        engine.__dict__.setdefault('_foundations3_feed_rewards', {})[result.roll_id] = {
            'owner': holder.actor.entity_id, 'subject': rc.roller.entity_id,
            'source': holder.feature_id, 'pb': int(holder.numbers['pb'])}


@hook('event', nested=True)
def feed_declared_save(engine, event_type, kwargs):
    """Native SAVE_ROLLED includes every later numeric/forced outcome adjustment."""
    if event_type != 'SAVE_ROLLED' or not engine.__dict__.get('_foundations3_feed_rewards'):
        return
    payload = kwargs.get('payload') or {}
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, '_foundations3_feed_rewards')
    rewards = engine.__dict__['_foundations3_feed_rewards']
    receipt = rewards.pop(payload.get('roll_id'), None)
    if not rewards:
        engine.__dict__.pop('_foundations3_feed_rewards', None)
    if receipt is not None and receipt['subject'] == kwargs.get('actor_id') and payload.get('success') is True:
        subject = engine.state.actors[receipt['subject']]
        engine._grant_temp_hp(subject, receipt['pb'], receipt['source'], receipt['owner'])


@hook('roll_context_end')
def feed_clear_receipt(engine, context):
    """No pending reward survives a native save scope, including rollback/escape."""
    if context.get('source_id') != 'system:combat.concentration':
        return
    # roll_context_end runs after restoring the enclosing public context. A
    # nested save for the same creature must leave its parent's receipt intact.
    enclosing = engine.d20_context() or {}
    if (enclosing.get('source_id') == context.get('source_id')
            and enclosing.get('actor_id') == context.get('actor_id')):
        return
    rewards = engine.__dict__.get('_foundations3_feed_rewards') or {}
    owned = [rid for rid, row in rewards.items() if row['subject'] == context.get('actor_id')]
    if owned:
        from ..paid_relocation import preserve_pending
        preserve_pending(engine, '_foundations3_feed_rewards')
        for rid in owned:
            rewards.pop(rid, None)
        if not rewards:
            engine.__dict__.pop('_foundations3_feed_rewards', None)


from .d20_rewrite import Rule, register

register(Rule('foundations3_feed', 'Feed the Living Circuit', rolls=('save',),
    who='ally', range_ft=30, when='failed', op='bonus', reaction=True,
    checkpoint='D20_ROLL_BONUS', costs=((('spirit_source_dew', 1),),),
    guard=_feed_eligible, accept=_feed_accept, bonus=_feed_bonus,
    ai=lambda engine, holder, rc: rc.dc is not None and rc.total < rc.dc <= rc.total + _feed_bonus(engine, holder, rc),
    after_bonus=_feed_settled))

BOON = 'condition:typed.foundations3_boon.'
SUPPORT_RANGE_FT = 30
OPEN_CHANNELS_RANGE_FT = 60


@hook('compile_bundle')
def compile_open_channels_hp(bundle, info):
    """Replace the source-bound standing Vessel contribution with 2*PB.

    Sheet.maximum is a final total, not an inferred chassis. Stage2's actual
    contribution must be known before replacing it; unknown totals are kept.
    """
    if not any(row.get('block') == 'foundations3_open_channels'
               for row in bundle['typed_passives']):
        return None
    from copy import deepcopy
    from .foundation_values import foundation_hp_in_maximum
    result = deepcopy(bundle)
    included = foundation_hp_in_maximum(info['owner_sheet'])
    desired = 2 * int(info['numbers']['pb'])
    if included is None or included > desired:
        result['diagnostics']['notes'].append(
            'Open Source Channels makes the Origin-Spirit Vessel maximum-HP increase twice your Proficiency Bonus. '
            'This sheet does not establish how much Vessel already adds, so its stated maximum is kept.')
        return result
    bonus = desired - included
    result['actor_template']['maximum_hp'] += bonus
    for row in result['typed_passives']:
        if row.get('block') == 'foundations3_open_channels':
            row.update({'vessel_hp_in_sheet': included, 'vessel_hp_total': desired, 'vessel_hp_added': bonus})
    result['diagnostics']['notes'].append(
        f'Open Source Channels: Origin-Spirit Vessel adds a total of {desired} maximum Hit Points '
        f'({included} already in the sheet; {bonus} added here), with no extra action or resource cost.')
    return result


HEART_ASH = 'foundation.red_lotus_ash_returning_v0_2B.refined_red_lotus_heart_ash'
CAUTERY = 'foundation.red_lotus_ash_returning_v0_2B.red_lotus_cautery'
ASH_POOL = 'resource:foundation.funeral_ash'


@hook('compile_passives')
def compile_heart_ash(passives, info):
    """Seal only this owned rider; the base reaction keeps its own payment."""
    if HEART_ASH not in info['owned_ids']:
        return passives
    return [*passives, {'block': 'foundations3_heart_ash', 'feature_id': HEART_ASH,
                       'pb': int(info['numbers']['pb'])}]


@hook('compile_bundle')
def heart_ash_maximum_hp(bundle, info):
    """Replace the source-bound initial HP contribution at the owned Refined tier.

    The character calculator already included the initial contribution. Only
    its authenticated mechanics projection establishes that amount; legacy
    sheets without it retain their supplied HP rather than guessing a base.
    The saved bundle seals the result, so reload never reapplies the increase.
    """
    if not any(row.get('feature_id') == HEART_ASH
               and row.get('block') == 'foundations3_heart_ash'
               for row in bundle.get('typed_passives', [])):
        return bundle
    foundation = info['owner_sheet'].get('foundation') or {}
    mechanics = foundation.get('mechanics')
    if not isinstance(mechanics, dict):
        return bundle
    from non_sphere_authority.foundation_mechanics import (
        resolve_initial_foundation_mechanics, verified_foundation_records,
    )
    from ..canonical import canonical_sha256
    identity = 'red_lotus_ash_returning_v0_2B'
    initial = mechanics.get('initial_state') or {}
    expected = resolve_initial_foundation_mechanics(
        verified_foundation_records()[identity], initial.get('active_expression_path_ids') or [],
        stage=initial.get('stage'))
    if canonical_sha256(mechanics) != canonical_sha256(expected):
        from app.core import FoundryError
        raise FoundryError('COMBAT_FOUNDATION_HP_PROJECTION_INVALID',
                           'The Foundation Hit Point contribution does not match its source.', status_code=409)
    from stage2.formulas import evaluate_formula
    pb = int(info['numbers']['pb'])
    included = sum(evaluate_formula(row['formula']['root'], {'pb': pb}).value
                   for row in expected['hp_maximum_modifiers'])
    bundle['actor_template']['maximum_hp'] += 2 * pb - included
    return bundle


@hook('damage_context_pending_reaction_rank')
def heart_ash_reduction(engine, reactor, row, packet, intent):
    """Select the one Cautery reduction, conditional on native prior paid-spend eligibility.

    This pure preview supplies a value to the generic reaction. That native
    caller commits it only after consent and successful base resource payment.
    No Strike producer or base Cautery trigger policy is manufactured here.
    """
    if row.get('feature_id') != CAUTERY or reactor.entity_id != packet.target_id:
        return None
    owned = next((r for r in engine.typed_passive_rows.get(reactor.entity_id, [])
                  if r.get('block') == 'foundations3_heart_ash' and r.get('feature_id') == HEART_ASH), None)
    if owned is None or not packet.hostile or packet.source_flags.intersection({'voluntary', 'training', 'self_inflicted'}):
        return None
    if row.get('costs') != [{'resource_id': ASH_POOL, 'amount': 1}] or packet.resource_before(reactor.entity_id, ASH_POOL) < 1:
        return None
    from .prior_event_resources import prior_generated_units
    if prior_generated_units(engine, reactor.entity_id, ASH_POOL,
            'passive:foundation.red_lotus_ash_returning_v0_2B.generate_funeral_ash',
            before_sequence=packet.event_sequence, transaction_id=packet.transaction_id) < 1:
        return None
    return {'reduction_bonus': int(owned['pb'])}

# First proven native support-value contract only. Other printed support types
# require their own native value/recipient provenance before admission here.
SPIRIT_VESSEL = 'foundation.origin_spirit_body_v0_2B.origin_spirit_vessel'
SPIRIT_VALUE_BLOCK = 'foundations3_spirit_value'
SPIRIT_VALUE_ROUND = 'foundation_round_origin_spirit_support_value'
SPIRIT_VALUE_PENDING = 'origin_spirit_support_value_pending'
SPIRIT_TEMP_HP_METHOD = 'LIFE_BASE_BORROWED_BREATH'


@hook('compile_block')
def compile_spirit_value(block, spec, row, numbers):
    if block != SPIRIT_VALUE_BLOCK or row['feature_id'] != SPIRIT_VESSEL:
        return None
    # Keep the reviewed residual clauses visible; this is no whole-owner seal.
    return [{**row, 'kind': 'temporary_hp', 'pb': int(numbers['pb']), 'keeps_compiling': True}]


@hook('temp_hp_offered_bonus')
def spirit_temp_hp_value(engine, subject, amount, source_id, source_actor_id, *, consume):
    """Choose one actual outward Life Temporary HP value; estimates never spend."""
    from .passive_rows import row_of
    owner = engine.state.actors.get(source_actor_id)
    if owner is None:
        return None
    row = row_of(engine, owner.entity_id, SPIRIT_VALUE_BLOCK, 'temporary_hp')
    action = engine.action_catalog.get(source_id)
    typed = (action.parameters.get('typed') or {}) if action else {}
    if (not row or row['feature_id'] != SPIRIT_VESSEL or amount <= 0
            or subject.entity_id == owner.entity_id or not owner.active or owner.current_hp <= 0
            or action is None or action.owner_id != owner.entity_id or source_id not in owner.action_ids
            or typed.get('source') != SPIRIT_TEMP_HP_METHOD
            or typed.get('sphere') != 'tianxia.sphere.life'
            or not origin_spirit_support_in_range(engine, owner, subject)
            or owner.turn_flags.get(SPIRIT_VALUE_ROUND) == engine.state.round_number):
        return None
    bonus = max(0, int(row['pb']))
    if not consume:
        return bonus
    # Native _grant_temp_hp owns interception and the committed event. A pure
    # number preview has no intent and cannot create a round receipt or prompt.
    intent = getattr(engine, '_active_intent', None)
    if intent is None or bonus == 0:
        return None
    from . import ai_controlled
    from .needle import ask, checkpoint_id, CHOICE
    chosen = ask(engine, intent,
        checkpoint_id(engine, 'ORIGIN_SPIRIT_SUPPORT_VALUE', source_id, subject.entity_id),
        owner, CHOICE + 'origin_spirit_support_value', ['increase'], allow_decline=True,
        automatic=ai_controlled(engine, owner),
        name='Origin-Spirit Vessel', feature_id=SPIRIT_VESSEL, target_id=subject.entity_id,
        preferred=['increase'],
        labels={'increase': f'Add {bonus} Temporary Hit Points for {subject.display_name}; use your once-per-round bonus'},
        prompt=f'Use Origin-Spirit Vessel on {action.display_name} for {subject.display_name}? Add {bonus} Temporary Hit Points, with no extra action or resource cost; one value this round.',
        prompt_context={'source_definition_id': source_id, 'action_name': action.display_name,
                        'action_actor_id': owner.entity_id, 'affected_id': subject.entity_id})
    if not chosen:
        return None
    # Primitive transient transport, replayed by the enclosing transaction.
    # The allowance is spent only by the actual native grant event below.
    owner.turn_flags[SPIRIT_VALUE_PENDING + '_source'] = str(source_id)
    owner.turn_flags[SPIRIT_VALUE_PENDING + '_target'] = str(subject.entity_id)
    owner.turn_flags[SPIRIT_VALUE_PENDING + '_bonus'] = bonus
    return bonus


@hook('event', nested=True)
def spirit_value_committed(engine, event_type, kwargs):
    if event_type != 'TEMP_HP_GRANTED':
        return
    owner = engine.state.actors.get(kwargs.get('actor_id'))
    if owner is None or owner.turn_flags.get(SPIRIT_VALUE_PENDING + '_source') != kwargs.get('source_definition_id'):
        return
    target_id = owner.turn_flags.get(SPIRIT_VALUE_PENDING + '_target')
    if tuple(kwargs.get('target_ids') or ()) != (target_id,):
        return
    bonus = owner.turn_flags.pop(SPIRIT_VALUE_PENDING + '_bonus')
    source = owner.turn_flags.pop(SPIRIT_VALUE_PENDING + '_source')
    owner.turn_flags.pop(SPIRIT_VALUE_PENDING + '_target')
    owner.turn_flags[SPIRIT_VALUE_ROUND] = int(engine.state.round_number)
    target = engine.state.actors[target_id]
    note(engine, SPIRIT_VESSEL, owner,
         f'Origin-Spirit Vessel adds {bonus} to the Temporary Hit Points from {engine.action_catalog[source].display_name} for {target.display_name}; its one-value bonus is used this round.',
         (target,), receipt_kind='origin_spirit_support_value', method=SPIRIT_TEMP_HP_METHOD,
         support_source=source, beneficiary=target_id, value_kind='temporary_hp',
         bonus=bonus, round=int(engine.state.round_number))


def _hostile(a, b):
    return a is not None and b is not None and a.team_id != b.team_id


def _threat(action):
    """Require a sealed harmful outcome; a bare/staged roll is not pressure."""
    if action is None:
        return False
    damage = action.damage
    if damage is not None and damage.count * damage.sides + damage.modifier > 0:
        return True
    typed = action.parameters.get('typed') or {}
    if typed.get('weapon'):
        return True
    def harmful(value):
        if isinstance(value, dict):
            kind = value.get('type')
            if kind in {'damage', 'extra_damage'} and (value.get('dice') or int(value.get('flat') or 0) > 0
                    or value.get('formula') not in (None, '', 'none')):
                return True
            if kind == 'condition' and value.get('condition') in {
                    'poisoned','frightened','charmed','prone','grappled','restrained',
                    'stunned','paralyzed','incapacitated','blinded','deafened','exhaustion'}:
                return True
            if kind == 'forced_movement' and int(value.get('distance_ft') or 0) > 0:
                return True
            return any(harmful(v) for v in value.values() if isinstance(v, (dict,list)))
        return isinstance(value, list) and any(harmful(v) for v in value)
    return harmful(typed.get('effects') or [])


def _boons(subject):
    return [c for c in subject.conditions.values() if c.condition_id.startswith(BOON)]


def _boon_label(kind, grantor):
    """Name the roll that spends a boon and the deadline that ends it."""
    deadline = f"expires at the start of {grantor}'s next turn"
    return {
        'mirror': f'Advantage on your next save against fear, charm, illusions, dreams, curses, or forced spiritual movement; {deadline}.',
        'lotus': f'Advantage on your next save against poison, disease, rot, polluted water, sickness exhaustion, failed medicine backlash, or terrain contamination; {deadline}.',
        'ash': f'Advantage on your next save against fear, poison, disease, fire, necrotic harm, blood-loss, despair, or corpse/battlefield contamination; {deadline}.',
        'bitter': 'Advantage on your next attack, save, or ability check against a hostile creature; expires at the end of this turn.',
    }[kind]


def _matches(condition, source, subject, named):
    data = condition.data or {}
    if data.get('kind') == 'bitter':
        return _hostile(source, subject)
    tags = {str(t).lower() for t in named or ()}
    # Save dispatch names printed consequence categories as damage:fire,
    # while reviewed boon scopes store the underlying category (fire).
    tags.update(t.removeprefix('damage:') for t in tuple(tags) if t.startswith('damage:'))
    tags = {t.removeprefix('category:') for t in tags}
    return bool(tags.intersection(data.get('scope') or []))


@effect('foundations3_boon', harmful=False)
def boon(ctx, eff):
    from .. import typed_executor as te
    kind = eff['kind']
    subjects = [ctx.actor] if kind in ('bitter', 'ash') else (ctx.targets or [ctx.actor])
    subject = subjects[0]
    amount = (2 if kind == 'bitter' else 1) * int(ctx.numbers['pb']) + int(ctx.numbers['key_mod'])
    sub = te.Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject)
    te.run_effects(sub, [{'type': 'temp_hp', 'flat': max(0, amount), 'applies_to': 'target'}])
    duration = {'kind': 'until_end_of_turn' if kind == 'bitter' else 'until_start_of_your_next_turn'}
    expiry = te.effect_expiry(ctx, {'duration': duration}, subject, condition=True)
    cid = BOON + kind
    ctx.engine._remove_condition(subject, cid, ctx.source)
    ctx.engine._apply_condition(subject, cid, ctx.source, ctx.actor.entity_id, expires_on=expiry,
        data={'kind': kind, 'scope': list(eff.get('scope') or []), 'label': ctx.action.display_name + ': ' + _boon_label(kind, ctx.actor.display_name)})


@hook('save_roll_tags')
def boon_tags(ctx, subject, ability, named):
    # The native save dispatcher then sees exactly the same explicit tags as
    # the typed save reader. Absent boons leave its context unchanged.
    if _boons(subject) or _vessels(ctx.engine, subject):
        return sorted(named)
    return None


@hook('save_mode')
def boon_save(engine, subject, ability, dc, source_id, context):
    source = engine.state.actors.get(context.get('source_actor_id'))
    named = context.get('named') or context.get('conditions') or []
    tags = {str(t).lower() for t in named}
    tags.update(t.removeprefix('damage:') for t in tuple(tags) if t.startswith('damage:'))
    tags = {t.removeprefix('category:') for t in tags}
    vessel = any((not row['abilities'] or ability.upper()[:3] in row['abilities'])
                 and tags.intersection(row['against']) and _hostile(source, subject)
                 for row in _vessels(engine, subject))
    if vessel or any(_matches(c, source, subject, named) for c in _boons(subject)):
        return 'ADVANTAGE'
    return None


@hook('attack_roll_modes')
def surge_attacks(engine, actor, target):
    if _hostile(actor, target) and any((c.data or {}).get('kind') == 'bitter' for c in _boons(actor)):
        return ['ADVANTAGE']
    return None


@hook('ability_check_mode')
def surge_check(engine, actor, ability, skill, against):
    if _hostile(actor, against) and any((c.data or {}).get('kind') == 'bitter' for c in _boons(actor)):
        return 'ADVANTAGE'
    return None


@hook('event', nested=True)
def consume_boon(engine, event_type, kwargs):
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None:
        return
    if event_type == 'SAVE_ROLLED':
        context = engine.d20_context() or {}
        source = engine.state.actors.get(context.get('source_actor_id'))
        for c in list(_boons(actor)):
            if _matches(c, source, actor, context.get('named') or context.get('conditions')):
                engine._remove_condition(actor, c.condition_id, c.source_definition_id)
    elif event_type == 'ATTACK_ROLLED':
        if any(_hostile(actor, engine.state.actors.get(t)) for t in kwargs.get('target_ids') or ()):
            engine._remove_condition(actor, BOON + 'bitter', kwargs.get('source_definition_id') or 'Heartfire Surge')
    elif event_type == 'CHECK_ROLLED':
        from .roll_context import check_receipts
        for aid, roll in check_receipts(kwargs):
            subject = engine.state.actors.get(aid)
            others = [engine.state.actors.get(t) for t in kwargs.get('target_ids') or ()]
            source = engine.state.actors.get(kwargs.get('actor_id'))
            if subject and (any(_hostile(subject, t) for t in others) or _hostile(subject, source)):
                engine._remove_condition(subject, BOON + 'bitter', kwargs.get('source_definition_id') or 'Heartfire Surge')


def _owns_generation(engine, actor, kind):
    return actor is not None and any(row.get('block') == 'generate'
        and 'foundations3_' + kind in row.get('on', [])
        for row in engine.typed_passive_rows.get(actor.entity_id, []))


def open_channels_range(engine, actor, target):
    """The Foundation's eligible outward support and generation reach to
    ``target``: the Refined Open Channels rider makes it 60 feet instead
    of 30 feet while the actual effect path to the ally is clear."""
    from ..targeting import line_of_effect
    owned = any(row.get('block') == 'foundations3_open_channels'
                for row in engine.typed_passive_rows.get(actor.entity_id, []))
    if owned and actor.team_id == target.team_id and line_of_effect(engine, actor, target=target):
        return OPEN_CHANNELS_RANGE_FT
    return SUPPORT_RANGE_FT


def origin_spirit_support_in_range(engine, actor, target):
    """Public eligibility shared by Dew, Vessel and Foundation support riders.

    This is the Foundation's context only, not permission to extend the source
    talent's own range. Actual producers must already have settled support.
    """
    return (actor is not None and target is not None
            and engine._distance_actor_to_actor(actor, target)
            <= open_channels_range(engine, actor, target))


@hook('save_support_intervention')
def spirit_support_intervention(engine, provider, beneficiary, support_source, receipt):
    """Keep a paid native intervention until the actual saving throw settles."""
    if not _owns_generation(engine, provider, 'spirit') or provider.entity_id == beneficiary.entity_id:
        return
    if not origin_spirit_support_in_range(engine, provider, beneficiary):
        return
    named = {tag.removeprefix('category:') for tag in receipt['named']}
    maintenance = receipt['save_source'] == 'system:combat.concentration'
    source = engine.state.actors.get(receipt.get('source_actor_id'))
    pressure = bool(named & {'fear', 'frightened', 'curse', 'cursed', 'hostile_drain', 'backlash',
                             'spirit_pressure', 'spiritual_exhaustion', 'technique_rhythm'})
    if not maintenance and not (pressure and _hostile(source, beneficiary)):
        return
    if receipt.get('dc') is None or receipt['original_total'] >= receipt['dc']:
        return  # a pressure failure must actually have been prevented
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, '_origin_spirit_support_receipts')
    pending = engine.__dict__.setdefault('_origin_spirit_support_receipts', {})
    pending.setdefault((beneficiary.entity_id, receipt['save_source'], receipt['roll_id']), []).append(
        (provider.entity_id, str(support_source)))


@hook('save_support_receipts_needed')
def spirit_support_receipts_needed(engine, provider):
    return _owns_generation(engine, provider, 'spirit')


def settle_spirit_support_roll(engine, beneficiary, save_source, roll_id, failed):
    """Public final-outcome consumer used by native and typed save settlement.

    No new state is persisted: primitive proposals exist only in the enclosing
    action transaction; completed generation uses pressure's native clock.
    """
    from ..paid_relocation import preserve_pending
    pending = engine.__dict__.get('_origin_spirit_support_receipts')
    if not pending:
        return
    preserve_pending(engine, '_origin_spirit_support_receipts')
    proposals = pending.pop((beneficiary.entity_id, save_source, str(roll_id)), [])
    if not pending:
        engine.__dict__.pop('_origin_spirit_support_receipts', None)
    if failed:
        return
    for provider_id, support_source in proposals:
        provider = engine.state.actors.get(provider_id)
        if provider is not None and provider.active and provider.current_hp > 0 \
                and origin_spirit_support_in_range(engine, provider, beneficiary):
            _pending(engine, provider, 'spirit', support_source)


@hook('event', nested=True)
def spirit_native_support_save(engine, event_type, kwargs):
    if event_type != 'SAVE_ROLLED' or not engine.__dict__.get('_origin_spirit_support_receipts'):
        return
    target_id = kwargs.get('actor_id')
    source = kwargs.get('source_definition_id')
    from ..typed_executor import active_save_pending
    if active_save_pending(engine, source, target_id):
        return  # typed outcome overrides still own the final result
    target = engine.state.actors.get(target_id)
    payload = kwargs.get('payload') or {}
    if target is not None and type(payload.get('success')) is bool:
        settle_spirit_support_roll(engine, target, source, payload['roll_id'], not payload['success'])


@hook('after_save_resolved')
def spirit_typed_support_save(ctx, subject, ability, named, failed):
    if not ctx.engine.__dict__.get('_origin_spirit_support_receipts'):
        return
    event = next((e for e in reversed(ctx.engine.events) if e.event_type == 'SAVE_ROLLED'
                  and e.actor_id == subject.entity_id and e.source_definition_id == ctx.source), None)
    if event is not None:
        settle_spirit_support_roll(ctx.engine, subject, ctx.source, event.payload['roll_id'], failed)


@hook('reaction_context_range')
def open_channels_reaction_range(limit, engine, reactor, other, feature_id):
    # Only the Foundation's named outward support spends; an unrelated talent
    # such as Ash Ward retains its own printed range even on this character.
    if feature_id not in {
            'foundation.origin_spirit_body_v0_2B.returning_source_guard',
            'foundation.origin_spirit_body_v0_2B.feed_the_living_circuit'}:
        return None
    if other.entity_id == reactor.entity_id or other.team_id != reactor.team_id:
        return None
    if not any(owned.get('feature_id') == feature_id
               for store in (engine.typed_reaction_rows, engine.typed_passive_rows)
               for owned in store.get(reactor.entity_id, ())):
        return None
    return max(int(limit), open_channels_range(engine, reactor, other))


def _generate(engine, actor, kind, source):
    from .. import pressure
    if pressure.generate(engine, actor, 'foundations3_' + kind):
        names = {'mirror':'Mirror Stillness', 'lotus':'Lotus Dew', 'bitter':'Bitter Heartfire', 'spirit':'Spirit-Source Dew', 'ash':'Funeral Ash'}
        note(engine, source, actor, actor.display_name + ' gains 1 ' + names[kind] + '. It expires at the end of their next turn and can be spent on a later event.')


def _perceives(engine, observer, source):
    from ..senses import perceives
    return perceives(engine, observer, source)


@hook('attack_completed')
def generate_after_attack(engine, notice, intent):
    source = engine.state.actors.get(notice.attacker_id)
    target = engine.state.actors.get(notice.target_id)
    owners = [a for a in engine.state.actors.values() if _owns_generation(engine, a, 'mirror')]
    if not _owns_generation(engine, source, 'bitter') and not owners:
        return
    if notice.hit or not _hostile(source, target) or not _threat(engine.action_catalog.get(notice.source_id)):
        return
    # A genuine attack against a perceived enemy with a possible hit, rather
    # than an impossible roll or self-created/friendly obstacle.
    roll = next((e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED'
                 and e.actor_id == source.entity_id and target.entity_id in e.target_ids), None)
    payload = roll.payload if roll else {}
    # Admission uses the accepted choice receipt, even when opposing modes
    # cancel. Imposed penalties do not identify attacker intention.
    if 'DISADVANTAGE' not in payload.get('chosen_attack_modes', []) and _perceives(engine, source, target):
        _generate(engine, source, 'bitter', notice.source_id)
    for owner in engine.state.actors.values():
        if owner.team_id == target.team_id and engine._distance_actor_to_actor(owner, target) <= 30 and _perceives(engine, owner, source):
            _generate(engine, owner, 'mirror', notice.source_id)


@hook('save_final')
def generate_after_save(ctx, subject, ability, named, failed):
    owners = [a for a in ctx.engine.state.actors.values() if _owns_generation(ctx.engine, a, 'mirror') or _owns_generation(ctx.engine, a, 'lotus')]
    if not _owns_generation(ctx.engine, subject, 'bitter') and not owners:
        return
    if not _hostile(ctx.actor, subject) or not _threat(ctx.action):
        return
    if failed:
        _pending(ctx.engine, subject, 'bitter', ctx.source)
    else:
        for owner in ctx.engine.state.actors.values():
            if owner.team_id == subject.team_id and ctx.engine._distance_actor_to_actor(owner, subject) <= 30 and _perceives(ctx.engine, owner, ctx.actor):
                _pending(ctx.engine, owner, 'mirror', ctx.source)
        tags = {str(t).lower() for t in named or ()}
        tags.update(t.removeprefix('damage:') for t in tuple(tags) if t.startswith('damage:'))
        tags = {t.removeprefix('category:') for t in tags}
        if tags.intersection({'poison','poisoned','disease','rot','polluted_water','sickness_exhaustion','terrain_contamination'}):
            for owner in ctx.engine.state.actors.values():
                if owner.team_id == subject.team_id and ctx.engine._distance_actor_to_actor(owner, subject) <= 30:
                    _pending(ctx.engine, owner, 'lotus', ctx.source)


@hook('action_completed')
def generate_after_support(engine, actor, economy, source):
    _flush(engine)
    _attrition(engine, source)


@hook('event', nested=True)
def generate_spirit_from_support(engine, event_type, kwargs):
    """Credit the actual provider from a settled, source-attributed support receipt."""
    if event_type not in ('HEALING_APPLIED', 'TEMP_HP_GRANTED', 'REACTION_RESOLVED'):
        return
    payload = kwargs.get('payload') or {}
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if not _owns_generation(engine, actor, 'spirit'):
        return
    target_ids = kwargs.get('target_ids') or ()
    if event_type == 'REACTION_RESOLVED':
        # Native ally-damaged settlement identifies the protected creature in
        # protects; target_ids names the attacker and must never receive credit.
        # Quote, consent and payment alone are not a successful reduction.
        before, after = payload.get('pending_before'), payload.get('pending_after')
        if payload.get('checkpoint') != 'DAMAGE_APPLICATION' or type(before) is not int \
                or type(after) is not int or not 0 <= after < before:
            return
        source = kwargs.get('source_definition_id')
        rows = engine.typed_reaction_rows.get(actor.entity_id, [])
        if not any(row.get('feature_id') == source and row.get('block') == 'generic'
                   and row.get('kind') == 'ally_damaged'
                   and any(e.get('type') in ('damage_modifier', 'half_damage', 'resistance', 'immunity')
                           for e in row.get('effects') or ())
                   and not any(e.get('type') in ('redirect_damage_to_self', 'hold_at_1hp')
                               for e in row.get('effects') or ()) for row in rows):
            return
        target_ids = (payload.get('protects'),)
    elif int(payload.get('after', 0)) <= int(payload.get('before', 0)):
        return
    if not actor.active or actor.current_hp <= 0 or any(
            c.condition_id.rsplit('.', 1)[-1] == 'unconscious' for c in actor.conditions.values()):
        return
    for target_id in target_ids:
        target = engine.state.actors.get(target_id)
        if target is not None and target.entity_id != actor.entity_id \
                and origin_spirit_support_in_range(engine, actor, target):
            _generate(engine, actor, 'spirit', kwargs.get('source_definition_id') or 'support')
            return


def _vessels(engine, subject):
    return [row for row in engine.typed_passive_rows.get(subject.entity_id, [])
            if row.get('block') == 'foundations3_vessel']


@hook('compile_block')
def compile_vessel(block, spec, row, numbers):
    if block != 'foundations3_vessel':
        return None
    return [{**row, 'abilities': list(spec['abilities']), 'against': list(spec['against'])}]


@hook('compile_block')
def compile_open_channels(block, spec, row, numbers):
    if block != 'foundations3_open_channels':
        return None
    return [{**row, 'range_ft': int(spec.get('range_ft') or OPEN_CHANNELS_RANGE_FT)}]


def _pending(engine, actor, kind, source):
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, '_foundations3_pending')
    pending = engine.__dict__.setdefault('_foundations3_pending', [])
    receipt = (actor.entity_id, kind, source)
    if receipt not in pending:
        pending.append(receipt)


def _flush(engine):
    if not engine.__dict__.get('_foundations3_pending'):
        return
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, '_foundations3_pending')
    for actor_id, kind, source in engine.__dict__.pop('_foundations3_pending', []):
        actor = engine.state.actors.get(actor_id)
        if actor is not None:
            _generate(engine, actor, kind, source)


@hook('technique_used')
def completed_saves(ctx):
    # Save outcomes are known before their consequences; generation waits
    # until the complete technique so a creature defeated by it gains nothing.
    _flush(ctx.engine)
    _attrition(ctx.engine, ctx.source)


def _attrition(engine, source):
    if not any(_owns_generation(engine, a, 'ash') for a in engine.state.actors.values()):
        return
    for event in reversed(engine.events):
        if event.event_type == 'INTENT_ACCEPTED':
            break
        if event.event_type != 'DAMAGE_COMMITTED':
            continue
        payload = event.payload or {}
        if str(payload.get('damage_type') or '').lower() not in {'fire','poison','necrotic'}:
            continue
        if int(payload.get('hp_damage') or 0) + int(payload.get('temporary_hp_absorbed') or 0) <= 0:
            continue
        attacker = engine.state.actors.get(event.actor_id)
        for target_id in event.target_ids:
            target = engine.state.actors.get(target_id)
            if _hostile(attacker, target) and target.current_hp < target.maximum_hp:
                _generate(engine, target, 'ash', source)
