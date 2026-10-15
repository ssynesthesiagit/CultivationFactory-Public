"""Native resolution of actual table-declared known-DC ability checks.

Source adapters opt in by attaching recorded character statistics. The table
owner supplies the actual obstacle, skill, ability, DC and ruling through the
existing private fact-admission contract. A declaration supplies no result,
ownership, proficiency, permission to act or resource. Every result is rolled
in the native non-action procedure, with normal reactions and cold replay.
"""
from copy import deepcopy
import json

from . import hook

SOURCE = 'system:journey.ability_checks'
KIND = 'known_dc_challenge'
STATISTICS = 'native_check_statistics'
PENDING = 'native_check_request'
COMPLETIONS = 'condition:typed.native_check_completions'
ABILITIES = ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')
SKILLS = {
    'athletics': 'STR', 'acrobatics': 'DEX', 'sleight of hand': 'DEX', 'stealth': 'DEX',
    'arcana': 'INT', 'history': 'INT', 'investigation': 'INT', 'nature': 'INT', 'religion': 'INT',
    'animal handling': 'WIS', 'insight': 'WIS', 'medicine': 'WIS', 'perception': 'WIS', 'survival': 'WIS',
    'deception': 'CHA', 'intimidation': 'CHA', 'performance': 'CHA', 'persuasion': 'CHA'}


def normalized(name):
    return str(name).casefold().replace('’', "'").strip().removeprefix('instrument:').strip()


def attach_statistics(bundle, owner_sheet, *, numbers):
    """Public source opt-in for Hunger and Ancestral Channeler compilation.

    Project only actual modifiers/totals; absent skills or tool statistics stay
    unknown. Tool rows name their recorded ability explicitly. A skill total
    never supplies saving-throw proficiency or an inferred proficiency rank.
    """
    from ..factory_compiler import ability_modifiers
    stats = owner_sheet.get('ability_scores_and_statistics') or {}
    rows = stats.get('skills') or []
    if isinstance(rows, str):
        rows = json.loads(rows)
    skills = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('skill'), str) or type(row.get('bonus')) is not int:
            continue
        key = normalized(row['skill'])
        ability = str(row.get('ability') or SKILLS.get(key) or '').upper()[:3]
        if ability in ABILITIES:
            skills[key] = {'name': row['skill'], 'ability': ability, 'total': row['bonus']}
    out = deepcopy(bundle)
    out[STATISTICS] = {'ability_mods': ability_modifiers(stats), 'skills': skills, 'numbers': dict(numbers)}
    return out


def statistic_bonus(statistics, ability, skill):
    mods = statistics.get('ability_mods') or {}
    if ability not in mods or type(mods[ability]) is not int:
        return None
    if not skill:
        return mods[ability]
    row = statistics.get('skills', {}).get(normalized(skill))
    if row is None or row['ability'] not in mods:
        return None
    # A table-requested variant changes only the underlying ability modifier;
    # the actual recorded proficiency and other fixed skill bonuses remain.
    return row['total'] - mods[row['ability']] + mods[ability]


def completed(actor):
    held = next((c for c in actor.conditions.values() if c.condition_id == COMPLETIONS
        and c.source_definition_id == SOURCE and c.source_actor_id == actor.entity_id), None)
    return held, json.loads(held.data['receipts']) if held else {}


def saved_completions(session, aid):
    snapshot = session.state['actors'][aid].get('encounter_snapshot') or {}
    for raw in snapshot.get('conditions', {}).values():
        row = json.loads(raw)
        if row['condition_id'] == COMPLETIONS and row['source_definition_id'] == SOURCE and row['source_actor_id'] == aid:
            return json.loads(row['data']['receipts'])
    return {}


def challenges(session, aid):
    from ..fact_consent_admission import journey_records
    done = saved_completions(session, aid)
    return [row for row in journey_records(session, aid, source=SOURCE, subject=aid, kind=KIND)
        if row['receipt_id'] not in done]


@hook('fact_admission_schema')
def input_schema(session, source, subject, kind):
    if (source, kind) == (SOURCE, KIND) and STATISTICS in session.state['actors'].get(subject, {}).get('bundle', {}):
        return {'value_type': 'document', 'maximum_seconds': 86400, 'authority': 'table_owner',
            'validate_value': True,
            'description': 'Record an actual known-DC ability check: its name, ability, skill (or empty), DC, unchanged obstacle identity and source ruling. This input supplies no outcome or proficiency.'}


@hook('fact_admission_value')
def validate_input(session, payload):
    if (payload.get('source'), payload.get('kind')) != (SOURCE, KIND):
        return None
    from ..journey import require
    value = payload['value']
    require(isinstance(value, dict) and set(value) == {'name', 'ability', 'skill', 'dc', 'obstacle_id', 'ruling'},
        'Supply the actual ability check, its recorded obstacle and source ruling; never an outcome or invented statistic.')
    require(all(isinstance(value[k], str) and value[k].strip() for k in ('name', 'obstacle_id', 'ruling'))
        and value['ability'] in ABILITIES and isinstance(value['skill'], str)
        and type(value['dc']) is int and value['dc'] > 0 and bool(payload['scope']),
        'A check needs a plain name, ability, skill (or empty), positive integer DC and durable obstacle identity.')
    stats = session.state['actors'][payload['subject']]['bundle'].get(STATISTICS) or {}
    require(statistic_bonus(stats, value['ability'], value['skill']) is not None,
        'The character’s actual ability and skill or tool total must be recorded before this check can resolve.')
    return True


@hook('journey_options')
def options(session, aid):
    if (session.state['phase'] != 'travel' or session.state.get('native_activity_pending')
            or session.state.get('native_activity') or session.state['actors'][aid]['incapacitated']):
        return None
    return [{'id': 'ability_check:' + row['receipt_id'], 'kind': 'ability_check',
        'payload': {'receipt_id': row['receipt_id']},
        'label': row['value']['name'] + ': resolve the table’s ' + (row['value']['skill'] or row['value']['ability']) + ' ability check.'}
        for row in challenges(session, aid)]


@hook('journey_command')
def command(session, aid, kind, payload):
    if kind != 'ability_check':
        return None
    from ..journey import require
    require(set(payload) == {'receipt_id'}, 'Choose one actual table-requested check.')
    receipt = next((row for row in challenges(session, aid) if row['receipt_id'] == payload['receipt_id']), None)
    require(receipt is not None, 'This check is unknown, expired, resolved or belongs to another creature.')
    session.state['actors'][aid]['travel_uses'][PENDING] = receipt
    from ..journey_activity import procedure
    procedure(session, aid, {'source': SOURCE, 'procedure': receipt['receipt_id']})
    return True


@hook('journey_combat_setup')
def setup(session, aid):
    request = session.state['actors'][aid]['travel_uses'].get(PENDING)
    if request:
        return {PENDING: deepcopy(request)}


@hook('journey_native_procedure')
def resolve(engine, actor, source, name, intent):
    if source != SOURCE:
        return None
    from ..journey import require
    from .needle import incapacitated
    from .ability_source import native_check_detail
    from .retained_updates import record_instance_update
    bundle = next(b for b in engine.typed_bundle_documents if b['actor_id'] == actor.entity_id)
    receipt = bundle.get('journey_setup', {}).get(PENDING)
    held, done = completed(actor)
    require(actor.active and not incapacitated(actor) and receipt is not None
        and receipt['receipt_id'] == name and name not in done and receipt['subject'] == actor.entity_id,
        'Only the actual subject may resolve this uncompleted check while able to act.')
    request, statistics = receipt['value'], bundle.get(STATISTICS) or {}
    bonus = statistic_bonus(statistics, request['ability'], request['skill'])
    require(bonus is not None, 'The requested check’s actual statistic is unknown.')
    result = native_check_detail(engine, actor, {**statistics['numbers'], 'ability_mods': statistics['ability_mods']},
        request['dc'], SOURCE, modifier=bonus, ability=request['ability'], skill=request['skill'] or None,
        check_name=request['name'], event_data={'obstacle_id': request['obstacle_id']})
    done[name] = result.roll.roll_id
    data = {'receipts': json.dumps(done, sort_keys=True), 'label': 'Resolved table-requested ability checks'}
    if held:
        held.data = data
        record_instance_update(engine, actor, 'condition', held.instance_id, held)
    else:
        engine._apply_condition(actor, COMPLETIONS, SOURCE, actor.entity_id, expires_on='UNTIL_REMOVED', data=data)
    return True


@hook('journey_encounter_settled')
def settled(session, aid, engine, actor):
    request = session.state['actors'][aid]['travel_uses'].get(PENDING)
    if not request:
        return
    _, done = completed(actor)
    roll_id = done.get(request['receipt_id'])
    if roll_id is None:
        return
    event = next(event for event in reversed(engine.events) if event.event_type == 'CHECK_ROLLED'
        and event.actor_id == aid and event.source_definition_id == SOURCE and event.payload['actor']['roll_id'] == roll_id)
    session.state['actors'][aid]['travel_uses'].pop(PENDING)
    session.emit('ABILITY_CHECK_RESOLVED', aid, receipt_id=request['receipt_id'], roll_id=roll_id,
        success=int(bool(event.payload['success'])), total=event.payload['effective_total'],
        text=request['value']['name'] + ': the ability check ' + ('succeeds.' if event.payload['success'] else 'fails.'))


@hook('presentation_hidden_conditions')
def private_completion_receipts(engine, actor):
    return [c.instance_id for c in actor.conditions.values() if c.condition_id == COMPLETIONS]
