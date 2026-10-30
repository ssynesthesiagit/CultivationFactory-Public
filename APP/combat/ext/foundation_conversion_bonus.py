"""Public paid-conversion bonuses shared by foundations4 and foundations4_rolls.

Quotes are pure. Settlement requires the native RESOURCE_SPENT receipt and
records one primitive round receipt; repeated readers of that receipt agree.
Refined owners publish their own selected extra_pb rows in this block. They
share this provider rather than copying payment, selection or round policy.
"""
from . import hook, effect, run_strict, note

BLOCK = 'foundation_conversion_bonus'
CLOCK = 'foundation_round_conversion_bonus'
CONVERSIONS = {'cut': 'Sword-Bone Cut', 'sheath': 'Sheath-Bone Guard',
               'severing_clarity': 'Severing Clarity'}
EXPRESSION = 'condition:typed.foundation_conversion_expression'
SOURCE_STATUS = 'condition:typed.foundation_conversion_source_status'


@hook('compile_block')
def compile_bonus(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'conversions': list(spec['conversions']),
             'extra_pb': int(spec.get('extra_pb', 1)),
             'once_round': bool(spec.get('once_round')),
             'selected': bool(spec.get('selected')), 'pb': int(numbers['pb']),
             'name': str((numbers.get('record') or {}).get('name') or 'Severance Edge evolution')}]


def conversion_rows(engine, actor):
    """Owned, stage-compiled bonus rows; public for Refined expression producers."""
    return [r for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, [])
            if r.get('block') == BLOCK]


@hook('compile_bundle')
def source_status(bundle, info):
    """Carry explicit Factory Foundation status without guessing from names.

    Unknown/absent statuses remain recorded as such. Only an explicit Suppressed
    status disables this provider; ordinary dispels do not sever a Foundation.
    """
    if not any(r.get('block') == BLOCK for r in bundle.get('typed_passives', [])):
        return bundle
    foundation = info['owner_sheet'].get('foundation') or {}
    bundle['foundation_source_status'] = {
        'foundation_id': str(foundation.get('foundation_id') or ''),
        'status': str(foundation.get('status') or ''),
        'provenance': 'owner_sheet.foundation.status'}
    return bundle


def conversion_available(engine, actor):
    """Pure explicit-source availability query used by every conversion reader."""
    state = next((c for c in actor.conditions.values() if c.condition_id == SOURCE_STATUS), None)
    if state is not None:
        return state.data.get('status') == 'available' and actor.active and actor.current_hp > 0
    for bundle in getattr(engine, 'typed_bundle_documents', ()) or ():
        if bundle.get('actor_id') == actor.entity_id:
            status = bundle.get('foundation_source_status') or {}
            if str(status.get('status', '')).casefold() == 'suppressed':
                return False
    return actor.active and actor.current_hp > 0


@hook('compile_actions')
def source_status_actions(info):
    """A table setting records a GM ruling, never invents a suppressing power.

    Source rows opt in; no other character receives these controls. Neither
    status is an AI default. Setting actions use the existing native table
    settings area, with accepted intents and persisted condition provenance.
    """
    from ..typed_reactions import rules
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    features = rules().get('features') or {}
    owned = next((fid for fid in info['owned_ids'] if
                  (features.get(fid) or {}).get('block') == BLOCK), None)
    if owned is None:
        return None
    source = '.'.join(owned.split('.')[:2])
    from ..action_variants import choice, with_variant

    return [with_variant(ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.conversion_source_status.{status}",
        display_name='Foundation: record ' + ('suppression' if status == 'suppressed' else 'recovery'),
        owner_id=info['actor_id'], economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
        parameters={'setting_only': True,
            'setting_description': 'Record the Game Master’s ruling that your Foundation is ' +
                ('suppressed. Severance Edge evolution bonuses stop until recovery is recorded.' if status == 'suppressed'
                 else 'available again. This does not restore a spent once-per-round benefit.') + ' No resource or Reaction is spent.',
            'typed': {'source': source, 'numbers': info['numbers'],
                'effects': [{'type': 'foundation_conversion_source_status', 'status': status}],
                'riders': [], 'duration': {'kind': 'instant'}}, 'expected_damage': 0}),
        f"action:typed.{info['short']}.conversion_source_status", 'Foundation: record',
        (choice('status', status, 'suppression' if status == 'suppressed' else 'recovery'),))
        for status in ('suppressed', 'available')]


@effect('foundation_conversion_source_status', harmful=False)
def record_source_status(ctx, spec):
    status = spec['status']
    if status not in {'suppressed', 'available'}:
        raise ValueError('Source status must record suppression or recovery')
    ctx.engine._remove_condition(ctx.actor, SOURCE_STATUS, ctx.source)
    ctx.engine._apply_condition(ctx.actor, SOURCE_STATUS, ctx.source, ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'status': status,
            'provenance': 'accepted table setting: Game Master ruling',
            'label': 'Foundation ' + ('suppressed: no Severance Edge evolution bonuses until recovery is recorded'
                                    if status == 'suppressed' else 'available')})


@hook('compile_actions')
def expression_actions(info):
    """Native human/AI settings for selected rows published by Refined owners."""
    from ..typed_reactions import rules
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    features = rules().get('features') or {}
    made = []
    for fid in info['owned_ids']:
        spec = features.get(fid) or {}
        if spec.get('block') != BLOCK or not spec.get('selected'):
            continue
        label = info['mechanics'][fid]['name']
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.conversion_expression.{fid.rsplit('.', 1)[-1]}",
            display_name='Foundation expression: ' + label, owner_id=info['actor_id'],
            economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
            parameters={'setting_only': True,
                'setting_description': 'Choose one Refined expression for this fight. It increases the matching Severance Edge conversion by your Proficiency Bonus, without an extra resource spend.',
                **({'ai_setting_default': {'condition_id': EXPRESSION, 'source_definition_id': fid,
                    'data': {'feature': fid, 'label': label}}} if not made else {}),
                'typed': {'source': fid, 'numbers': info['numbers'],
                    'effects': [{'type': 'foundation_conversion_expression', 'feature': fid}],
                    'riders': [], 'duration': {'kind': 'instant'}}, 'expected_damage': 0}))
    return made or None


@effect('foundation_conversion_expression', harmful=False)
def select_expression(ctx, spec):
    if not any(c.condition_id == EXPRESSION for c in ctx.actor.conditions.values()):
        ctx.engine._apply_condition(ctx.actor, EXPRESSION, ctx.source, ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED', data={'feature': spec['feature'], 'label': ctx.action.display_name})


@hook('candidate_allowed')
def expression_allowed(engine, actor, candidate, action):
    if action and any(e.get('type') == 'foundation_conversion_expression'
            for e in (action.parameters.get('typed') or {}).get('effects') or []):
        if any(c.condition_id == EXPRESSION for c in actor.conditions.values()):
            return False
    return None


@hook('foundation_expression_selected')
def expression_selected(engine, actor, feature_id):
    if not any(r['feature_id'] == feature_id and r['selected'] for r in conversion_rows(engine, actor)):
        return None
    return any(c.condition_id == EXPRESSION and c.data.get('feature') == feature_id
               for c in actor.conditions.values())


def selected_bonus_row(engine, actor, row):
    """Public selection query: an explicit False vetoes, unknown is not selected."""
    if not row['selected']:
        return True
    answers = run_strict('foundation_expression_selected', engine, actor, row['feature_id'])
    return True in answers and False not in answers


def conversion_bonus(engine, actor, conversion, *, receipt_id=None):
    """Pure extra bonus quote, or the settled value for a named native receipt.

    Consumers add this to one existing damage/reduction/same-roll value. A
    matching receipt is read even after its once-round allowance was claimed.
    """
    clock = actor.turn_flags.get(CLOCK) or {}
    receipt = clock.get('receipt') or {}
    if receipt_id is not None and receipt.get('receipt_id') == receipt_id:
        return int(receipt['bonus']) if receipt.get('conversion') == conversion else 0
    if not conversion_available(engine, actor):
        return 0
    amount = 0
    for row in conversion_rows(engine, actor):
        if conversion not in row['conversions']:
            continue
        if not selected_bonus_row(engine, actor, row):
            continue
        if row['once_round'] and clock.get(row['feature_id']) == engine.state.round_number:
            continue
        amount += row['extra_pb'] * row['pb']
    return amount


def conversion_consent_note(engine, actor, conversion):
    """Pure shared-limit disclosure for Cut/Guard and Clarity consent prompts.

    Only available, contributing once-round rows incur this opportunity cost;
    a selected Refined-only increase must not claim to spend it.
    """
    if actor is None or not conversion_available(engine, actor):
        return ''
    clock = actor.turn_flags.get(CLOCK) or {}
    notes = []
    for row in conversion_rows(engine, actor):
        if (conversion not in row['conversions'] or not row['once_round']
                or row['extra_pb'] * row['pb'] <= 0
                or not selected_bonus_row(engine, actor, row)
                or clock.get(row['feature_id']) == engine.state.round_number):
            continue
        names = [CONVERSIONS.get(kind, kind.replace('_', ' ')) for kind in row['conversions']]
        notes.append(f" Using {row['name']} spends its shared once-per-round benefit for "
                     + ', '.join(names) + ' until the next round.')
    return ''.join(notes)


def settle_conversion_bonus(engine, actor, conversion, receipt_id, source_id):
    """Commit after one legal debit. A receipt never boosts two conversions.

    Cut/Guard pass the RESOURCE_SPENT event id; Clarity passes the original roll
    id after its shared on_use callback pays. A missing/mismatched debit fails
    closed. No resource, Reaction, roll or extra damage packet is created here.
    """
    clock = actor.turn_flags.get(CLOCK) or {}
    previous = clock.get('receipt') or {}
    if previous.get('receipt_id') == receipt_id:
        return conversion_bonus(engine, actor, conversion, receipt_id=receipt_id)
    payment = next((e for e in reversed(engine.events) if e.event_type == 'RESOURCE_SPENT'
                    and e.actor_id == actor.entity_id and e.source_definition_id == source_id), None)
    if (payment is None or payment.payload.get('resource_id') != 'resource:foundation.severance_edge'
            or payment.payload.get('amount') != 1
            or payment.transaction_id != engine.events[-1].transaction_id
            or previous.get('payment_sequence') == payment.sequence):
        return 0
    amount = conversion_bonus(engine, actor, conversion)
    if not amount:
        return 0
    clock = actor.turn_flags.setdefault(CLOCK, {})
    contributed = [row for row in conversion_rows(engine, actor)
        if conversion in row['conversions'] and selected_bonus_row(engine, actor, row)
        and (not row['once_round'] or clock.get(row['feature_id']) != engine.state.round_number)]
    for row in contributed:
        if row['once_round']:
            clock[row['feature_id']] = engine.state.round_number
    clock['receipt'] = {'receipt_id': str(receipt_id), 'conversion': conversion,
                        'bonus': amount, 'round': engine.state.round_number,
                        'payment_sequence': payment.sequence, 'source_id': source_id,
                        'contributors': ','.join(row['feature_id'] for row in contributed)}
    note(engine, source_id, actor,
         f"{' + '.join(row['name'] for row in contributed)} increases {CONVERSIONS[conversion]} by {amount} for this spend." +
         (' The once-per-round benefit is used.' if any(row['once_round'] for row in contributed) else ''),
         receipt_kind=BLOCK, **clock['receipt'])
    return amount
