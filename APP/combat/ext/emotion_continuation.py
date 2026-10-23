"""Emotion's consumers of the published native continuation/time contracts.

Only actual source-owned native instances are exported. Restoration is state
continuation through effect_continuation, never another cast or acquired feature.
Original exact journey deadlines survive projection and source-clock rebasing.
"""
import json
from fractions import Fraction
from . import hook
from .emotion_cultivator import LEVELS, WEATHER, STATE, condition

KEY = 'emotion_native_continuation'
DEADLINE = 'condition:typed.concentration_deadline'


def source_owned(engine, source):
    # Native movement consumers use the controlling source record, rather than
    # an action id: moving under an existing aura is not another activation.
    # This classifies actual instances for continuation; it grants no feature.
    if source in LEVELS:
        return True
    action = engine.action_catalog.get(source)
    return action is not None and (action.parameters.get('typed') or {}).get('source') in LEVELS


def remaining(engine, row, holder):
    from .effect_durations import remaining_seconds, token
    name = row.expires_on
    if name == 'END_OF_CURRENT_TURN':
        return Fraction(6, len(engine.state.initiative_order))
    if name == 'END_OF_HOLDER_NEXT_TURN':
        name = token('end', holder.entity_id, holder.turns_started + 1)
    value = remaining_seconds(engine, name, source_actor_id=row.source_actor_id)
    if value is None:
        from .effect_durations import parse
        parsed = parse(name)
        if parsed and parsed[0] == 'end':
            start = token('start', parsed[1], parsed[2])
            value = remaining_seconds(engine, start) + Fraction(6, len(engine.state.initiative_order))
    if value is None:
        raise ValueError('Emotion continuation requires a recognized native duration: ' + str(name))
    return value


def exported(engine, actor):
    from .. import concentration
    rows = []
    for kind, values in [('condition', actor.conditions.values()), ('modifier', actor.modifiers.values())]:
        for row in values:
            if not source_owned(engine, row.source_definition_id):
                continue
            if kind == 'condition' and row.condition_id == 'condition:typed.heart_anchor':
                continue
            if row.expires_on in (None, 'UNTIL_REMOVED'):
                continue
            rows.append((kind, row, remaining(engine, row, actor)))
    ledger = [(state, actor.conditions[iid]) for iid, state in concentration.held(actor)]
    if actor.concentration:
        ledger.append((actor.concentration, None))
    ledger.sort(key=lambda row: concentration.continuation_order(actor, row[0]))
    copies = [(copy, held, index) for index, (copy, held) in enumerate(ledger)
        if source_owned(engine, copy.source_definition_id)]
    return rows, copies


@hook('journey_snapshot_actor')
def snapshot(actor, session, aid, engine):
    rows, copies = exported(engine, actor)
    anchors = [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.heart_anchor']
    if not rows and not copies and not anchors:
        return None
    projected = actor.model_copy(deep=True)
    for kind, row, _ in rows:
        (projected.conditions if kind == 'condition' else projected.modifiers).pop(
            row.instance_id if kind == 'condition' else row.modifier_id, None)
    for row in anchors:
        projected.conditions.pop(row.instance_id, None)
    for copy, held, _ in copies:
        if held:
            projected.conditions.pop(held.instance_id, None)
        elif projected.concentration and projected.concentration.started_sequence == copy.started_sequence:
            projected.concentration = None
    return projected


@hook('journey_encounter_settled')
def settled(session, aid, engine, actor):
    rows, copies = exported(engine, actor)
    source = session.state['actors'][aid].setdefault('source_states', {})
    previous = source.get(KEY, {})
    def deadline(left):
        value = session.clock() + left
        return [value.numerator, value.denominator]
    previous_records = (previous.get('records') or [])
    active_instances = {row.instance_id for kind, row, left in rows if kind == 'condition' and left > 0}
    ended = set(previous.get('ended_declaration_receipts', []))
    for saved in previous_records:
        instance = json.loads(saved['instance'])
        if instance.get('instance_id') not in active_instances:
            receipt = (instance.get('data') or {}).get('declaration_receipt')
            if receipt:
                ended.add(receipt)
    # A source declaration owns one durable effect lifetime. The encounter ends
    # without that lifetime still on the creature (cured, ended or expired), so
    # retire the declaration itself: reopening must not recreate it from the
    # same fact without a new source event.
    from ..fact_consent_admission import read
    from .qi_subpaths_1 import PULSE
    live = {(held.data or {}).get('declaration_receipt') for held in actor.conditions.values()}
    for kind in ('emotional_traits', 'ordinary_emotional_impairment', 'emotional_escalation_sources'):
        receipt = read(session, PULSE, aid, kind, session.state['journey_id'], aid)
        if receipt and receipt['receipt_id'] not in live:
            ended.add(receipt['receipt_id'])
    source[KEY] = {'journey_id': session.state['journey_id'],
        'clock': [session.clock().numerator, session.clock().denominator],
        'ended_declaration_receipts': sorted(ended),
        'records': [{'kind': kind, 'instance': row.model_dump_json(), 'deadline': deadline(left)}
            for kind, row, left in rows if left > 0],
        'copies': [{'instance': copy.model_dump_json(), 'order': order,
            **({'held': held.model_dump_json()} if held else {})} for copy, held, order in copies]}
    # Removal by a real qualifying native countermeasure ends the cultivated
    # anchor in the journey too; a later encounter must not recreate it.
    rites = source.get(STATE)
    if rites:
        # Heart Release's Advantage is spent per rite; the source record must
        # keep that use, since heart_anchor is not serialized as a condition.
        for held in actor.conditions.values():
            if held.condition_id == 'condition:typed.heart_anchor' and held.data.get('release_check_used'):
                for bucket in ('rites', 'anchors'):
                    row = rites.get(bucket, {}).get(held.source_actor_id)
                    if row is not None:
                        row['release_check_used'] = 1
        active = {c.source_actor_id for c in actor.conditions.values()
            if c.condition_id == 'condition:typed.heart_anchor' and c.data.get('deep')}
        for owner in list(rites.get('anchors', {})):
            if owner not in active:
                del rites['anchors'][owner]


@hook('journey_combat_setup')
def setup(session, aid):
    saved = session.state['actors'][aid].get('source_states', {}).get(KEY)
    if not saved:
        return None
    return {'emotion_continuation': json.dumps({**saved, 'records': [
        {**row, 'remaining': [(left := max(Fraction(0), Fraction(*row['deadline']) - session.clock())).numerator, left.denominator]}
        for row in saved['records'] if Fraction(*row['deadline']) > session.clock()]}, sort_keys=True)}


@hook('activity_initialize')
@hook('match_initialize')
def restore(engine):
    from .. import concentration, effect_continuation
    from .effect_durations import expiry_after_seconds
    for bundle in engine.typed_bundle_documents:
        raw = (bundle.get('journey_setup') or {}).get('emotion_continuation')
        actor = engine.state.actors.get(bundle['actor_id'])
        if raw is None or actor is None:
            continue
        data = json.loads(raw)
        # restore_copy gives each continued copy a new start sequence; dependent
        # concentration deadlines must target that restored copy, not the old one.
        restored_sequence = {}
        for copy in data['copies']:
            previous = json.loads(copy['instance'])
            state = concentration.restore_copy(engine, actor, previous, origin_order=copy['order'],
                held_condition=json.loads(copy['held']) if copy.get('held') else None)
            restored_sequence[int(previous['started_sequence'])] = int(state.started_sequence)
        for row in data['records']:
            instance = json.loads(row['instance'])
            # The declaration's materialized condition and its continued record
            # are the same effect. Whichever initializer runs first wins; the
            # other must not add a duplicate lifetime.
            live = {(held.data or {}).get('declaration_receipt') for held in actor.conditions.values()}
            declaration = (instance.get('data') or {}).get('declaration_receipt')
            if declaration is not None and declaration in live:
                continue
            deadline = (instance.get('data') or {})
            if instance.get('condition_id') == DEADLINE and deadline.get('started_sequence') in restored_sequence:
                instance['data'] = {**deadline, 'started_sequence': restored_sequence[deadline['started_sequence']]}
            expiry = expiry_after_seconds(engine, Fraction(*row['remaining']))
            if row['kind'] == 'condition':
                effect_continuation.restore_condition(engine, actor, instance, expires_on=expiry)
            else:
                effect_continuation.restore_modifier(engine, actor, instance, expires_on=expiry)


@hook('journey_native_timers')
def timers(session):
    rows = []
    for aid, actor in session.state['actors'].items():
        saved = actor.get('source_states', {}).get(KEY) or {}
        for row in saved.get('records', []):
            instance = json.loads(row['instance'])
            left = max(Fraction(0), Fraction(*row['deadline']) - session.clock())
            rows.append({'actor_id': aid, 'kind': row['kind'], 'instance_id': instance.get('instance_id') or instance.get('modifier_id'),
                'remaining': [left.numerator, left.denominator], 'deadline': list(row['deadline'])})
    return rows


@hook('journey_native_time_settled')
def exact_deadlines(session, timers):
    for timer in timers:
        saved = session.state['actors'][timer['actor_id']].get('source_states', {}).get(KEY) or {}
        for row in saved.get('records', []):
            instance = json.loads(row['instance'])
            if (instance.get('instance_id') or instance.get('modifier_id')) == timer.get('runtime_instance_id'):
                row['deadline'] = list(timer['deadline'])


@hook('journey_initialize')
def rebase(session, aid):
    saved = session.state['actors'][aid].get('source_states', {}).get(KEY)
    if not saved:
        return
    if saved['journey_id'] != session.state['journey_id']:
        old = Fraction(*saved['clock'])
        for row in saved['records']:
            due = session.clock() + max(Fraction(0), Fraction(*row['deadline']) - old)
            row['deadline'] = [due.numerator, due.denominator]
    saved['journey_id'] = session.state['journey_id']


@hook('journey_elapsed')
def clock(session, aid, before, seconds, moving):
    saved = session.state['actors'][aid].get('source_states', {}).get(KEY)
    if saved:
        saved['clock'] = [session.clock().numerator, session.clock().denominator]
