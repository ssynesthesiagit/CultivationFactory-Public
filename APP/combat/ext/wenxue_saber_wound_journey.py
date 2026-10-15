"""Native elapsed-scene Medicine for actual persistent Saber Wounds.

Uses journey_setup's existing encounter snapshot; no parallel wound schema,
synthetic fight, GM end-effects button, healing or resource recovery is used.
"""
import json
from . import hook
from .wenxue_saber_wounds import PREFIX, TREAT, wound_label


def saved_wounds(session, actor_id):
    from ..gate2_runtime_models import ConditionInstance
    snapshot = session.state['actors'][actor_id].get('encounter_snapshot') or {}
    result = {}
    for key, text in snapshot.get('conditions', {}).items():
        condition = ConditionInstance.model_validate(json.loads(text))
        if (condition.condition_id == PREFIX + condition.source_actor_id
                and type(condition.data.get('count')) is int and 1 <= condition.data['count'] <= 2
                and type(condition.data.get('save_dc')) is int):
            result[key] = condition
    return result


def medicine_bonus(session, actor_id):
    bundle = session.state['actors'][actor_id]['bundle']
    value = (bundle.get('skills') or {}).get('Medicine', (bundle.get('ability_mods') or {}).get('WIS'))
    return value if type(value) is int else None


def attempt_scene(session, actor_id, wound_id):
    return ((session.state['actors'][actor_id].get('source_states') or {}).get(TREAT) or {}).get(wound_id)


@hook('journey_options')
def medicine_options(session, actor_id):
    actor = session.state['actors'][actor_id]
    if session.state['phase'] != 'travel' or actor['incapacitated'] or medicine_bonus(session, actor_id) is None:
        return []
    return [{'id': TREAT + ':' + key, 'kind': 'activate',
        'payload': {'feature': TREAT, 'wound_instance': key},
        # A failed automatic attempt is personal knowledge. All legal retries
        # remain explicit options; the default policy may then continue travel.
        'auto_select': int(attempt_scene(session, actor_id, key) != str(session.state.get('scene_id', session.state['journey_id']))),
        'label': f'Treat one Saber Wound (group {index + 1}): Wisdom (Medicine) check against its creator’s '
            'Sabers save DC. One Action (6 seconds), no Qi or Stamina. Success removes one wound.'}
        for index, (key, condition) in enumerate(saved_wounds(session, actor_id).items())]


@hook('journey_command')
def treat(session, actor_id, kind, payload):
    if kind != 'activate' or payload.get('feature') != TREAT:
        return None
    from ..journey import require
    from ..journey_checks import resolve
    actor = session.state['actors'][actor_id]
    require(set(payload) == {'feature', 'wound_instance'} and type(payload['wound_instance']) is str,
        'Choose one actual Saber Wound to treat.')
    pool = saved_wounds(session, actor_id)
    key = payload['wound_instance']
    bonus = medicine_bonus(session, actor_id)
    require(not actor['incapacitated'] and key in pool and bonus is not None,
        'This creature cannot currently treat that Saber Wound.')
    condition = pool[key]
    session.tick(6)
    if actor['incapacitated']:
        session.emit('SABER_WOUND_TREATMENT_INTERRUPTED', actor_id,
            text='Medicine treatment stopped before completion because the creature became incapacitated.')
        return True
    record = resolve(session, actor_id, source=TREAT, ability='WIS', skill='Medicine', modifier=bonus,
        dc=condition.data['save_dc'], source_actor_id=condition.source_actor_id)
    count = condition.data['count']
    if record['success']:
        conditions = actor['encounter_snapshot']['conditions']
        if count == 1:
            conditions.pop(key)
        else:
            condition.data.update(count=count - 1, label=wound_label(count - 1))
            conditions[key] = condition.model_dump_json(exclude_none=True)
    else:
        actor.setdefault('source_states', {}).setdefault(TREAT, {})[key] = str(
            session.state.get('scene_id', session.state['journey_id']))
    session.emit('SABER_WOUND_MEDICINE', actor_id, source=TREAT,
        wound_instance=key, before=count, after=count - record['success'], success=record['success'],
        text='Medicine treatment removes one Saber Wound.' if record['success'] else 'The Medicine check failed; the Saber Wound remains.')
    return True
