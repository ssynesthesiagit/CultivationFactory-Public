"""Digestive Mantle consumer of the shared native elapsed-effect contract.

Only actual Mantle conditions and modifiers are exported. Restoration does not
activate a Mantle, spend Satiety or repeat its benefits. Native expiry invokes
the existing Hunger provider's ending procedure, including its real costs,
saves and owner choices, before ordinary travel can continue.
"""
import json
from fractions import Fraction

from . import hook
from .hunger_riders import MANTLE_ID

KEY = 'hunger.mantle_continuation'


def records(session, aid):
    return session.state['actors'][aid].get('source_states', {}).get(KEY, [])


def left(session, row):
    return max(Fraction(0), Fraction(*row['deadline']) - session.clock())


def exported(engine, actor):
    from .ability_source import mechanic_at
    from .effect_durations import remaining_seconds
    for kind, instances in [('condition', actor.conditions.values()), ('modifier', actor.modifiers.values())]:
        for instance in instances:
            source = instance.source_definition_id
            if source != MANTLE_ID and mechanic_at(engine, source) != MANTLE_ID:
                continue
            remaining = remaining_seconds(engine, instance.expires_on,
                source_actor_id=instance.source_actor_id, holder_actor_id=actor.entity_id)
            if remaining is not None:
                yield kind, instance, remaining


@hook('journey_snapshot_actor')
def snapshot(actor, session, aid, engine):
    rows = list(exported(engine, actor))
    if not rows:
        return None
    result = actor.model_copy(deep=True)
    for kind, instance, _ in rows:
        (result.conditions if kind == 'condition' else result.modifiers).pop(
            instance.instance_id if kind == 'condition' else instance.modifier_id)
    return result


@hook('journey_encounter_settled')
def settled(session, aid, engine, creature):
    rows = []
    for kind, instance, remaining in exported(engine, creature):
        deadline = session.clock() + remaining
        rows.append({'kind': kind, 'instance': instance.model_dump_json(),
            'deadline': [deadline.numerator, deadline.denominator]})
    saved = session.state['actors'][aid].setdefault('source_states', {})
    if rows:
        saved[KEY] = rows
    else:
        saved.pop(KEY, None)


@hook('journey_combat_setup')
def setup(session, aid):
    rows = records(session, aid)
    if rows:
        return {'hunger_mantle_continuation': [{**row,
            'remaining': [left(session, row).numerator, left(session, row).denominator]} for row in rows]}


@hook('match_initialize')
@hook('activity_initialize')
def restore(engine):
    from ..effect_continuation import restore_condition, restore_modifier
    from .effect_durations import expiry_after_seconds
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None:
            continue
        for row in bundle.get('journey_setup', {}).get('hunger_mantle_continuation', []):
            restore_instance = restore_condition if row['kind'] == 'condition' else restore_modifier
            restore_instance(engine, actor, json.loads(row['instance']),
                expires_on=expiry_after_seconds(engine, Fraction(*row['remaining'])))


@hook('journey_native_timers')
def native_timers(session):
    from ..effect_continuation import native_timer_records
    return [timer for aid in session.state['actors']
        for timer in native_timer_records(aid, records(session, aid), lambda row: left(session, row))]


@hook('journey_native_time_settled')
def exact_deadlines(session, timers):
    from ..effect_continuation import retain_timer_deadlines
    for aid in session.state['actors']:
        retain_timer_deadlines(aid, records(session, aid), timers)
