"""Continue actual classified consequences through the shared journey contract.

Source procedures/native condition admission produce the declaration marker and
its exact linked condition/modifier identities. This consumer exports those
real instances, keeps each actual remaining clock, and restores state without
reapplying damage, rolls, treatment or on-gain effects. Rest recovery applies
only to source-defined Strain explicitly declaring that recovery route.
"""
import json
from copy import deepcopy
from fractions import Fraction
from . import hook

KEY = 'system:source.consequences'


@hook('journey_actor_continued')
def rebase(session, aid, previous_clock):
    saved = session.state['actors'][aid].get('source_states', {}).get(KEY)
    if saved is None:
        return None
    for row in saved['records']:
        if 'deadline' in row:
            value = Fraction(*row['deadline']) - previous_clock + session.clock()
            row['deadline'] = [value.numerator, value.denominator]
    return [KEY]


@hook('journey_conditions')
def conditions(actor):
    from ..gate2_runtime_models import ConditionInstance
    saved = actor.get('source_states', {}).get(KEY) or {}
    return [ConditionInstance.model_validate_json(row['instance'])
            for row in saved.get('records', ()) if row['kind'] == 'condition']


def identity(kind, instance):
    return instance.instance_id if kind == 'condition' else instance.modifier_id


def markers(actor):
    return [c for c in actor.conditions.values() if c.condition_id.startswith('condition:source.')
            and c.data.get('declaration') and 'effect_conditions' in c.data and 'effect_modifiers' in c.data]


def exported(engine, actor):
    from .effect_durations import remaining_seconds, skipped_expiry_slots
    selected = {}
    for marker in markers(actor):
        selected[marker.instance_id] = ('condition', marker, 1)
        for kind, field, instances in (('condition', 'effect_conditions', actor.conditions),
                                      ('modifier', 'effect_modifiers', actor.modifiers)):
            for key in json.loads(marker.data[field]):
                if key in instances:
                    selected[key] = (kind, instances[key], 0)
    result = []
    for kind, instance, is_marker in selected.values():
        persistent = instance.expires_on in (None, 'UNTIL_REMOVED')
        remaining = None if persistent else remaining_seconds(engine, instance.expires_on,
            source_actor_id=instance.source_actor_id, holder_actor_id=actor.entity_id,
            skipped=skipped_expiry_slots(actor, instance))
        if not persistent and remaining is None:
            raise ValueError('A source consequence requires a recognized native continuation clock')
        result.append((kind, instance, is_marker, remaining))
    return result


@hook('journey_snapshot_actor')
def snapshot(actor, session, aid, engine):
    rows = exported(engine, actor)
    if not rows:
        return None
    result = actor.model_copy(deep=True)
    for kind, instance, _marker, _remaining in rows:
        (result.conditions if kind == 'condition' else result.modifiers).pop(identity(kind, instance), None)
    return result


@hook('journey_encounter_settled')
def settled(session, aid, engine, actor):
    records = []
    for kind, instance, marker, remaining in exported(engine, actor):
        if remaining is not None and remaining <= 0:
            continue
        row = {'kind': kind, 'id': identity(kind, instance), 'marker': marker, 'instance': instance.model_dump_json()}
        if remaining is not None:
            deadline = session.clock() + remaining
            row['deadline'] = [deadline.numerator, deadline.denominator]
        records.append(row)
    actor_state = session.state['actors'][aid]
    if not records and KEY not in actor_state.get('source_states', {}):
        return
    states = actor_state.setdefault('source_states', {})
    if records:
        states[KEY] = {'records': records}
    else:
        states.pop(KEY, None)


def remaining(session, row):
    return max(Fraction(0), Fraction(*row['deadline']) - session.clock()) if 'deadline' in row else None


@hook('journey_combat_setup')
def setup(session, aid):
    saved = session.state['actors'][aid].get('source_states', {}).get(KEY)
    if not saved:
        return None
    records = []
    for row in saved['records']:
        duration = remaining(session, row)
        if duration is not None and duration <= 0:
            continue
        result = deepcopy(row)
        if duration is not None:
            result['remaining'] = [duration.numerator, duration.denominator]
        records.append(result)
    return {'source_consequence_continuation': records}


@hook('match_initialize')
@hook('activity_initialize')
def restore(engine):
    from .. import effect_continuation
    from .effect_durations import expiry_after_seconds
    restored = False
    for bundle in engine.typed_bundle_documents:
        rows = (bundle.get('journey_setup') or {}).get('source_consequence_continuation')
        actor = engine.state.actors.get(bundle['actor_id'])
        if not rows or actor is None:
            continue
        restored = True
        ids = {}
        # Restore effects before their classification so every treatment link
        # points to the actual rekeyed native instance, never an old match ID.
        for row in sorted(rows, key=lambda row: row['marker']):
            instance = json.loads(row['instance'])
            expires = expiry_after_seconds(engine, Fraction(*row['remaining'])) if 'remaining' in row else instance['expires_on']
            if row['marker']:
                for field in ('effect_conditions', 'effect_modifiers'):
                    instance['data'][field] = json.dumps([ids[key] for key in json.loads(instance['data'][field]) if key in ids])
            if row['kind'] == 'condition':
                audience = json.loads(instance['data']['source_audience']) if row['marker'] else None
                current = effect_continuation.restore_condition(engine, actor, instance,
                    expires_on=expires, audience_actor_ids=audience)
            else:
                current = effect_continuation.restore_modifier(engine, actor, instance, expires_on=expires)
            ids[row['id']] = identity(row['kind'], current)
    return True if restored else None


@hook('journey_elapsed')
def elapsed(session, aid, previous, seconds, moving):
    if getattr(session, 'native_activity_advancing', False):
        return
    saved = session.state['actors'][aid].get('source_states', {}).get(KEY)
    if not saved:
        return
    from .journey_setup import journey_incapacitated
    was_incapacitated = journey_incapacitated(session.state['actors'][aid])
    saved['records'] = [row for row in saved['records'] if remaining(session, row) is None or remaining(session, row) > 0]
    live_ids = {row['id'] for row in saved['records']}
    # An ordinary condition's private classification cannot outlive the actual
    # condition/modifier it classifies. Authored injury history remains until
    # its own source clock or a real treatment/recovery route removes it.
    for row in list(saved['records']):
        if row['marker']:
            data = json.loads(row['instance'])['data']
            links = [*json.loads(data['effect_conditions']), *json.loads(data['effect_modifiers'])]
            if data.get('native_condition_record') and not live_ids.intersection(links):
                saved['records'].remove(row)
    refresh_status(session, aid, was_incapacitated)


def refresh_status(session, aid, previously_incapacitated):
    """Release a native expired/recovered status, preserving later manual input."""
    from .journey_setup import journey_incapacitated
    actor = session.state['actors'][aid]
    if not previously_incapacitated or journey_incapacitated(actor):
        return
    actor['incapacitated'] = int(actor.get('declared_travel_incapacitated', 0))


def rest_recovery(session, aid):
    saved = session.state['actors'][aid].get('source_states', {}).get(KEY)
    if not saved:
        return
    from .journey_setup import journey_incapacitated
    was_incapacitated = journey_incapacitated(session.state['actors'][aid])
    removed = set()
    for row in saved['records']:
        if row['marker']:
            data = json.loads(row['instance'])['data']
            declaration = json.loads(data['declaration'])
            if declaration.get('kind') == 'strain' and declaration.get('recovery_mode') == 'rest':
                removed.update((row['id'], *json.loads(data['effect_conditions']), *json.loads(data['effect_modifiers'])))
    if removed:
        saved['records'] = [row for row in saved['records'] if row['id'] not in removed]
        refresh_status(session, aid, was_incapacitated)
        session.emit('SOURCE_STRAIN_RECOVERED', aid, removed_instances=len(removed),
            text='The completed rest clears this source-defined Strain and its linked penalties; no damage or payment is repeated.')


@hook('shared_short_rest_recovery')
def short_rest(session, leader, roster):
    for aid in roster:
        rest_recovery(session, aid)


@hook('journey_rest')
def long_rest(session, aid):
    rest_recovery(session, aid)
