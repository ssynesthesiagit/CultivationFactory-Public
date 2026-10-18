"""Yin–Yang consumers of the public native journey continuation contract.

This module transports actual committed instances; it does not acquire features,
cast techniques, renew durations, or manufacture application/creation events.
The family implementation owns all mechanical behavior in yin_yang_cultivator.
"""
import json
from copy import deepcopy
from fractions import Fraction

from . import hook
from .yin_yang_cultivator import FLOW, CURRENT, UNITY, PREFIX

KEY = FLOW


def state(session, aid):
    return session.state['actors'][aid].get('source_states', {}).get(KEY)


def available(session, aid, kind):
    """Current sealed acquisition gate, never ownership from a continuation."""
    from .yin_yang_cultivator import BLOCK, TIERS
    from .activation_requirements import effective_cl
    from ..gate2_runtime_models import ConditionInstance
    from types import SimpleNamespace
    actor = session.state['actors'][aid]
    # Read-only adapter of actual committed permanent conditions. This neither
    # declares suppression nor fabricates ownership or a mechanical result.
    conditions = (actor.get('encounter_snapshot') or {}).get('conditions') or {}
    snapshot = SimpleNamespace(conditions={iid: ConditionInstance.model_validate_json(raw) for iid, raw in conditions.items()})
    rows = actor['bundle'].get('typed_passives', ())
    return any(row.get('block') == BLOCK and row.get('kind') == kind
        and effective_cl(snapshot, min(int(row['numbers']['cl']), int(row['numbers'].get('source_cl') or row['numbers']['cl']))) >= TIERS[kind]
        for row in rows)


def deadline(session, remaining):
    value = session.clock() + remaining
    return [value.numerator, value.denominator]


@hook('journey_initialize')
def rebase_clock(session, aid):
    saved = state(session, aid)
    if saved is None:
        return
    if saved.get('journey_id') != session.state['journey_id']:
        old = Fraction(*saved['clock'])
        for row in saved['records']:
            row['deadline'] = deadline(session, max(Fraction(0), Fraction(*row['deadline']) - old))
    saved['journey_id'] = session.state['journey_id']
    saved['clock'] = [session.clock().numerator, session.clock().denominator]


def left(session, row):
    return max(Fraction(0), Fraction(*row['deadline']) - session.clock())


def export(engine, actor):
    """Pure selection of source-owned state, retaining the whole native ledger."""
    from .effect_durations import remaining_seconds
    from .. import concentration
    rows = []
    for kind, instances in [('condition', actor.conditions.values()), ('modifier', actor.modifiers.values())]:
        for instance in instances:
            owned = (kind == 'condition' and instance.condition_id in (CURRENT, UNITY)) or (
                kind == 'modifier' and instance.source_definition_id == FLOW)
            if not owned:
                continue
            remaining = remaining_seconds(engine, instance.expires_on, source_actor_id=instance.source_actor_id)
            if remaining is None:
                raise ValueError('Yin–Yang continuation requires a recognized native duration')
            rows.append((kind, instance, remaining))
    zones = [z for z in engine.state.zones.values() if z.active and z.owner_id == actor.entity_id
             and z.trigger_profile.get('yin_yang_field')]
    ledger = [*(('held', c, actor.conditions[iid]) for iid, c in concentration.held(actor)),
              *([('current', actor.concentration, None)] if actor.concentration else [])]
    ledger.sort(key=lambda row: concentration.continuation_order(actor, row[1]))
    copies = [(kind, copy, condition, order) for order, (kind, copy, condition) in enumerate(ledger)
              if copy.zone_id in {z.zone_id for z in zones}]
    for zone in zones:
        remaining = remaining_seconds(engine, zone.trigger_profile.get('duration_deadline'))
        if remaining is None:
            raise ValueError('Taiji Field continuation requires its actual native deadline')
        rows.append(('zone', zone, remaining))
    return rows, copies


@hook('journey_snapshot_actor')
def snapshot(creature, session, aid, engine):
    rows, copies = export(engine, creature)
    if not rows and not copies:
        return None
    from ..concentration import project_without_copies
    projected = project_without_copies(creature, [copy for _kind, copy, _condition, _order in copies])
    for kind, instance, _remaining in rows:
        if kind == 'condition':
            projected.conditions.pop(instance.instance_id)
        elif kind == 'modifier':
            projected.modifiers.pop(instance.modifier_id)
    return projected


@hook('journey_encounter_settled')
def settled(session, aid, engine, creature, *, effects_ended=False):
    rows, copies = export(engine, creature)
    if effects_ended:
        # The GM ended this creature's timed encounter effects (journey_resume).
        # Every exported row is timed, so none may return on the next entry.
        rows, copies = [], []
    source_states = session.state['actors'][aid].setdefault('source_states', {})
    if not rows:
        source_states.pop(KEY, None)
        return
    source_states[KEY] = {
        'journey_id': session.state['journey_id'],
        'clock': [session.clock().numerator, session.clock().denominator],
        'records': [{'kind': kind, 'instance': instance.model_dump_json(), 'deadline': deadline(session, remaining)}
                    for kind, instance, remaining in rows if remaining > 0],
        'copies': [{'kind': kind, 'instance': copy.model_dump_json(), 'order': order,
                    **({'condition': condition.model_dump_json()} if condition else {})}
                   for kind, copy, condition, order in copies],
        'rotation': str(creature.turn_flags.get('_round_taiji_rotation') or 'yin')}
    session.emit('YIN_YANG_CONTINUED', aid, source=FLOW, match_id=engine.state.match_id,
                 text='Yin–Yang effects continue with their actual remaining durations; no technique is cast again.')


@hook('journey_combat_setup')
def setup_document(session, aid):
    saved = state(session, aid)
    if not saved:
        return None
    if (not available(session, aid, 'ultimate_unity') and available(session, aid, 'taiji_field')
            and unfocused_fields(session, saved)):
        raise ValueError('Ultimate Unity is no longer available. The field owner must first choose whether to maintain Taiji Field with Concentration or end it.')
    return {'yin_yang_continuation': {
        **deepcopy(saved), 'records': [{**row, 'remaining': [left(session, row).numerator, left(session, row).denominator]}
                                    for row in saved['records'] if left(session, row) > 0]}}


@hook('match_initialize')
@hook('activity_initialize')
def restore(engine):
    from .. import concentration, effect_continuation, zones
    from ..gate2_runtime_models import ZoneState
    from .effect_durations import expiry_after_seconds
    from .yin_yang_cultivator import owns
    restored = False
    for bundle in engine.typed_bundle_documents:
        saved = (bundle.get('journey_setup') or {}).get('yin_yang_continuation')
        actor = engine.state.actors.get(bundle['actor_id'])
        if not saved or actor is None:
            continue
        restored = True
        records = []
        for row in saved['records']:
            instance = json.loads(row['instance'])
            kind = ('taiji_field' if row['kind'] == 'zone' else
                    'ultimate_unity' if row['kind'] == 'condition' and instance['condition_id'] == UNITY else
                    'balanced_flow' if row['kind'] == 'condition' and instance['condition_id'] == CURRENT else None)
            if kind is not None and not owns(engine, actor, kind):
                engine._append_event('PASSIVE_TRIGGERED', PREFIX + kind, actor_id=actor.entity_id,
                    payload={'continued_instance': instance.get('instance_id') or instance.get('zone_id'),
                        'reason': 'FEATURE_ACCESS_UNAVAILABLE',
                        'log': 'The ongoing effect ends because this character no longer has access to its source.'})
                continue
            records.append(row)
        active_zones = {json.loads(row['instance'])['zone_id'] for row in records if row['kind'] == 'zone'}
        for row in saved['copies']:
            previous = json.loads(row['instance'])
            if previous.get('zone_id') in active_zones:
                concentration.restore_copy(engine, actor, previous, origin_order=row['order'],
                    held_condition=json.loads(row['condition']) if row['kind'] == 'held' else None)
        for row in records:
            expires = expiry_after_seconds(engine, Fraction(*row['remaining']))
            instance = json.loads(row['instance'])
            if (row['kind'] == 'modifier' and instance['source_definition_id'] == FLOW
                    or row['kind'] == 'condition' and instance['condition_id'] == CURRENT):
                if instance['source_actor_id'] in engine.state.actors:
                    # A new actual source turn ends this one-turn effect even
                    # when the receiving encounter has a different slot order.
                    # Ordinary journey time still uses its exact saved timer.
                    expires = 'START_OF_SOURCE_NEXT_TURN'
            if row['kind'] == 'zone':
                zone = ZoneState.model_validate(instance)
                zone.trigger_profile['duration_deadline'] = expires
                from ..zone_sources import capture
                source_row = owns(engine, actor, 'taiji_field')
                zone.trigger_profile['source_profile'] = capture(zone.trigger_profile.get('source_profile'), source_row['numbers'])
                zone.trigger_profile['numbers'] = dict(source_row['numbers'])
                zones.restore(engine, zone, zone.source_definition_id)
            else:
                function = effect_continuation.restore_condition if row['kind'] == 'condition' else effect_continuation.restore_modifier
                function(engine, actor, instance, expires_on=expires)
        actor.turn_flags['_round_taiji_rotation'] = saved['rotation']
    return True if restored else None


@hook('journey_elapsed')
def elapsed(session, aid, previous, seconds, moving):
    if getattr(session, 'native_activity_advancing', False):
        return  # native expiry/owner decisions are authoritative while active
    saved = state(session, aid)
    if saved is None:
        return
    saved['clock'] = [session.clock().numerator, session.clock().denominator]
    expired = [row for row in saved['records'] if left(session, row) <= 0]
    if not expired:
        return
    unity_ended = any(row['kind'] == 'condition' and json.loads(row['instance'])['condition_id'] == UNITY for row in expired)
    if unity_ended:
        focus_after_unity(session, aid, saved)
    saved['records'] = [row for row in saved['records'] if row not in expired]
    zone_ids = {json.loads(row['instance'])['zone_id'] for row in saved['records'] if row['kind'] == 'zone'}
    saved['copies'] = [row for row in saved['copies'] if json.loads(row['instance']).get('zone_id') in zone_ids]
    for row in expired:
        instance = json.loads(row['instance'])
        session.emit('YIN_YANG_EFFECT_EXPIRED', aid, source=instance['source_definition_id'],
                     instance=instance, text='The printed remaining Yin–Yang duration ends.')


@hook('journey_concentration_copies')
def focus_copies(session, aid):
    saved = state(session, aid)
    if saved is None:
        return None
    zones = {json.loads(row['instance'])['zone_id'] for row in saved['records']
             if row['kind'] == 'zone' and left(session, row) > 0}
    return [{'identity': json.loads(row['instance'])['zone_id'], 'order': row['order'], 'name': 'Taiji Field'}
            for row in saved['copies'] if json.loads(row['instance']).get('zone_id') in zones]


@hook('journey_concentration_end')
def end_focus(session, aid, identity, reason):
    saved = state(session, aid)
    if not saved or not any(row['identity'] == identity for row in focus_copies(session, aid)):
        return None
    saved['records'] = [row for row in saved['records'] if not (
        row['kind'] == 'zone' and json.loads(row['instance'])['zone_id'] == identity)]
    saved['copies'] = [row for row in saved['copies'] if json.loads(row['instance']).get('zone_id') != identity]
    session.emit('YIN_YANG_FIELD_ENDED', aid, source=PREFIX + 'taiji_field', zone_id=identity, reason=reason,
                 text='Taiji Field ends because its Concentration ends.')
    return True


def unfocused_fields(session, saved):
    return [row for row in saved['records'] if row['kind'] == 'zone' and left(session, row) > 0
            and not json.loads(row['instance'])['concentration_link']]


def unavailable_unity_handover(session, aid):
    saved = state(session, aid)
    return bool(saved and not available(session, aid, 'ultimate_unity')
        and unfocused_fields(session, saved)
        and any(row['kind'] == 'condition' and json.loads(row['instance'])['condition_id'] == UNITY
                for row in saved['records']))


@hook('journey_native_activity_gate')
def unresolved_unity_activity(session, aid):
    return False if any(unavailable_unity_handover(session, owner) for owner in session.state['actors']) else None


@hook('journey_time_gate')
def unresolved_unity_time(session, seconds):
    if any(unavailable_unity_handover(session, aid) for aid in session.state['actors']):
        raise ValueError('Ultimate Unity is unavailable. Each field owner must choose which Taiji Fields to maintain with Concentration and which to end before time passes.')


@hook('journey_initialized')
def automatic_unavailable_unity(session):
    from ..concentration import journey_copies, journey_limit
    for aid, actor in session.state['actors'].items():
        if actor['control_mode'] != 'LOCAL_AUTO' or not unavailable_unity_handover(session, aid):
            continue
        saved = state(session, aid)
        limit = journey_limit(session, aid)
        free = len(unfocused_fields(session, saved)) if limit is None else max(0, limit - len(journey_copies(session, aid)))
        ordered = sorted(unfocused_fields(session, saved), key=lambda row: (left(session, row), json.loads(row['instance'])['zone_id']), reverse=True)
        saved['unity_expiry_choices'] = {}
        for index, row in enumerate(ordered):
            iid = json.loads(row['instance'])['zone_id']
            choice = {'field_id': iid, 'mode': 'maintain' if index < free and available(session, aid, 'taiji_field') else 'end', 'end_existing': []}
            saved['unity_expiry_choices'][iid] = choice
            session.emit('YIN_YANG_UNITY_EXPIRY_CHOSEN', aid, source=PREFIX + 'ultimate_unity', choice=choice,
                decision_owner='LOCAL_AUTO', text='The computer-controlled field owner keeps the longest remaining fields that fit its free Concentration slots and ends the others.')
        complete_unity_loss(session, aid, saved)


@hook('journey_native_timers')
def native_timers(session):
    rows = []
    for aid in session.state['actors']:
        saved = state(session, aid)
        for row in (saved or {}).get('records', ()):
            instance = json.loads(row['instance'])
            iid = instance.get('instance_id') or instance.get('modifier_id') or instance.get('zone_id')
            value = left(session, row)
            rows.append(dict(actor_id=aid, kind=row['kind'], instance_id=iid,
                remaining=[value.numerator, value.denominator], deadline=row['deadline']))
    return rows


@hook('journey_native_time_settled')
def retain_exact_deadlines(session, timers):
    deadlines = {(row['actor_id'], row['kind'], row['runtime_instance_id']): row['deadline'] for row in timers}
    for aid in session.state['actors']:
        saved = state(session, aid)
        for row in (saved or {}).get('records', ()):
            instance = json.loads(row['instance'])
            iid = instance.get('instance_id') or instance.get('modifier_id') or instance.get('zone_id')
            if (aid, row['kind'], iid) in deadlines:
                row['deadline'] = deadlines[aid, row['kind'], iid]


@hook('journey_options')
def expiry_options(session, aid):
    saved = state(session, aid)
    if session.state['phase'] != 'travel' or session.state.get('native_activity') or saved is None:
        return None
    if available(session, aid, 'ultimate_unity'):
        return None  # ordinary expiry uses the actual native owner checkpoint
    if not unfocused_fields(session, saved) or not any(row['kind'] == 'condition'
            and json.loads(row['instance'])['condition_id'] == UNITY and left(session, row) > 0 for row in saved['records']):
        return None
    rows = []
    for row in unfocused_fields(session, saved):
        zone = json.loads(row['instance'])
        name = f"Taiji Field at square ({zone['center']['x']}, {zone['center']['y']})"
        for mode in ('maintain', 'end'):
            rows.append({'id': 'yin_yang:unity_expiry:' + zone['zone_id'] + ':' + mode,
                'kind': 'yin_yang_unity_expiry', 'payload': {'field_id': zone['zone_id'], 'mode': mode, 'end_existing': []},
                'label': ('Ultimate Unity is unavailable: maintain ' + name + ' with Concentration for only its remaining duration. '
                    'Choose existing Concentration copies to end if capacity requires it.' if mode == 'maintain' else
                    'Ultimate Unity is unavailable: end ' + name + '; no cost or refund.')})
    return rows


@hook('journey_command')
def choose_expiry(session, aid, kind, payload):
    if kind != 'yin_yang_unity_expiry':
        return None
    from ..journey import require
    from ..concentration import journey_copies, journey_limit
    saved = state(session, aid)
    require(saved is not None and expiry_options(session, aid), 'Choose the owner of an active Unity and Taiji Field.')
    require(set(payload) == {'field_id', 'mode', 'end_existing'} and payload['mode'] in ('maintain', 'end')
            and isinstance(payload['end_existing'], list)
            and all(type(value) is str for value in payload['end_existing'])
            and len(set(payload['end_existing'])) == len(payload['end_existing']), 'Choose whether to maintain the field and exact existing focus copies to end.')
    copies = journey_copies(session, aid)
    field_ids = {json.loads(row['instance'])['zone_id'] for row in unfocused_fields(session, saved)}
    require(type(payload['field_id']) is str and payload['field_id'] in field_ids,
        'Choose one of this creature’s actual continuing fields.')
    require(set(payload['end_existing']) <= {row['identity'] for row in copies}, 'Choose only this creature’s actual Concentration copies.')
    limit = journey_limit(session, aid)
    require(payload['mode'] == 'maintain' or not payload['end_existing'], 'Ending the field cannot end unrelated Concentration.')
    require(payload['mode'] != 'maintain' or available(session, aid, 'taiji_field'),
        'This character no longer has access to Taiji Field and cannot maintain it.')
    plans = saved.setdefault('unity_expiry_choices', {})
    plans[payload['field_id']] = deepcopy(payload)
    complete = field_ids <= set(plans)
    if complete:
        maintained = [plans[iid] for iid in field_ids if plans[iid]['mode'] == 'maintain']
        ended = {identity for choice in maintained for identity in choice['end_existing']}
        require(limit is None or len(copies) - len(ended) + len(maintained) <= limit,
            'Choose which fields to maintain within your Concentration limit, and which existing Concentration copies to end.')
    session.emit('YIN_YANG_UNITY_EXPIRY_CHOSEN', aid, source=PREFIX + 'ultimate_unity', choice=deepcopy(payload),
        text='The field owner chooses what happens to Taiji Field when Ultimate Unity ends; its remaining duration is not renewed.')
    if complete and not available(session, aid, 'ultimate_unity'):
        complete_unity_loss(session, aid, saved)
    return True


def complete_unity_loss(session, aid, saved):
    focus_after_unity(session, aid, saved)
    ended_instances = [row['instance'] for row in saved['records'] if row['kind'] == 'condition'
                       and json.loads(row['instance'])['condition_id'] == UNITY]
    saved['records'] = [row for row in saved['records'] if not (row['kind'] == 'condition'
        and json.loads(row['instance'])['condition_id'] == UNITY)]
    session.emit('YIN_YANG_UNITY_ENDED', aid, source=PREFIX + 'ultimate_unity', reason='FEATURE_ACCESS_UNAVAILABLE',
        ended_instances=ended_instances,
        text='Ultimate Unity ends because this character no longer has access to it; no Qi is refunded.')
    if not any(unavailable_unity_handover(session, owner) for owner in session.state['actors']):
        from ..journey_effect_time import advance
        advance(session, 0, settle=True, actor_id=aid)


def focus_after_unity(session, aid, saved):
    from ..concentration import journey_copies, end_journey_copy, journey_limit
    from ..gate2_runtime_models import ConcentrationState
    from ..journey import require
    fields = unfocused_fields(session, saved)
    if not fields:
        return
    choices = saved.pop('unity_expiry_choices', {})
    ids = {json.loads(row['instance'])['zone_id'] for row in fields}
    require(ids <= set(choices), 'The field owner must resolve each field’s Concentration when Ultimate Unity ends.')
    maintained = [row for row in fields if choices[json.loads(row['instance'])['zone_id']]['mode'] == 'maintain']
    ended_fields = [row for row in fields if row not in maintained]
    for row in ended_fields:
        zone = json.loads(row['instance'])
        saved['records'].remove(row)
        session.emit('YIN_YANG_FIELD_ENDED', aid, source=PREFIX + 'taiji_field', zone_id=zone['zone_id'],
            reason='UNITY_EXPIRED_OWNER_DECLINED', text='Ultimate Unity ends; the owner ends this Taiji Field instead of maintaining Concentration.')
    end_existing = {identity for iid in ids for identity in choices[iid]['end_existing']}
    for identity in end_existing:
        if any(row['identity'] == identity for row in journey_copies(session, aid)):
            end_journey_copy(session, aid, identity, 'OWNER_MAINTAINS_TAIJI_AFTER_UNITY')
    copies = journey_copies(session, aid)
    limit = journey_limit(session, aid)
    require(limit is None or len(copies) + len(maintained) <= limit, 'Concentration capacity changed; refresh the owner’s Taiji Field decision.')
    order = max([row['order'] for row in copies], default=-1) + 1
    for row in maintained:
        zone = json.loads(row['instance'])
        zone['concentration_link'] = True
        profile = zone['trigger_profile'].get('source_profile')
        if profile is not None:
            profile['concentration'] = 1
        row['instance'] = json.dumps(zone, sort_keys=True)
        focus = ConcentrationState(source_definition_id=zone['source_definition_id'], zone_id=zone['zone_id'],
            started_sequence=len(session.state['events']) + 1)
        saved['copies'].append({'kind': 'current', 'instance': focus.model_dump_json(), 'order': order})
        session.emit('YIN_YANG_FIELD_CONCENTRATION_STARTED', aid, source=zone['source_definition_id'], zone_id=zone['zone_id'],
            concentration=focus.model_dump_json(), text='Ultimate Unity ends; the owner maintains Taiji Field with Concentration for its remaining duration.')
        order += 1
