"""Source-owned Lotus continuation using the public journey/effect transports.

Only actual committed Root support, Recovery Field and pressure-resource clock
instances are exported. Neither reopening a journey nor entering combat casts
an ability, restores a use, gains Dew or renews a duration.
"""
import json
from copy import deepcopy
from fractions import Fraction
from . import hook
from .mud_lotus_native import GENERATE, DEW
from .mud_lotus_recovery import CONDITION
from .. import pressure

KEY = GENERATE


@hook('journey_actor_continued')
def rebase(session, aid, previous_clock):
    saved = session.state['actors'][aid].get('source_states', {}).get(KEY)
    if saved is None:
        return None
    offset = session.clock() - previous_clock
    for row in [*saved['records'], *([saved['dew']] if saved.get('dew') else [])]:
        for field in ('deadline', 'round_deadline'):
            if field in row:
                value = Fraction(*row[field]) + offset
                row[field] = [value.numerator, value.denominator]
    return [KEY]


def deadline(session, duration):
    value = session.clock() + duration
    return [value.numerator, value.denominator]


def left(session, row):
    return max(Fraction(0), Fraction(*row['deadline']) - session.clock())


def exported(engine, actor):
    from .effect_durations import remaining_seconds
    rows = []
    for condition in actor.conditions.values():
        if condition.condition_id not in (CONDITION, 'condition:typed.foundations3_boon.lotus',
                                           'condition:typed.humble_medicine_witness'):
            continue
        remaining = remaining_seconds(engine, condition.expires_on, source_actor_id=condition.source_actor_id)
        if remaining is None:
            raise ValueError('Lotus support continuation requires its native duration')
        rows.append(('condition', condition, remaining))
        if condition.condition_id == CONDITION:
            zone = engine.state.zones.get(condition.data.get('zone_id'))
            if zone is not None and zone.active:
                rows.append(('zone', zone, remaining))
    return rows


@hook('journey_snapshot_actor')
def snapshot(actor, session, aid, engine):
    rows = exported(engine, actor)
    if not rows:
        return None
    projected = actor.model_copy(deep=True)
    for kind, instance, _ in rows:
        if kind == 'condition':
            projected.conditions.pop(instance.instance_id)
    return projected


@hook('journey_encounter_settled')
def settled(session, aid, engine, actor):
    rows = exported(engine, actor)
    saved = {'records': [{'kind': kind, 'instance': instance.model_dump_json(),
        'deadline': deadline(session, duration)} for kind, instance, duration in rows if duration > 0]}
    entry = (actor.turn_flags.get(pressure.CLOCK) or {}).get(DEW, {})
    if actor.resources.get(DEW, 0) > 0:
        n = len(engine.state.initiative_order)
        cursor = engine.state.current_slot_index
        if entry.get('deadline'):
            from .effect_durations import remaining_seconds
            remaining = remaining_seconds(engine, entry['deadline'])
        elif entry.get('ends_left'):
            first = (engine.state.initiative_order.index(aid) - cursor) % n + 1
            remaining = Fraction((first + (int(entry['ends_left']) - 1) * n) * 6, n)
        else:
            raise ValueError('Held Lotus Dew must have an actual native expiration clock')
        saved['dew'] = {'deadline': deadline(session, remaining), 'count': int(entry.get('count', 0)),
            'round_deadline': deadline(session, Fraction((n - cursor) * 6, n)) if entry.get('round') == engine.state.round_number
            else deadline(session, 0)}
    actor_state = session.state['actors'][aid]
    if not saved['records'] and not saved.get('dew') and KEY not in actor_state.get('source_states', {}):
        return
    states = actor_state.setdefault('source_states', {})
    if saved['records'] or saved.get('dew'):
        states[KEY] = saved
    else:
        states.pop(KEY, None)


@hook('journey_combat_setup')
def setup(session, aid):
    saved = session.state['actors'][aid].get('source_states', {}).get(KEY)
    if not saved:
        return None
    value = deepcopy(saved)
    value['records'] = [{**row, 'remaining': [left(session, row).numerator, left(session, row).denominator]}
                        for row in saved['records'] if left(session, row) > 0]
    if 'dew' in value:
        duration = left(session, value['dew'])
        round_left = max(Fraction(0), Fraction(*value['dew']['round_deadline']) - session.clock())
        value['dew'].update(remaining=[duration.numerator, duration.denominator],
                            round_remaining=[round_left.numerator, round_left.denominator])
    return {'mud_lotus_continuation': value}


@hook('match_initialize')
@hook('activity_initialize')
def restore(engine):
    from .. import effect_continuation, zones
    from ..gate2_runtime_models import ZoneState
    from .effect_durations import expiry_after_seconds
    restored = False
    for bundle in engine.typed_bundle_documents:
        saved = (bundle.get('journey_setup') or {}).get('mud_lotus_continuation')
        actor = engine.state.actors.get(bundle['actor_id'])
        if not saved or actor is None:
            continue
        restored = True
        for row in saved['records']:
            expires = expiry_after_seconds(engine, Fraction(*row['remaining']))
            instance = json.loads(row['instance'])
            if row['kind'] == 'zone':
                zone = ZoneState.model_validate(instance)
                zone.trigger_profile['duration_deadline'] = expires
                zones.restore(engine, zone, zone.source_definition_id)
            else:
                # Entry into a new native context is a real turn/round boundary;
                # the duration and once-field injury flag are retained.
                if instance['condition_id'] == CONDITION:
                    instance['data'].update(used_round=-1, hostile_turn='')
                effect_continuation.restore_condition(engine, actor, instance, expires_on=expires)
        if saved.get('dew'):
            row = saved['dew']
            pressure.continue_clock(engine, actor, DEW, remaining=Fraction(*row['remaining']),
                round_remaining=Fraction(*row['round_remaining']), count=row['count'])
    return True if restored else None


@hook('journey_elapsed')
def elapsed(session, aid, previous, seconds, moving):
    if getattr(session, 'native_activity_advancing', False):
        return  # Native turns expire actual state; save exports the new ledger.
    actor = session.state['actors'][aid]
    saved = actor.get('source_states', {}).get(KEY)
    if not saved:
        return
    saved['records'] = [row for row in saved['records'] if left(session, row) > 0]
    if saved.get('dew') and left(session, saved['dew']) <= 0:
        actor['resources'][DEW] = 0
        saved.pop('dew')
        session.emit('RESOURCE_EXPIRED', aid, resource_id=DEW, source_id=GENERATE,
                     text='Lotus Dew expires at its remaining native turn deadline.')


@hook('turn_start')
def continued_clocks(engine, actor):
    pressure.sweep_continued(engine)
