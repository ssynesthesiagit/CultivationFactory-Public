"""Native table-owner input for an external nonmagical travel penalty.

The operator supplies the actual campaign rule, cause, amount and lifetime;
there is no built-in fatigue number, inferred condition, or player approval
button. Source input commits a real speed penalty through the ordinary journal.
Deep Nourishment consumes the public penalties() query. No declaration means
no condition or movement change for any character.
"""
import json

from . import hook

SOURCE = 'system:world.nonmagical_travel_penalty'
KIND = 'nonmagical_travel_penalty'
EXISTING = 'existing_nonmagical_travel_penalty'
CONDITION = 'condition:typed.world_travel_penalty'
CAUSES = ('hunger', 'thirst', 'forced_march', 'travel_fatigue')


@hook('fact_admission_schema')
def schema(session, source, subject, kind):
    if source != SOURCE or kind not in (KIND, EXISTING) or not getattr(session, 'is_combat_fact_context', False):
        return None
    return {'value_type': 'document', 'authority': 'table_owner', 'combat': True,
            'validate_value': True, 'maximum_seconds': 86400,
            'description': 'Record an actual external nonmagical travel penalty, with its rule and remaining duration.'}


@hook('fact_admission_value')
def validate(session, payload):
    if payload.get('source') != SOURCE or payload.get('kind') not in (KIND, EXISTING):
        return None
    from ..journey import require
    value = payload['value']
    if payload['kind'] == EXISTING:
        require(isinstance(value, dict) and set(value) == {'condition_instance_id', 'cause', 'source_rule', 'ruling'}
                and all(type(value[key]) is str and value[key].strip() for key in value),
                'Name the actual condition, its nonmagical travel cause, source rule and ruling.')
        actor = session.engine.state.actors[payload['subject']]
        condition = actor.conditions.get(value['condition_instance_id'])
        require(condition is not None and 'exhaustion' not in condition.condition_id.lower()
                and value['cause'] in CAUSES and payload['scope'] == condition.instance_id,
                'Only an existing non-Exhaustion travel penalty can be recorded.')
        source = session.engine.action_catalog.get(condition.source_definition_id)
        typed = ((source.parameters or {}).get('typed') or {}) if source is not None else {}
        # A Sphere or a condition's name alone is not a magical-status receipt.
        # Preserve explicit native facts; the table owner supplies genuinely
        # external classifications only where the source has not settled one.
        known_magical = (condition.data.get('magical') == 1 or typed.get('magical') == 1
                         or (condition.data.get('rule') or {}).get('magical') == 1
                         or (typed.get('activation_profile') or {}).get('magical') == 1)
        require(not known_magical, 'An external ruling cannot reclassify a known magical effect as a nonmagical penalty.')
        return True
    require(isinstance(value, dict) and set(value) == {
        'penalty_id', 'cause', 'label', 'source_rule', 'ruling', 'speed_reduction_ft'},
        'Record the exact penalty identity, cause, label, source rule, ruling and speed reduction.')
    require(all(type(value[key]) is str and value[key].strip() for key in (
        'penalty_id', 'label', 'source_rule', 'ruling')), 'An external penalty needs its actual rule and ruling.')
    require(value['cause'] in CAUSES and payload['scope'] == value['penalty_id'],
            'Bind this input to its actual nonmagical hunger, thirst, forced-march or travel-fatigue penalty.')
    amount = value['speed_reduction_ft']
    require(type(amount) is int and amount > 0 and amount % 5 == 0,
            'Supply the actual positive whole-square speed penalty; no amount is assumed.')
    return True


@hook('source_fact_committed')
def committed(engine, record):
    if record['source'] != SOURCE or record['kind'] != KIND:
        return
    from ..fact_consent_admission import CONDITION as ADMISSION
    actor = engine.state.actors[record['subject']]
    value = record['value']
    receipt = next(condition for condition in actor.conditions.values()
        if condition.condition_id == ADMISSION
        and json.loads(condition.data['record'])['receipt_id'] == record['receipt_id'])
    for condition in list(penalties(actor)):
        if condition.data.get('penalty_id') == value['penalty_id']:
            engine._remove_condition_instance(actor, condition.instance_id, SOURCE,
                payload={'reason': 'SOURCE_PENALTY_AMENDED'})
    seconds = record['expires_at'] - record['created_at']
    span = (f'{seconds // 3600} hours' if seconds % 3600 == 0 else
            f'{seconds // 60} minutes' if seconds % 60 == 0 else f'{seconds} seconds')
    engine._apply_condition(actor, CONDITION, SOURCE, actor.entity_id, expires_on=receipt.expires_on,
        data={'penalty_id': value['penalty_id'], 'cause': value['cause'],
              'speed_reduction_ft': value['speed_reduction_ft'],
              'receipt_id': record['receipt_id'], 'nonmagical': 1, 'source_kind': 'nonmagical_world_rule',
              'label': f"{value['label']}: Speed reduced by {value['speed_reduction_ft']} feet for up to "
                       f"{span}"})


def penalties(actor):
    """Actual committed nonmagical penalties, never inferred from names/flags."""
    native = [condition for condition in actor.conditions.values()
            if condition.condition_id == CONDITION and condition.source_definition_id == SOURCE
            and condition.data.get('cause') in CAUSES and condition.data.get('nonmagical') == 1]
    from ..fact_consent_admission import CONDITION as ADMISSION, digest
    latest = {}
    for condition in sorted(actor.conditions.values(), key=lambda item: item.applied_sequence):
        if condition.condition_id != ADMISSION:
            continue
        record = json.loads(condition.data['record'])
        if record['source'] == SOURCE and record['kind'] == EXISTING:
            latest[record['scope']] = record
    for record in latest.values():
        if (record['authority'] == 'table_owner' and record['subject'] == actor.entity_id
                and record['receipt_id'] == digest({key:value for key,value in record.items() if key != 'receipt_id'})):
            condition = actor.conditions.get(record['value']['condition_instance_id'])
            if condition is not None and condition not in native and 'exhaustion' not in condition.condition_id.lower():
                native.append(condition)
    return native


@hook('speed')
def speed(engine, actor):
    from ..speed_contributions import SpeedContribution
    sources = [(SOURCE + ':' + condition.data['penalty_id'], condition.data['label'],
                -int(condition.data['speed_reduction_ft']))
               for condition in penalties(actor) if condition.condition_id == CONDITION]
    return SpeedContribution(sources) if sources else None
