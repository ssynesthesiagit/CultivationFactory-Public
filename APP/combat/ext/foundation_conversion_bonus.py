"""Public shared paid values for foundations4, foundations4_rolls and reed_slip.

Quotes are pure. Settlement requires the native RESOURCE_SPENT receipt and
records one primitive round receipt; repeated readers of that receipt agree.
Refined owners publish their own selected extra_pb/scoped rows in this block. They
share this provider rather than copying payment, selection or round policy.
"""
from . import hook, effect, run_strict, note

BLOCK = 'foundation_conversion_bonus'
CLOCK = 'foundation_round_conversion_bonus'
CONVERSIONS = {'cut': 'Sword-Bone Cut', 'sheath': 'Sheath-Bone Guard',
               'severing_clarity': 'Severing Clarity', 'reed_slip': 'Reed Slip',
               'reed_guard': 'Bend-Without-Breaking Guard', 'reed_recovery': 'Reed Recovery',
               'wire_tendons': 'Wire Tendons'}
EXPRESSION = 'condition:typed.foundation_conversion_expression'
SOURCE_STATUS = 'condition:typed.foundation_conversion_source_status'


@hook('compile_block')
def compile_bonus(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'conversions': list(spec['conversions']),
             'extra_pb': int(spec.get('extra_pb', 1)),
             'conversion_values': {key: {name: int(value) for name, value in values.items()}
                                   for key, values in spec.get('conversion_values', {}).items()},
             'scope': list(spec.get('scope') or []),
             'once_round': bool(spec.get('once_round')),
             'selected': bool(spec.get('selected')), 'pb': int(numbers['pb']),
             'name': str((numbers.get('record') or {}).get('name') or 'Foundation evolution')}]


def conversion_rows(engine, actor):
    """Owned, stage-compiled bonus rows; public for Refined expression producers."""
    return [r for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, [])
            if r.get('block') == BLOCK and conversion_available(engine, actor, r['feature_id'])]


@hook('compile_bundle')
def source_status(bundle, info):
    """Carry explicit Factory Foundation status without guessing from names.

    Unknown/absent statuses remain recorded as such. Only an explicit Suppressed
    status disables this provider; ordinary dispels do not sever a Foundation.
    """
    foundation = info['owner_sheet'].get('foundation') or {}
    if not foundation.get('foundation_id'):
        return bundle
    from ..typed_numbers import authority_mechanics
    mechanics = authority_mechanics()
    exclusions = foundation.get('suppressed_or_excluded_benefits') or []
    excluded_ids = []
    for fid, record in mechanics.items():
        if record.get('foundation_id') == foundation.get('foundation_id') and any(
                entry.get('benefit') in {fid, record.get('name')}
                and entry.get('source_packet_ids') and entry.get('reason')
                for entry in exclusions if isinstance(entry, dict)):
            excluded_ids.append(fid)
    bundle['foundation_source_status'] = {
        'foundation_id': str(foundation.get('foundation_id') or ''),
        'status': str(foundation.get('status') or ''),
        'provenance': 'owner_sheet.foundation.status',
        'excluded_feature_ids': excluded_ids,
        'exclusions': exclusions,
        'exclusion_provenance': 'Character_Master_Ledger.foundation.suppressed_or_excluded_benefits'}
    return bundle


def conversion_available(engine, actor, source_id=None):
    """Pure explicit-source availability query used by every conversion reader."""
    state = next((c for c in actor.conditions.values() if c.condition_id == SOURCE_STATUS), None)
    if state is not None and state.data.get('status') != 'available':
        return False
    for bundle in getattr(engine, 'typed_bundle_documents', ()) or ():
        if bundle.get('actor_id') == actor.entity_id:
            status = bundle.get('foundation_source_status') or {}
            if state is None and str(status.get('status', '')).casefold() == 'suppressed':
                return False
            if source_id in status.get('excluded_feature_ids', []):
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
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.conversion_source_status.{status}",
        display_name='Foundation: record ' + ('suppression' if status == 'suppressed' else 'recovery'),
        owner_id=info['actor_id'], economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
        parameters={'setting_only': True,
            'setting_description': 'Record the Game Master’s ruling that your Foundation is ' +
                ('suppressed. Foundation evolution bonuses stop until recovery is recorded.' if status == 'suppressed'
                 else 'available again. This does not restore a spent once-per-round benefit.') + ' No resource or Reaction is spent.',
            'typed': {'source': source, 'numbers': info['numbers'],
                'effects': [{'type': 'foundation_conversion_source_status', 'status': status}],
                'riders': [], 'duration': {'kind': 'instant'}}, 'expected_damage': 0})
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
            'label': 'Foundation ' + ('suppressed: no Foundation evolution bonuses until recovery is recorded'
                                    if status == 'suppressed' else 'available')})


@hook('compile_actions')
def expression_actions(info):
    """Native human/AI settings for selected rows published by Refined owners."""
    from ..typed_reactions import rules
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    features = rules().get('features') or {}
    made = []
    for fid in sorted(info['owned_ids']):
        spec = features.get(fid) or {}
        if spec.get('block') != BLOCK or not spec.get('selected'):
            continue
        label = info['mechanics'][fid]['name']
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.conversion_expression.{fid.rsplit('.', 1)[-1]}",
            display_name='Foundation expression: ' + label, owner_id=info['actor_id'],
            economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
            parameters={'setting_only': True,
                'setting_description': 'Choose one Refined expression for this fight. Its printed benefit applies when you spend the matching Foundation resource; the evolution adds no extra cost.',
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


def eligible_rows(engine, actor, conversion, *, named=()):
    """Pure matching rows, shared by quotes and paid settlement across consumers."""
    if not conversion_available(engine, actor):
        return []
    clock = actor.turn_flags.get(CLOCK) or {}
    return [row for row in conversion_rows(engine, actor)
            if conversion in row['conversions']
            and (not row.get('scope') or set(named).intersection(row['scope']))
            and selected_bonus_row(engine, actor, row)
            and (not row['once_round'] or clock.get(row['feature_id']) != engine.state.round_number)]


def row_value(row, conversion):
    """A data-declared integer value; flat feet and PB bonuses use the same receipt."""
    values = row.get('conversion_values', {}).get(conversion)
    if values is not None:
        return int(values.get('flat', 0)) + int(values.get('extra_pb', 0)) * row['pb']
    return row['extra_pb'] * row['pb']


def conversion_bonus(engine, actor, conversion, *, receipt_id=None, named=()):
    """Pure extra bonus quote, or the settled value for a named native receipt.

    Consumers add this to one existing damage/reduction/same-roll value. A
    matching receipt is read even after its once-round allowance was claimed.
    """
    clock = actor.turn_flags.get(CLOCK) or {}
    receipt = clock.get('receipt') or {}
    if receipt_id is not None and receipt.get('receipt_id') == receipt_id:
        return int(receipt['bonus']) if receipt.get('conversion') == conversion else 0
    return sum(row_value(row, conversion) for row in eligible_rows(engine, actor, conversion, named=named))


def conversion_consent_note(engine, actor, conversion, *, named=()):
    """Disclose the shared round limit only for available contributing rows."""
    if actor is None:
        return ''
    notes = []
    for row in eligible_rows(engine, actor, conversion, named=named):
        if not row['once_round'] or row_value(row, conversion) <= 0:
            continue
        names = [CONVERSIONS.get(kind, kind.replace('_', ' ')) for kind in row['conversions']]
        notes.append(f" Using {row['name']} spends its shared once-per-round benefit for "
                     + ', '.join(names) + ' until the next round.')
    return ''.join(notes)


def settle_conversion_bonus(engine, actor, conversion, receipt_id, source_id, *, resource_id=None, named=()):
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
    if resource_id is None:
        resource_id = next((r.get('resource_id') for r in engine.typed_passive_rows.get(actor.entity_id, [])
                            if r.get('feature_id') == source_id and r.get('resource_id')), None)
    if (payment is None or resource_id is None or payment.payload.get('resource_id') != resource_id
            or payment.payload.get('amount') != 1
            or payment.transaction_id != engine.events[-1].transaction_id
            or previous.get('payment_sequence') == payment.sequence):
        return 0
    applied = eligible_rows(engine, actor, conversion, named=named)
    amount = sum(row_value(row, conversion) for row in applied)
    if not amount:
        return 0
    clock = actor.turn_flags.setdefault(CLOCK, {})
    for row in applied:
        if row['once_round']:
            clock[row['feature_id']] = engine.state.round_number
    clock['receipt'] = {'receipt_id': str(receipt_id), 'conversion': conversion,
                        'bonus': amount, 'round': engine.state.round_number,
                        'payment_sequence': payment.sequence, 'source_id': source_id,
                        'contributors': ','.join(row['feature_id'] for row in applied)}
    note(engine, source_id, actor,
         f"{' + '.join(row['name'] for row in applied)} increases {CONVERSIONS[conversion]} by {amount} for this spend." +
         (' The once-per-round benefit is used.' if any(row['once_round'] for row in applied) else ''),
         receipt_kind=BLOCK, **clock['receipt'])
    return amount
