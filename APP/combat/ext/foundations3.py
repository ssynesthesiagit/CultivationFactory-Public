"""Foundation combat boons and objective completed-event resource triggers.

Scope tags name this save's printed consequence, never an affinity sphere or
an action-name guess. Fresh reviewed effects opt in; frozen catalogs remain
unchanged. Native pressure owns generation, cap, round allowance and expiry.
Outward support is credited from its committed healing/temp-HP or reduction receipt so the
actual provider receives the trigger even when it resolves as a reaction
during another creature's turn.
"""
from . import effect, hook, note


# Gentle Source Pulse uses the public willing_targets and fact_consent_admission
# contracts. No source meaning is inferred from a name, team, or damage type.
PULSE_FACT_KIND = 'gentle_pulse_minor_penalty'
PULSE_CATEGORIES = {'hostile_drain', 'fear_pressure', 'curse_pressure', 'spiritual_exhaustion', 'backlash'}
PULSE_EXCLUDED = {'charmed', 'frightened', 'incapacitated', 'stunned', 'paralyzed', 'possessed',
                  'exhaustion', 'major_curse', 'disease', 'hidden_injury', 'deviation', 'realm_scale_affliction'}


@hook('compile_action')
def compile_gentle_pulse(action, info):
    """Extend the single typed provider; keep its signed amount, cost and range."""
    import copy
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') != GENTLE_PULSE or GENTLE_PULSE not in info['owned_ids']:
        return None
    if any(row.get('type') == 'choose_willing' for row in typed.get('effects') or []):
        return None
    parameters = copy.deepcopy(action.parameters)
    typed = parameters['typed']
    typed['manual_inline_choice'] = True
    typed['effects'] = [{'type': 'choose_willing', 'target_only': True, 'allow_hostile_target': True,
        'allow_neutral_target': True,
        'range_ft': 30, 'consent_text': 'Gain temporary Hit Points equal to the giver’s Proficiency Bonus plus Path key modifier. '
        'They spend a Bonus Action and 1 Spirit-Source Dew; you spend nothing. You may separately end one GM-authorized minor penalty.',
        'effects': [*typed['effects'], {'type': 'gentle_pulse_cleanup'}]}]
    return action.model_copy(update={'parameters': parameters})


@hook('compile_actions')
def gentle_pulse_nonallies(info):
    # compile_actions runs before compile_action transforms. Seal only this
    # owned row before calling the existing public nonally-variant producer.
    from .willing_targets import willing_non_allies
    actions = [sealed for action in info['actions']
               if (sealed := compile_gentle_pulse(action, info)) is not None]
    return willing_non_allies({**info, 'actions': actions}) if actions else None


def pulse_penalty_models(session, subject, value):
    """Validate GM classification against exact native instances, never outcomes."""
    import json
    from ..journey import require
    from ..condition_names import condition_key
    from ..typed_executor import rules
    from ..effect_harm import classify_effect
    from ..penalty_instances import modifier_penalty
    required = {'condition_instances', 'modifier_instances', 'source_definition_id', 'source_actor_id', 'label',
                'category', 'severity', 'excluded', 'allow_pulse'}
    require(set(value) == required, 'Supply exact source instances, category, severity, exclusions and Pulse permission.')
    ids = value['condition_instances']
    mids = value['modifier_instances']
    require(all(isinstance(items, list) and all(type(i) is str for i in items) and len(items) == len(set(items)) for items in (ids, mids)) and (ids or mids),
            'Select distinct existing penalty instances.')
    records = (session.state['actors'][subject].get('encounter_snapshot') or {}).get('conditions', {})
    require(set(ids) <= set(records), 'A selected penalty is no longer present.')
    require(type(value['label']) is str and 0 < len(value['label'].strip()) <= 240 and
            type(value['category']) is str and value['category'] in PULSE_CATEGORIES and
            type(value['severity']) is str and value['severity'] in {'minor', 'major'} and
            isinstance(value['excluded'], list) and all(type(e) is str for e in value['excluded']) and
            set(value['excluded']) <= PULSE_EXCLUDED and type(value['allow_pulse']) is int and value['allow_pulse'] in (0, 1),
            'Classify the actual source and all exclusions; this input grants no penalty or numerical benefit.')
    models = [json.loads(records[i]) for i in ids]
    modifiers = (session.state['actors'][subject].get('encounter_snapshot') or {}).get('modifiers', {})
    require(set(mids) <= set(modifiers), 'A selected modifier is no longer present.')
    modifier_models = [json.loads(modifiers[i]) for i in mids]
    require(all((m['source_definition_id'], m.get('source_actor_id')) ==
                (value['source_definition_id'], value['source_actor_id']) for m in models),
            'Select instances from one exact source and source creature.')
    require(all((m['source_definition_id'], m.get('source_actor_id')) ==
                (value['source_definition_id'], value['source_actor_id']) for m in modifier_models),
            'Select modifiers from the same exact source and source creature.')
    for m in modifier_models:
        require(modifier_penalty(m) is not False,
                'A known native benefit cannot be classified as a penalty.')
    checked = {m['instance_id'] for m in models}
    for m in models:
        data = m.get('data') or {}
        name = condition_key(m['condition_id'])
        known = {name} & PULSE_EXCLUDED
        known |= set(data.get('source_exclusions') or ()) & PULSE_EXCLUDED
        rule = {**(rules()['conditions'].get(name) or {}), **(data.get('rule') or {})}
        if rule.get('no_actions'):
            known.add('incapacitated')
        # A dependent major condition cannot be hidden behind a minor parent.
        for child_id in data.get('consequences') or ():
            if child_id not in records:
                continue
            child = json.loads(records[child_id])
            if (child['source_definition_id'], child.get('source_actor_id')) != (
                    m['source_definition_id'], m.get('source_actor_id')):
                continue
            child_name = condition_key(child['condition_id'])
            child_rule = {**(rules()['conditions'].get(child_name) or {}), **((child.get('data') or {}).get('rule') or {})}
            known |= {child_name} & PULSE_EXCLUDED
            if child_rule.get('no_actions'):
                known.add('incapacitated')
            if child['instance_id'] not in checked:
                checked.add(child['instance_id'])
                models.append(child)
        require(known <= set(value['excluded']), 'A declaration cannot erase a known major-condition exclusion.')
        # Missing native semantics are precisely the GM-bounded case. Preserve
        # known benefits; the explicit GM input supplies unknown source meaning.
        # A declaration itself is bookkeeping, never a mechanically produced penalty.
        require(m['condition_id'] != 'condition:typed.fact_consent_admission' and
                classify_effect({'rule': rule}) is not False,
                'A declaration or known native benefit is not a penalty.')
    return models


@hook('combat_fact_admission_allowed')
def pulse_combat_fact_allowed(session, source, subject, kind):
    return True if source == GENTLE_PULSE and kind == PULSE_FACT_KIND else None


@hook('fact_admission_schema')
def pulse_fact_schema(session, source, subject, kind):
    if source == GENTLE_PULSE and kind == PULSE_FACT_KIND:
        return {'authority': 'table_owner', 'value_type': 'document', 'maximum_seconds': 86400,
                'subject_access': False, 'combat_condition_data_paths': [],
                'description': 'Classify exact existing same-source penalties and permit optional Gentle Source Pulse relief.'}


@hook('fact_admission_validate')
def pulse_fact_validate(session, source, subject, kind, value):
    if source == GENTLE_PULSE and kind == PULSE_FACT_KIND:
        pulse_penalty_models(session, subject, value)


@hook('fact_admitted')
def pulse_fact_scope(session, record):
    if record['source'] == GENTLE_PULSE and record['kind'] == PULSE_FACT_KIND:
        from ..fact_consent_admission import digest
        from ..journey import require
        value = record['value']
        require(hasattr(session, 'engine') and record['scope'] == digest([
                    session.engine.state.match_id, value['source_definition_id'], value['source_actor_id']]),
                'Bind the classification to this exact fight, source and source creature.')


@effect('gentle_pulse_cleanup', harmful=False)
def gentle_pulse_cleanup(ctx, row):
    """The recipient may end ONE permitted minor same-source instance; no broad cleanse."""
    from ..fact_consent_admission import combat_records, NativeFactSession, read, digest
    from .needle import ask, checkpoint_id, CHOICE, say
    from ..penalty_instances import end_instance
    subject = ctx.target
    if subject is None or ctx.typed.get('source') != GENTLE_PULSE:
        return
    available = {}
    session = NativeFactSession(ctx.engine)
    for record in combat_records(ctx.engine, subject, source=GENTLE_PULSE, kind=PULSE_FACT_KIND):
        value = record['value']
        if record['scope'] != digest([ctx.engine.state.match_id, value['source_definition_id'], value['source_actor_id']]):
            continue
        latest = read(session, GENTLE_PULSE, subject.entity_id, PULSE_FACT_KIND, record['scope'], subject.entity_id)
        if latest is None or latest['receipt_id'] != record['receipt_id']:
            continue
        if record['subject'] != subject.entity_id or value['severity'] != 'minor' or value['excluded'] or not value['allow_pulse']:
            continue
        # Revalidate each remaining exact instance separately: removing one
        # stacked penalty does not invalidate permission for the others later.
        for iid in [*value['condition_instances'], *value['modifier_instances']]:
            modifier = iid in value['modifier_instances']
            if iid not in (subject.modifiers if modifier else subject.conditions):
                continue
            try:
                pulse_penalty_models(session, subject.entity_id, {**value,
                    'condition_instances': [] if modifier else [iid], 'modifier_instances': [iid] if modifier else []})
            except ValueError:
                continue
            available[iid] = value['label']
    if not available:
        return
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'GENTLE_PULSE_CLEANUP', subject.entity_id),
        subject, CHOICE + 'gentle_pulse_cleanup', list(available), allow_decline=True,
        labels={iid: f'End {label} (minor penalty {n + 1})' for n, (iid, label) in enumerate(available.items())},
        name='Gentle Source Pulse', feature_id=GENTLE_PULSE, target_id=subject.entity_id,
        automatic_options=list(available),
        prompt=f'Gentle Source Pulse from {ctx.actor.display_name} grants temporary Hit Points to {subject.display_name}. '
        'Also end one of these exact GM-authorized minor penalties? This is optional and costs you no action or resource; all other penalties remain.')
    if selected:
        iid = selected[0]
        if end_instance(ctx.engine, subject, iid, ctx.source):
            say(ctx.engine, ctx.source, ctx.actor,
                f'Gentle Source Pulse ends {available[iid]} on {subject.display_name}; other penalties remain.',
                (subject.entity_id,), details={'receipt_kind': 'gentle_pulse_cleanup', 'condition_instance_id': iid})


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
SHARED = 'foundation.origin_spirit_body_v0_2B.refined_shared_circuit_memory'
GUARD = 'foundation.origin_spirit_body_v0_2B.returning_source_guard'
FEED = 'foundation.origin_spirit_body_v0_2B.feed_the_living_circuit'
MEMORY = 'condition:typed.foundations3_shared_memory.'
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

@hook('damage_context_pending_reaction_rank')
def cautery_wounded_bonus(engine, reactor, row, packet, intent):
    """Red Lotus Cautery: "If you are below half your Hit Point maximum or the damage source is below half its Hit Point
    maximum, increase the reduction by your Proficiency Bonus." It adds to the base reduction (and to Heart-Ash's own
    bonus) only when the reaction is taken, so it never changes who may take it."""
    if row.get('feature_id') != CAUTERY or reactor.entity_id != packet.target_id or not packet.hostile \
            or packet.source_flags.intersection({'voluntary', 'training', 'self_inflicted'}):
        return None
    source = engine.state.actors.get(packet.source_actor_id)
    hurt = packet.hp_before * 2 < reactor.maximum_hp or (source is not None and source.current_hp * 2 < source.maximum_hp)
    return {'reduction_bonus': int(reactor.proficiency_bonus or 2)} if hurt else None


# All scalar consumers share this one source-bound round allowance.
SPIRIT_VESSEL = 'foundation.origin_spirit_body_v0_2B.origin_spirit_vessel'
GENTLE_PULSE = 'foundation.origin_spirit_body_v0_2B.gentle_source_pulse'
SPIRIT_VALUE_BLOCK = 'foundations3_spirit_value'
SPIRIT_VALUE_ROUND = 'foundation_round_origin_spirit_support_value'
SPIRIT_VALUE_PENDING = 'origin_spirit_support_value_pending'
SPIRIT_TEMP_HP_METHOD = 'LIFE_BASE_BORROWED_BREATH'
SPIRIT_SUPPORT_SPHERES = frozenset('tianxia.sphere.' + name for name in (
    'life', 'protection', 'qiweaving', 'radiance', 'spirit_companions', 'water',
    'verdant_growth', 'talismans', 'alchemy'))
SPIRIT_SUPPORT_KINDS = frozenset(('temporary_hp', 'healing', 'damage_reduction',
    'concentration', 'rhythm', 'backlash', 'drain', 'fear', 'curse_pressure',
    'spiritual_exhaustion', 'stabilization'))


@hook('support_value_sign')
def spirit_support_sign(engine, proposal):
    """Pure source/ownership query; neither chooses nor spends a value."""
    from ..support_values import method_of
    from .passive_rows import row_of
    owner = engine.state.actors.get(proposal.actor_id)
    if owner is None or owner.entity_id == proposal.beneficiary_id or not owner.active or owner.current_hp <= 0:
        return None
    row = row_of(engine, owner.entity_id, SPIRIT_VALUE_BLOCK, 'temporary_hp')
    native = method_of(engine, owner, proposal.source_id)
    if not row or native is None:
        return None
    authority = native[1]
    return authority.get('sphere_id') in SPIRIT_SUPPORT_SPHERES or authority.get('foundation_id') == 'origin_spirit_body_v0_2B'


@hook('compile_action')
def seal_spirit_support_action(action, info):
    if SPIRIT_VESSEL not in info['owned_ids']:
        return None
    from ..support_values import source_snapshot
    typed = action.parameters.get('typed') or {}
    source = str(typed.get('source') or '').split('#')[0]
    snapshot = source_snapshot(source)
    if snapshot is None:
        return None
    return action.model_copy(update={'parameters': {**action.parameters,
        'typed': {**typed, 'support_method': snapshot}}})


@hook('compile_bundle')
def seal_spirit_support_rows(bundle, info):
    if not any(row.get('feature_id') == SPIRIT_VESSEL for row in bundle.get('typed_passives', ())):
        return bundle
    from ..support_values import source_snapshot
    for field in ('typed_passives', 'typed_reactions'):
        for row in bundle.get(field, ()):
            snapshot = source_snapshot(row.get('feature_id'))
            if snapshot is not None:
                row['support_method'] = snapshot
    return bundle


@hook('compile_block')
def compile_spirit_value(block, spec, row, numbers):
    if block != SPIRIT_VALUE_BLOCK or row['feature_id'] != SPIRIT_VESSEL:
        return None
    # Keep the reviewed residual clauses visible; this is no whole-owner seal.
    return [{**row, 'kind': 'temporary_hp', 'pb': int(numbers['pb']), 'keeps_compiling': True}]


@hook('support_condition_purpose')
def spirit_support_condition(engine, owner, subject, source_id, condition):
    """A native table response establishes unknown scene consequences.

    This is factual attribution of an already selected harmful condition, not
    a new support action. Automatic seats retain unknown facts; known source
    consequences use their ordinary native producers instead of this question.
    """
    from .passive_rows import row_of
    from ..support_values import method_of
    from . import ai_controlled
    row = row_of(engine, owner.entity_id, SPIRIT_VALUE_BLOCK, 'temporary_hp')
    native = method_of(engine, owner, source_id)
    if (not row or native is None or owner.entity_id == subject.entity_id
            or not owner.active or owner.current_hp <= 0 or ai_controlled(engine, owner)
            or owner.turn_flags.get(SPIRIT_VALUE_ROUND) == engine.state.round_number):
        return None
    method, authority = native
    if authority.get('sphere_id') not in SPIRIT_SUPPORT_SPHERES and authority.get('foundation_id') != 'origin_spirit_body_v0_2B':
        return None
    intent = getattr(engine, '_active_intent', None)
    if intent is None or not getattr(condition, 'condition_id', None):
        return None
    from .needle import ask, checkpoint_id, CHOICE
    labels = {
        'concentration': 'Maintain Concentration',
        'rhythm': 'Maintain the rhythm needed to sustain a technique',
        'backlash': 'Resist backlash or unstable circulation',
        'drain': 'Resist spiritual drain',
        'fear': 'Resist fear',
        'curse_pressure': 'Resist pressure from a curse',
        'spiritual_exhaustion': 'Resist spiritual exhaustion',
        'stabilization': 'Stabilize against one of those pressures',
    }
    action = engine.action_catalog.get(source_id)
    name = action.display_name if action else authority['name']
    check_grant = bool(((condition.data or {}).get('rule') or {}).get('check_mode'))
    chosen = ask(engine, intent, checkpoint_id(engine, 'ORIGIN_SPIRIT_SUPPORT_CONTEXT',
        source_id, subject.entity_id, condition.instance_id), owner,
        CHOICE + 'origin_spirit_support_context', list(labels), labels=labels,
        allow_decline=True, name='Origin-Spirit Vessel', feature_id=SPIRIT_VESSEL,
        target_id=subject.entity_id, preferred=[], default='decline',
        prompt=f'Origin-Spirit Vessel: {name} ' + (f'supports an ability check by {subject.display_name}. ' if check_grant else f'is trying to end or suppress an ongoing harm on {subject.display_name}. ') + 'Confirm the actual consequence that this check supports, or reserve the bonus if it is not established. Confirmation has no extra action or resource cost.',
        prompt_context={'source_definition_id': source_id, 'action_name': name,
                        'action_actor_id': owner.entity_id, 'affected_id': subject.entity_id})
    if not chosen:
        return None
    purpose = chosen[0]
    note(engine, SPIRIT_VESSEL, owner,
         f'{name} supports {subject.display_name} against {purpose.replace("_", " ")}; confirmed at the table.',
         (subject,), receipt_kind='origin_spirit_support_context', method=method,
         method_text_sha256=authority['source']['text_sha256'], beneficiary=subject.entity_id,
         condition_instance=condition.instance_id, condition_source=condition.source_definition_id,
         support_source=source_id, support_purpose=purpose)
    return purpose


@hook('d20_bonus')
def spirit_granted_check_value(engine, roll, intent):
    """An actual roll using an outward native grant may select that roll.

    The native d20 context supplies the check's ability/skill. A matching held
    Advantage grant supplies its actual provider and method, before native
    next-check consumption. No method or purpose comes from an action name.
    """
    context = engine.d20_context(roll) or {}
    if context.get('kind') not in {'check', 'save'} or intent is None:
        return None
    subject = engine.state.actors.get(roll.actor_id)
    if subject is None:
        return None
    from ..typed_executor import is_active_typed_condition
    from ..support_values import (SupportRollSource, condition_purpose_from,
                                  offered_bonus, roll_sources, settled)
    sources = roll_sources(engine, subject, context)
    for condition in tuple(subject.conditions.values()) if context.get('kind') == 'check' else ():
        if not is_active_typed_condition(condition):
            continue
        modes = ((condition.data or {}).get('rule') or {}).get('check_mode') or {}
        if not any(key and modes.get(key) == 'ADVANTAGE' for key in (
                str(context.get('ability') or '').upper(), context.get('skill'), 'ALL')):
            continue
        owner = engine.state.actors.get(condition.source_actor_id)
        if owner is None or owner is subject:
            continue
        purpose = condition_purpose_from(engine, owner, subject, condition.source_definition_id, condition)
        if purpose is None:
            continue
        sources.append(SupportRollSource(owner.entity_id, condition.source_definition_id, purpose))
    total = int(roll.total)
    for source in dict.fromkeys(sources):
        owner = engine.state.actors.get(source.actor_id)
        if owner is None or owner is subject:
            continue
        original = total
        bonus = offered_bonus(engine, owner, subject, source.source_id, source.purpose, original, consume=True)
        if bonus:
            settled(engine, owner, subject, source.source_id, source.purpose,
                    original, original + bonus, original + bonus)
            total += bonus
            yield {'source_id': SPIRIT_VESSEL, 'bonus': bonus, 'user_id': owner.entity_id}


def spirit_temp_hp_value(engine, subject, amount, source_id, source_actor_id, *, consume):
    """Public compatibility adapter; the native offers helper owns dispatch."""
    from ..support_values import offered_bonus
    owner = engine.state.actors.get(source_actor_id)
    if owner is None:
        return None
    return offered_bonus(engine, owner, subject, source_id, 'temporary_hp', amount, consume=consume)


@hook('support_value_bonus')
def spirit_support_value(engine, proposal, *, consume):
    """Choose one actual outward support value, with authoritative provenance."""
    from ..support_values import method_of
    from .passive_rows import row_of
    owner = engine.state.actors.get(proposal.actor_id)
    subject = engine.state.actors.get(proposal.beneficiary_id)
    if owner is None or subject is None or proposal.kind not in SPIRIT_SUPPORT_KINDS:
        return None
    row = row_of(engine, owner.entity_id, SPIRIT_VALUE_BLOCK, 'temporary_hp')
    native = method_of(engine, owner, proposal.source_id)
    if (not row or row['feature_id'] != SPIRIT_VESSEL or native is None
            or subject.entity_id == owner.entity_id or not owner.active or owner.current_hp <= 0
            or owner.turn_flags.get(SPIRIT_VALUE_ROUND) == engine.state.round_number
            or SPIRIT_VALUE_PENDING + '_source' in owner.turn_flags):
        return None
    method, authority = native
    if authority.get('sphere_id') not in SPIRIT_SUPPORT_SPHERES and authority.get('foundation_id') != 'origin_spirit_body_v0_2B':
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
    source_id = proposal.source_id
    action = engine.action_catalog.get(source_id)
    name = action.display_name if action else authority['name']
    value_name = proposal.kind.replace('_', ' ')
    chosen = ask(engine, intent,
        checkpoint_id(engine, 'ORIGIN_SPIRIT_SUPPORT_VALUE', source_id, subject.entity_id, proposal.kind, proposal.value_id),
        owner, CHOICE + 'origin_spirit_support_value', ['increase'], allow_decline=True,
        automatic=ai_controlled(engine, owner),
        name='Origin-Spirit Vessel', feature_id=SPIRIT_VESSEL, target_id=subject.entity_id,
        preferred=['increase'],
        labels={'increase': f'Add {bonus} to this {value_name} value for {subject.display_name}; use your once-per-round bonus'},
        prompt=f'Use Origin-Spirit Vessel on {name} for {subject.display_name}? Add {bonus} to this {value_name} value ({proposal.value} before the bonus), with no extra action or resource cost; one value this round.',
        prompt_context={'source_definition_id': source_id, 'action_name': name,
                        'action_actor_id': owner.entity_id, 'affected_id': subject.entity_id})
    if not chosen:
        return None
    # Primitive transient transport, replayed by the enclosing transaction.
    # The allowance is spent only by the actual native grant event below.
    owner.turn_flags[SPIRIT_VALUE_PENDING + '_source'] = str(source_id)
    owner.turn_flags[SPIRIT_VALUE_PENDING + '_target'] = str(subject.entity_id)
    owner.turn_flags[SPIRIT_VALUE_PENDING + '_bonus'] = bonus
    owner.turn_flags[SPIRIT_VALUE_PENDING + '_kind'] = proposal.kind
    owner.turn_flags[SPIRIT_VALUE_PENDING + '_original'] = proposal.value
    owner.turn_flags[SPIRIT_VALUE_PENDING + '_method'] = method
    owner.turn_flags[SPIRIT_VALUE_PENDING + '_hash'] = str(authority['source']['text_sha256'])
    owner.turn_flags[SPIRIT_VALUE_PENDING + '_name'] = str(authority['name'])
    owner.turn_flags[SPIRIT_VALUE_PENDING + '_value_id'] = proposal.value_id
    # This is an actual selected scalar inside the accepted native transaction,
    # not an estimate. Counterplay may reduce its final delivered result to zero;
    # the selection still cannot boost a second value. Pauses/cancel roll back.
    owner.turn_flags[SPIRIT_VALUE_ROUND] = int(engine.state.round_number)
    return bonus


@hook('event', nested=True)
def spirit_value_committed(engine, event_type, kwargs):
    if event_type not in ('TEMP_HP_GRANTED', 'HEALING_APPLIED'):
        return
    owner = engine.state.actors.get(kwargs.get('actor_id'))
    if owner is None or owner.turn_flags.get(SPIRIT_VALUE_PENDING + '_source') != kwargs.get('source_definition_id'):
        return
    target_id = owner.turn_flags.get(SPIRIT_VALUE_PENDING + '_target')
    if tuple(kwargs.get('target_ids') or ()) != (target_id,):
        return
    kind = 'temporary_hp' if event_type == 'TEMP_HP_GRANTED' else 'healing'
    if owner.turn_flags.get(SPIRIT_VALUE_PENDING + '_kind') != kind:
        return
    from ..support_values import SupportValue
    payload = kwargs.get('payload') or {}
    original = int(owner.turn_flags[SPIRIT_VALUE_PENDING + '_original'])
    spirit_support_settled(engine, SupportValue(owner.entity_id, target_id,
        str(kwargs['source_definition_id']), kind, original),
        original + int(owner.turn_flags[SPIRIT_VALUE_PENDING + '_bonus']),
        int(payload.get('offered', 0)) if kind == 'temporary_hp' else
        max(0, int(payload.get('after', 0)) - int(payload.get('before', 0))))


@hook('support_value_resolved')
def spirit_support_settled(engine, proposal, selected, result):
    owner = engine.state.actors.get(proposal.actor_id)
    if owner is None or (owner.turn_flags.get(SPIRIT_VALUE_PENDING + '_source'),
            owner.turn_flags.get(SPIRIT_VALUE_PENDING + '_target'),
            owner.turn_flags.get(SPIRIT_VALUE_PENDING + '_kind'),
            owner.turn_flags.get(SPIRIT_VALUE_PENDING + '_value_id')) != (
            proposal.source_id, proposal.beneficiary_id, proposal.kind, proposal.value_id):
        return
    bonus = owner.turn_flags.pop(SPIRIT_VALUE_PENDING + '_bonus')
    source = owner.turn_flags.pop(SPIRIT_VALUE_PENDING + '_source')
    owner.turn_flags.pop(SPIRIT_VALUE_PENDING + '_target')
    owner.turn_flags.pop(SPIRIT_VALUE_PENDING + '_kind')
    owner.turn_flags.pop(SPIRIT_VALUE_PENDING + '_original')
    method = owner.turn_flags.pop(SPIRIT_VALUE_PENDING + '_method')
    source_hash = owner.turn_flags.pop(SPIRIT_VALUE_PENDING + '_hash')
    method_name = owner.turn_flags.pop(SPIRIT_VALUE_PENDING + '_name')
    value_id = owner.turn_flags.pop(SPIRIT_VALUE_PENDING + '_value_id')
    owner.turn_flags[SPIRIT_VALUE_ROUND] = int(engine.state.round_number)
    target = engine.state.actors[proposal.beneficiary_id]
    action = engine.action_catalog.get(source)
    name = action.display_name if action else method_name
    note(engine, SPIRIT_VESSEL, owner,
         f'Origin-Spirit Vessel adds {bonus} to one {proposal.kind.replace("_", " ")} value from {name} for {target.display_name}; its one-value bonus is used this round.',
         (target,), receipt_kind='origin_spirit_support_value', method=method,
         support_source=source, beneficiary=target.entity_id, value_kind=proposal.kind,
         original=proposal.value, selected=selected, final_result=result,
         value_id=value_id,
         method_text_sha256=source_hash,
         bonus=bonus, round=int(engine.state.round_number))


def _hostile(a, b):
    return a is not None and b is not None and a.team_id != b.team_id


def _harmful(value):
    """Whether these exact sealed outcome rows impose represented harm."""
    if isinstance(value, dict):
        kind = value.get('type')
        if kind in {'damage', 'extra_damage'} and (value.get('dice') or int(value.get('flat') or 0) > 0
                or value.get('formula') not in (None, '', 'none')):
            return True
        if kind in {'condition', 'ongoing'} and value.get('condition') in {
                'poisoned','frightened','charmed','prone','grappled','restrained',
                'stunned','paralyzed','incapacitated','blinded','deafened','exhaustion'}:
            return True
        if kind == 'forced_movement' and int(value.get('distance_ft') or 0) > 0:
            return True
        return any(_harmful(v) for v in value.values() if isinstance(v, (dict,list)))
    return isinstance(value, list) and any(_harmful(v) for v in value)


def _threat(action):
    """Require a sealed harmful outcome; a bare/staged roll is not pressure."""
    if action is None:
        return False
    damage = action.damage
    if damage is not None and damage.count * damage.sides + damage.modifier > 0:
        return True
    typed = action.parameters.get('typed') or {}
    return bool(typed.get('weapon')) or _harmful(typed.get('effects') or [])


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


@hook('ability_check_hazard_mode')
def moon_mirror_check(engine, actor, ability, skill, against, hazards):
    """The native check producer supplies both hostile source and consequence.

    Soul Vessel never infers pressure from a skill, action name, affinity or a
    condition already on the actor. This is a permanent passive query: it does
    not spend a boon, a Reaction, or a round allowance. Other vessels retain
    their separately printed save-only eligibility.
    """
    source = 'foundation.moon_mirror_still_water_v0_2B.moon_mirror_soul_vessel'
    if str(ability or '').upper()[:3] != 'WIS' or not _hostile(actor, against):
        return None
    tags = {str(tag).lower().removeprefix('category:') for tag in hazards or ()}
    if any(row.get('feature_id') == source and tags.intersection(row['against'])
           for row in _vessels(engine, actor)):
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


SUPPORT_RANGE_FT = 30
OPEN_CHANNELS_RANGE_FT = 60


def open_channels_range(engine, actor, target):
    """The Foundation's eligible outward support and generation reach to
    ``target``: the Refined Open Channels rider makes it 60 feet instead
    of 30 feet while the actual effect path to the ally is clear."""
    from ..targeting import line_of_effect
    owned = any(row.get('block') == 'foundations3_open_channels'
                for row in engine.typed_passive_rows.get(actor.entity_id, []))
    if owned and line_of_effect(engine, actor, target=target):
        return OPEN_CHANNELS_RANGE_FT
    return SUPPORT_RANGE_FT


def _conscious(actor):
    """Foundation receipt gates share native Sleep and Unconscious semantics.

    Positive HP alone does not establish consciousness. Stunned/Paralyzed
    alone still permit these no-action triggers; labels are not authority.
    """
    from ..condition_names import condition_key
    from .dreams_core import asleep
    from .life_state import UNCONSCIOUS
    return not asleep(actor) and not any(
        c.condition_id == UNCONSCIOUS or condition_key(c.condition_id) == 'unconscious'
        for c in actor.conditions.values())


def _generate(engine, actor, kind, source):
    if kind in ('spirit', 'lotus') and not _conscious(actor):
        return
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
    # Only an actual matching helpful save reader can establish a created
    # protection. A successful ordinary save, bare roll or affinity is not it.
    if not failed and _hostile(ctx.actor, subject) \
            and _harmful((getattr(ctx, 'save_effect', None) or {}).get('on_fail') or []):
        tags = {str(t).lower().removeprefix('category:') for t in named or ()}
        if tags.intersection({'fear', 'frightened', 'curse', 'cursed', 'hostile_drain',
                              'life_drain', 'necrotic_drain', 'spirit_pressure',
                              'spiritual_pressure', 'exhaustion_pressure'}):
            for source in getattr(ctx, 'save_support_sources', ()):
                actor = ctx.engine.state.actors.get(source['actor_id'])
                if _owns_generation(ctx.engine, actor, 'spirit') and actor.team_id == subject.team_id \
                        and ctx.engine._distance_actor_to_actor(actor, subject) <= open_channels_range(ctx.engine, actor, subject):
                    _pending(ctx.engine, actor, 'spirit', source['source_id'])
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


@hook('event', nested=True)
def generate_spirit_from_support(engine, event_type, kwargs):
    """Credit the actual provider from a settled, source-attributed support receipt."""
    if event_type not in ('HEALING_APPLIED', 'TEMP_HP_GRANTED', 'REACTION_RESOLVED'):
        return
    payload = kwargs.get('payload') or {}
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if not _owns_generation(engine, actor, 'spirit'):
        return
    # All listed support routes require consciousness at receipt settlement,
    # including a packet accepted before the provider became unconscious.
    if not _conscious(actor):
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
    for target_id in target_ids:
        target = engine.state.actors.get(target_id)
        if target is not None and target.entity_id != actor.entity_id \
                and engine._distance_actor_to_actor(actor, target) <= open_channels_range(engine, actor, target):
            _generate(engine, actor, 'spirit', kwargs.get('source_definition_id') or 'support')
            return


@hook('concentration_save_resolved')
def spirit_after_maintenance(engine, subject, roll, dc, maintained, sources):
    """A final maintained technique credits only its actual outward helper."""
    if not maintained or subject.concentration is None:
        return
    for source in sources:
        actor = engine.state.actors.get(source['actor_id'])
        if not _owns_generation(engine, actor, 'spirit') or actor.entity_id == subject.entity_id:
            continue
        if engine._distance_actor_to_actor(actor, subject) <= open_channels_range(engine, actor, subject):
            held = subject.concentration
            _pending(engine, actor, 'spirit', source['source_id'],
                     maintained=(subject.entity_id, held.source_definition_id, held.started_sequence))


def _vessels(engine, subject):
    return [row for row in engine.typed_passive_rows.get(subject.entity_id, [])
            if row.get('block') == 'foundations3_vessel']


@hook('compile_block')
def compile_vessel(block, spec, row, numbers):
    if block == 'foundations3_shared_memory':
        return [{**row, 'numbers': {k: int(v) for k, v in numbers.items()
                                  if k in ('pb', 'key_mod', 'cl')}}]
    if block != 'foundations3_vessel':
        return None
    return [{**row, 'abilities': list(spec['abilities']), 'against': list(spec['against'])}]


@hook('compile_block')
def compile_open_channels(block, spec, row, numbers):
    if block != 'foundations3_open_channels':
        return None
    return [{**row, 'range_ft': int(spec.get('range_ft') or OPEN_CHANNELS_RANGE_FT)}]


def _shared_row(engine, owner_id):
    return next((r for r in engine.typed_passive_rows.get(owner_id, [])
                 if r.get('block') == 'foundations3_shared_memory' and r.get('feature_id') == SHARED), None)


@hook('choice_reactors')
def shared_memory_choosers(engine):
    owners = [a for a in engine.state.actors.values() if a.active and _shared_row(engine, a.entity_id)]
    return tuple(a.entity_id for a in engine.state.actors.values() if a.active
                 and any(a is not owner and a.team_id == owner.team_id for owner in owners))


def shared_circuit_protection_succeeded(engine, receipt):
    """Consume a public, primitive settled-protection receipt; never rescue a roll.

    Producer must confirm payment from prior resources and an actual benefit.
    Guard adapter below is the native caller. A separate Feed rescue producer
    may call this only after an eligible failed roll actually becomes success.
    Missing actor/source facts are inert, never guessed from prior log entries.
    """
    from . import needle
    from .choice_prompt import action_context
    from ..typed_reactions import triggered_context
    from ..typed_executor import effect_expiry

    if receipt.get('protection_id') not in (GUARD, FEED) or any(type(receipt.get(k)) is not int or receipt[k] != 1 for k in ('beneficial', 'eligible')):
        return
    fields = ('owner_id', 'protected_id', 'source_actor_id', 'trigger_source_id', 'receipt_id')
    if any(not isinstance(receipt.get(k), str) or not receipt[k] for k in fields):
        return
    owner = engine.state.actors.get(receipt['owner_id'])
    ally = engine.state.actors.get(receipt['protected_id'])
    source = engine.state.actors.get(receipt['source_actor_id'])
    row = _shared_row(engine, receipt['owner_id'])
    intent = getattr(engine, '_active_intent', None)
    if not row or not owner or not ally or not ally.active or ally is owner or ally.team_id != owner.team_id or not _hostile(source, ally) or intent is None:
        return
    rid = receipt['receipt_id']
    if any(e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == SHARED
           and e.payload.get('receipt_kind') == 'shared_circuit_choice' and e.payload.get('receipt_id') == rid
           and e.payload.get('owner_id') == owner.entity_id for e in engine.events):
        return
    action = engine.action_catalog.get(receipt['trigger_source_id'])
    # Catalog membership is presentation, not successful-protection authority.
    # Read native provenance only for this exact attacker, source and target;
    # never borrow the enclosing turn's action or another reaction's name.
    action_name = action.display_name if action else 'triggering effect'
    if action is None:
        from ..native_reactions import context as native_context
        from ..typed_reactions import opportunity_profile
        frame = native_context(engine, source.entity_id, receipt['trigger_source_id'])
        if frame and frame.get('target_id') == ally.entity_id:
            native_row, _, _ = opportunity_profile(engine, source)
            if native_row and native_row.get('feature_id') == receipt['trigger_source_id']:
                action_name = native_row['name']
    display_context = {**action_context(engine, source, receipt['trigger_source_id'], ally),
                       'action_name': action_name,
                       'cost': 'No extra action, Reaction, resource or ordinary movement.'}
    labels = {'move': f'Move {ally.display_name} up to 5 feet now; only {source.display_name} cannot make an Opportunity Attack for this movement.',
              'advantage': f'Advantage on {ally.display_name}\'s next saving throw or Cultivation Check (a technique check) against {source.display_name}; expires at the start of {owner.display_name}\'s next turn.'}
    checkpoint = needle.checkpoint_id(engine, 'SHARED_CIRCUIT:' + rid, SHARED)
    chosen = needle.ask(engine, intent, checkpoint, ally, 'choice:needle.shared_circuit_memory',
        list(labels), labels=labels, preferred=['advantage'], allow_decline=True,
        target_id=ally.entity_id, name='Shared Circuit Memory', feature_id=SHARED,
        prompt_context=display_context,
        prompt=f'Shared Circuit Memory: {owner.display_name} protected {ally.display_name} from {source.display_name}\'s {action_name}. Choose one benefit or decline. No extra action, Reaction, resource or ordinary movement is spent.')
    benefit = chosen[0] if chosen else 'decline'
    if benefit not in ('move', 'advantage', 'decline'):
        raise ValueError('Shared Circuit Memory received an unoffered benefit')
    log = (f'Shared Circuit Memory: {ally.display_name} chooses this benefit: {labels[benefit]} No extra action, Reaction or resource is spent.'
           if benefit in labels else f'{ally.display_name} declines Shared Circuit Memory after {source.display_name}\'s {action_name}; no benefit or extra cost.')
    note(engine, SHARED, ally, log,
         receipt_kind='shared_circuit_choice', receipt_id=rid, owner_id=owner.entity_id,
         source_actor_id=source.entity_id, benefit=benefit)
    if benefit == 'move':
        from ..granted_movement import candidates
        moves = candidates(engine, ally, 5, intent, SHARED)
        from . import any_false
        moves = {key: c for key, c in moves.items() if c.destination != ally.position
                 and not any_false('candidate_allowed', engine, ally, c, None)}
        if not moves:
            return
        move_labels = {key: f'Move {ally.display_name} to {c.destination.x},{c.destination.y} at {c.destination.z * 5} feet altitude ({c.movement_cost_ft} feet of movement).'
                       for key, c in moves.items()}
        destination = needle.ask(engine, intent, checkpoint + ':MOVE', ally,
            'choice:needle.shared_circuit_destination', list(moves), labels=move_labels,
            allow_decline=True, target_id=ally.entity_id, name='Shared Circuit Memory', feature_id=SHARED,
            prompt_context=display_context,
            prompt=f'Shared Circuit Memory after {source.display_name}\'s {action_name}: choose where {ally.display_name} moves up to 5 feet, or stay. Only {source.display_name}\'s Opportunity Attack is exempt; other enemies can still react. No extra action, resource or ordinary movement is spent.')
        if destination and destination[0] in moves:
            engine._resolve_movement(ally, moves[destination[0]], intent, granted_ft=5,
                                     ignore_oa_from=(source.entity_id,))
    elif benefit == 'advantage':
        ctx = triggered_context(engine, owner, source, {**row, 'feature_id': SHARED,
                                'name': 'Shared Circuit Memory', 'effects': []}, intent)
        expiry = effect_expiry(ctx, {'duration': {'kind': 'until_start_of_your_next_turn'}}, ally, condition=True)
        if expiry is None:
            raise ValueError('Shared Circuit Memory requires native owner next-start expiry')
        cid = MEMORY + owner.entity_id + '.' + source.entity_id
        engine._remove_condition(ally, cid, SHARED)
        engine._apply_condition(ally, cid, SHARED, owner.entity_id, expires_on=expiry,
            data={'pressure_source_id': source.entity_id, 'receipt_id': rid,
                  'label': 'Shared Circuit Memory: ' + labels['advantage']})


@hook('event', nested=True)
def shared_memory_guard_receipt(engine, event_type, kwargs):
    if event_type != 'REACTION_RESOLVED' or kwargs.get('source_definition_id') != GUARD or not _shared_row(engine, kwargs.get('actor_id')):
        return
    from ..pending_damage import current
    packet = current(engine)
    payload = kwargs.get('payload') or {}
    before, after = payload.get('pending_before'), payload.get('pending_after')
    event = kwargs.get('originating_event')
    if not packet or not packet.hostile or packet.target_id != payload.get('protects') or not event:
        return
    if type(before) is not int or type(after) is not int or not (before > after >= 0) or payload.get('reduction') != before - after:
        return
    if packet.source_actor_id not in kwargs.get('target_ids', ()):
        return
    shared_circuit_protection_succeeded(engine, {
        'protection_id': GUARD, 'beneficial': 1, 'eligible': 1,
        'owner_id': kwargs['actor_id'], 'protected_id': packet.target_id,
        'source_actor_id': packet.source_actor_id, 'trigger_source_id': packet.source_id,
        'receipt_id': 'guard:' + str(event.sequence)})


def _memories(subject, source_id):
    return [c for c in subject.conditions.values() if c.condition_id.startswith(MEMORY)
            and (c.data or {}).get('pressure_source_id') == source_id]


@hook('save_mode')
def shared_memory_save(engine, subject, ability, dc, source_id, context):
    return 'ADVANTAGE' if _memories(subject, context.get('source_actor_id')) else None


@hook('event', nested=True)
def consume_shared_memory_save(engine, event_type, kwargs):
    if event_type != 'SAVE_ROLLED':
        return
    subject = engine.state.actors.get(kwargs.get('actor_id'))
    if subject:
        for held in _memories(subject, (engine.d20_context() or {}).get('source_actor_id')):
            engine._remove_condition(subject, held.condition_id, held.source_definition_id)


@hook('contest_check_mode')
def shared_memory_cultivation(ctx, subject, opponent, spec):
    return 'ADVANTAGE' if spec.get('kind') == 'cultivation' and _memories(subject, opponent.entity_id) else None


@hook('opposed_check_resolved')
def consume_shared_memory_cultivation(ctx, target, result, actor_check, target_check):
    for subject, opponent, spec in ((ctx.actor, target, actor_check), (target, ctx.actor, target_check)):
        if spec.get('kind') == 'cultivation':
            for held in _memories(subject, opponent.entity_id):
                ctx.engine._remove_condition(subject, held.condition_id, held.source_definition_id)


def _pending(engine, actor, kind, source, *, maintained=None):
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, '_foundations3_pending')
    pending = engine.__dict__.setdefault('_foundations3_pending', [])
    receipt = (actor.entity_id, kind, source, *maintained) if maintained is not None else (actor.entity_id, kind, source)
    if receipt not in pending:
        pending.append(receipt)


def _flush(engine):
    if not engine.__dict__.get('_foundations3_pending'):
        return
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, '_foundations3_pending')
    for receipt in engine.__dict__.pop('_foundations3_pending', []):
        actor_id, kind, source = receipt[:3]
        if len(receipt) == 6:
            subject_id, technique, started = receipt[3:]
            subject = engine.state.actors.get(subject_id)
            from ..concentration import copies
            if subject is None or not subject.active or subject.current_hp <= 0 \
                    or started not in copies(subject, technique):
                continue
        actor = engine.state.actors.get(actor_id)
        if actor is not None:
            _generate(engine, actor, kind, source)


@hook('technique_used')
def completed_saves(ctx):
    # Save outcomes are known before their consequences; generation waits
    # until the complete technique so a creature defeated by it gains nothing.
    _flush(ctx.engine)


@hook('transaction_settled')
def settle_support_receipts(engine, source_id, actor_id, intent, first_sequence):
    # Standing-zone and turn-boundary deliveries run typed effects without an
    # action or technique completing, so their queued Dew (supported saves)
    # settles at the transaction boundary, inside the same commit.
    _flush(engine)


@hook('transaction_settled')
def generate_ash_after_settlement(engine, source_id, actor_id, intent, first_sequence):
    from .ash_garden import owns_zero_drop
    from .foundation_context import (settled_execution_events, adjudicated_event_context,
        conscious, helpless_before, source_method_facts, ash_aligned)
    from ..relations import relation, ENEMY
    def enemy(engine, left, right):
        return relation(engine, left, right) == ENEMY
    owners = [a for a in engine.state.actors.values()
              if _owns_generation(engine, a, 'ash') and conscious(a)
              and a.resources.get('resource:foundation.funeral_ash', 0) == 0]
    if not owners:
        return
    if intent is None:
        # No actual table/controller answer can establish scene facts at an
        # unprompted system/bootstrap boundary. Unknown remains unknown.
        return
    events = settled_execution_events(engine, first_sequence)
    for event in events:
        source_actor = engine.state.actors.get(event.actor_id)
        target = engine.state.actors.get(next(iter(event.target_ids), ''))
        payload = event.payload or {}
        if event.event_type == 'DAMAGE_COMMITTED':
            if (source_actor is None or target is None or not enemy(engine, source_actor, target)
                    or helpless_before(event)
                    or int(payload.get('hp_damage') or 0) + int(payload.get('temporary_hp_absorbed') or 0) <= 0):
                continue
            for owner in owners:
                if owner.resources.get('resource:foundation.funeral_ash', 0):
                    continue
                if owns_zero_drop(engine, owner, event):
                    # Garden offers this same drop once, including decline.
                    continue
                if owner is target and target.current_hp < target.maximum_hp:
                    facts = adjudicated_event_context(engine, owner, event, intent, route='incoming')
                    if facts.get('circumstances') == 'real' and facts.get('damage_category') in {
                            'fire', 'poison', 'necrotic', 'disease', 'blood_loss', 'attrition'}:
                        _generate(engine, owner, 'ash', event.source_definition_id)
                elif owner is source_actor and int(payload.get('hp_before') or 0) < target.maximum_hp \
                        and source_method_facts(engine, event.source_definition_id):
                    facts = adjudicated_event_context(engine, owner, event, intent, route='outgoing')
                    if facts.get('circumstances') == 'real' and ash_aligned(engine, owner, event, facts):
                        _generate(engine, owner, 'ash', event.source_definition_id)
        elif event.event_type == 'ENTITY_DEFEATED':
            target = engine.state.actors.get(event.actor_id)
            if target is None:
                continue
            for owner in owners:
                if owner.resources.get('resource:foundation.funeral_ash', 0) or not enemy(engine, owner, target):
                    continue
                # A defeat must be a newly observed hostile packet, not damage
                # harvested from an already helpless target. The cultivator
                # need not land the finishing blow to observe an enemy ending.
                damage = next((e for e in events if e.event_type == 'DAMAGE_COMMITTED'
                    and target.entity_id in e.target_ids and int(e.payload.get('hp_before') or 0) > 0
                    and e.payload.get('remaining_hp') == 0
                    and owner.entity_id in e.payload.get('target_perceived_by', ())
                    and engine.state.actors.get(e.actor_id) is not None
                    and enemy(engine, engine.state.actors[e.actor_id], target)), None)
                if damage is None or helpless_before(damage):
                    continue
                if owns_zero_drop(engine, owner, damage):
                    continue
                facts = adjudicated_event_context(engine, owner, event, intent, route='ending', damage_receipt=damage)
                if facts.get('circumstances') == 'real' and facts.get('ending') in ('defeat', 'mercy'):
                    _generate(engine, owner, 'ash', damage.source_definition_id)
