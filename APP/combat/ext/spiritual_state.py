"""Source-scoped declarations shared by ancestral, passage and Measure rules.

Journey commands are revision-checked table inputs, never automatic AI actions.
They record genuinely external rulings, not inferred consent, hostility, injury
or death. The receipt is carried into combat as one evented condition; callers
read public helpers and updates use the retained-instance journal contract.
Unknown facts return None. A source's suppression never changes another source.
"""
from copy import deepcopy
import json

from . import hook, effect

KEY = 'spiritual_state'
RECEIPT = 'condition:typed.spiritual_state'
OFFICE_SKILLS = {
    'Archivist': ('History', 'Investigation'), 'Healer': ('Medicine', 'Insight'),
    'Magistrate': ('Insight', 'Persuasion'), 'Warrior': ('Athletics', 'Intimidation'),
    'Wayfarer': ('Perception', 'Survival'), 'Ritualist': ('Religion',),
}
RITUAL_TOOLS = ('calligrapher’s supplies', 'carpenter’s tools', 'herbalism kit',
               'mason’s tools', 'weaver’s tools', 'woodcarver’s tools')
CHANNELER = 'tianxia.tradition.spirit.ancestral_channeler.feature.'
INPUT_SOURCE = 'system:spirit.source_state'
WORLD_INPUT = 'spiritual_world_state'
SUBJECT_INPUT = 'spiritual_subject_state'
LINEAGE_INPUT = 'lineage_duty_act'


@hook('presentation_hidden_conditions')
def private_source_state(engine, actor):
    """The semantic receipt contains owner-private covenant and source values."""
    return [condition.instance_id for condition in actor.conditions.values() if condition.condition_id == RECEIPT]


def input_scope(source, name):
    """Bind one amendable fact, without coupling its readers to other facts."""
    from ..fact_consent_admission import digest
    return KEY + ':' + digest([source, name])


def spirit_level(bundle):
    """The acquired owning-Path level, with the explicit legacy fallback."""
    native = next((row['source_numbers']['cl'] for row in bundle.get('typed_passives', [])
                   if str(row.get('feature_id', '')).startswith(CHANNELER) and row.get('source_numbers')), None)
    return int(bundle.get('spiritual_path_cl', native if native is not None else bundle['cl']))


@hook('choice_reactors')
def spirit_save_targets(engine):
    """Enroll dynamic target-owned saves in the existing AI-turn choice probe."""
    sources = {'tianxia.tradition.spirit.soulstring_dancer.feature.threaded_step',
               'tianxia.tradition.spirit.equal_measure_scripture.feature.threefold_recompense'}
    if any(row.get('feature_id') in sources for rows in getattr(engine, 'typed_passive_rows', {}).values() for row in rows):
        return tuple(engine.state.actors)
    return ()


@hook('compile_bundle')
def prepare(bundle, info):
    # Only explicit records opt in; all unrecorded bundles remain unchanged.
    raw = info['owner_sheet'].get(KEY)
    if raw is None:
        return None
    validate(raw)
    known = [row for row in (info['owner_sheet'].get('path_and_subpath') or {}).get('paths', [])
             if isinstance(row, dict) and row.get('path_id') == 'tianxia.path.spirit_awakening'
             and row.get('subpath_or_tradition_id') == CHANNELER.removesuffix('.feature.')
             and (row.get('subpath_or_tradition_acquisition_provenance') or {}).get('recorded') is True]
    attainment = int(known[0]['attainment']) if len(known) == 1 else spirit_level(bundle)
    if raw.get('covenant') and not known and not any(str(r.get('feature_id', '')).startswith(CHANNELER) for r in bundle['typed_passives']):
        raise ValueError('Only an acquired Ancestral Channeler can record its Lineage Covenant.')
    if raw.get('covenant') and attainment < 3:
        raise ValueError('Ancestor Offices require Spirit Awakening CL3.')
    if raw.get('covenant') and len(raw['covenant']['offices']) > (3 if attainment >= 10 else 2):
        raise ValueError('A third Ancestor Office requires CL10.')
    out = deepcopy(bundle)
    out[KEY] = deepcopy(raw)
    if raw.get('covenant'):
        # A covenant already in the authenticated character document precedes
        # the journey created from this compilation. Runtime declarations get
        # the real current scene instead; actors cannot submit this marker.
        out[KEY]['covenant_scene'] = 'character-record-before-journey'
    return out


def validate(record, *, internal=False):
    if not isinstance(record, dict) or set(record) - ({'covenant', 'facts', 'covenant_scene'} if internal else {'covenant', 'facts'}):
        raise ValueError('Spiritual records contain a covenant and source-scoped facts only.')
    if 'covenant_scene' in record and (not isinstance(record['covenant_scene'], str) or not record['covenant_scene']):
        raise ValueError('A native covenant record needs its actual scene identity.')
    covenant = record.get('covenant')
    if covenant is not None:
        required = {'membership', 'duty', 'taboo', 'ordinary_restitution', 'severe_restitution', 'offices', 'knowledge_domains'}
        if not isinstance(covenant, dict) or set(covenant) - (required | {'ritual_proficiency', 'higher_ranked_duty'}) or not required <= set(covenant):
            raise ValueError('Record lineage membership, Duty, Taboo, both restitutions, Offices and knowledge domains.')
        if any(not isinstance(covenant[k], str) or not covenant[k].strip() for k in required - {'offices', 'knowledge_domains'}):
            raise ValueError('Covenant obligations must contain meaningful text.')
        if 'higher_ranked_duty' in covenant and (not isinstance(covenant['higher_ranked_duty'], str) or not covenant['higher_ranked_duty'].strip()):
            raise ValueError('An optional higher-ranked Duty must name the actual recorded obligation.')
        offices = covenant['offices']
        if not isinstance(offices, list) or not 2 <= len(offices) <= 3 or any(not isinstance(o, str) or o not in OFFICE_SKILLS for o in offices) or len(set(offices)) != len(offices):
            raise ValueError('Choose two Offices at CL3 or three at CL10.')
        domains = covenant['knowledge_domains']
        if not isinstance(domains, list) or len(domains) < 3 or any(not isinstance(v, str) or not v.strip() for v in domains) or len({v.casefold().strip() for v in domains}) < 3:
            raise ValueError('Record at least three actual lineage knowledge domains.')
        if 'Ritualist' in offices:
            proficiency = covenant.get('ritual_proficiency')
            if not isinstance(proficiency, str) or not proficiency.strip():
                raise ValueError('The Ritualist Office requires its chosen ritual tool or funerary instrument.')
            normalized = proficiency.casefold().strip().replace('’', "'")
            tools = {v.casefold().replace('’', "'") for v in RITUAL_TOOLS}
            if normalized not in tools and not (normalized.startswith('instrument:') and normalized.partition(':')[2].strip()):
                raise ValueError('Choose a listed ritual tool, or record a funerary or shrine musical instrument as instrument: followed by its name.')
    if not isinstance(record.get('facts', {}), dict):
        raise ValueError('Spiritual facts must be source-scoped records.')
    for source, facts in record.get('facts', {}).items():
        if not isinstance(source, str) or not source or not isinstance(facts, dict):
            raise ValueError('Every fact needs a source identity.')
        for name, entry in facts.items():
            if str(name).startswith('permits_lethal') or name in ('route_source_cl','route_category'):
                raise ValueError('Movement permissions and source power must come from a printed typed Source Rule, not a fact declaration.')
            allowed = {'value', 'ruling', 'source_cl', 'visibility', 'known_to', 'scene_id'}
            if internal:
                allowed.add('admission_receipt')
            if not isinstance(entry, dict) or not {'value', 'ruling'} <= set(entry) <= allowed:
                raise ValueError('Facts need a value, source authority and an explicit table ruling.')
            if type(entry['value']) not in (str, int) or not isinstance(entry['ruling'], str) or not entry['ruling'].strip():
                raise ValueError('Facts use integers or strings with an explicit source ruling.')
            if 'source_cl' in entry and (type(entry['source_cl']) is not int or entry['source_cl'] < 0):
                raise ValueError('A known Source CL is a nonnegative integer; omit unknown authority instead of inventing it.')
            if 'scene_id' in entry and (not isinstance(entry['scene_id'],str) or not entry['scene_id'].strip()):
                raise ValueError('A recorded scene identity must be a nonempty string.')
            if source == 'spiritual_scene' and name == 'scene_id' and (not isinstance(entry['value'],str) or not entry['value'].strip()):
                raise ValueError('Declare the actual bounded spiritual scene with a stable identity and table ruling.')
            if name in ('anchor_strained', 'taboo_scene', 'taboo_since_session', 'meaningful_hostile', 'willing', 'obviously_lethal', 'anchor_exists', 'physically_immobile'):
                if type(entry['value']) is not int or entry['value'] not in (0, 1):
                    raise ValueError('A known yes/no fact must be recorded as integer 0 or 1.')
            if name == 'host_id' and (not isinstance(entry['value'], str) or not entry['value']):
                raise ValueError('An occupying presence requires the actual host or vessel identity.')
            if name == 'presence_kind' and entry['value'] not in ('possessing_spirit', 'occupying_spirit'):
                raise ValueError('Declare whether this presence is a possessing spirit or an occupying spirit.')
            if entry.get('visibility', 'owner') not in ('owner', 'public'):
                raise ValueError('Choose owner-private or publicly perceptible source information.')
            if not isinstance(entry.get('known_to', []), list) or any(not isinstance(v, str) or not v for v in entry.get('known_to', [])):
                raise ValueError('Known recipients are explicit creature identities.')


def read(actor):
    """Read this actor's source-scoped receipt; absent data stays unknown."""
    held = next((c for c in actor.conditions.values() if c.condition_id == RECEIPT), None)
    record = json.loads(held.data['record']) if held else {}
    from ..fact_consent_admission import CONDITION
    latest = {}
    for condition in sorted(actor.conditions.values(), key=lambda c: c.applied_sequence):
        if condition.condition_id == CONDITION:
            item = json.loads(condition.data['record'])
            latest[(item['source'], item['kind'], item['scope'])] = item['receipt_id']
    active = set(latest.values())
    for facts in record.get('facts', {}).values():
        for key, entry in list(facts.items()):
            if entry.get('admission_receipt') and entry['admission_receipt'] not in active:
                del facts[key]
    return record


def active_offices(actor):
    """Keep recorded lineage identity while a suppressed CL10 Office is dormant."""
    offices = read(actor).get('covenant', {}).get('offices', [])
    held = next((condition for condition in actor.conditions.values() if condition.condition_id == RECEIPT), None)
    level = int(held.data.get('spirit_cl', 20)) if held else 20
    return offices[:3 if level >= 10 else 2] if level >= 3 else []


def scene_id(engine, actor):
    """The native journey scene, or this standalone encounter's scene identity."""
    bundle = next((b for b in engine.typed_bundle_documents if b['actor_id'] == actor.entity_id), {})
    return str(bundle.get('spiritual_scene_id') or declared_scene(bundle.get(KEY,{})) or engine.state.match_id)


def declared_scene(record):
    """A GM-declared spiritual scene boundary, without changing world time."""
    return record.get('facts',{}).get('spiritual_scene',{}).get('scene_id',{}).get('value')


def journey_scene_id(session,aid):
    actor = session.state['actors'][aid]
    record = actor['travel_uses'].get(KEY) or actor['bundle'].get(KEY) or {}
    return session.state.get('scene_id') or declared_scene(record) or session.state['journey_id']


def journey_record(actor):
    """Rejoin the actual committed encounter receipt before accepting new facts."""
    record = deepcopy(actor['travel_uses'].get(KEY) or actor['bundle'].get(KEY) or {})
    conditions = actor.get('encounter_snapshot', {}).get('conditions', {})
    for key, raw in list(conditions.items()):
        condition = json.loads(raw)
        if condition['condition_id'] == RECEIPT:
            record = json.loads(condition['data']['record'])
            del conditions[key]
    actor['travel_uses'][KEY] = record
    return record


def fact(actor, source, name):
    from .lineage_reconciliation import strained
    if source in (CHANNELER, CHANNELER.removesuffix('.feature.')) and name == 'anchor_strained' and strained(actor):
        return 1
    return read(actor).get('facts', {}).get(source, {}).get(name, {}).get('value')


def visible_fact(engine, viewer, subject, source, name):
    """Read another creature's source fact only through its recorded disclosure."""
    entry = read(subject).get('facts', {}).get(source, {}).get(name, {})
    if viewer is subject or viewer.entity_id in entry.get('known_to', []):
        return entry.get('value')
    if entry.get('visibility') == 'public':
        from ..target_knowledge import located
        if located(engine, viewer, subject):
            return entry.get('value')
    return None


def write(engine, actor, record, source):
    """Validate and journal a whole receipt without fresh-application hooks."""
    from .retained_updates import record_instance_update
    validate(record, internal=True)
    held = next((c for c in actor.conditions.values() if c.condition_id == RECEIPT), None)
    data = {'record': json.dumps(record, sort_keys=True), 'label': 'Recorded spiritual relationships and source rulings'}
    bundle = next((row for row in engine.typed_bundle_documents if row['actor_id'] == actor.entity_id), None)
    if bundle:
        data['spirit_cl'] = spirit_level(bundle)
    if held:
        held.data = data
        record_instance_update(engine, actor, 'condition', held.instance_id, held)
    else:
        engine._apply_condition(actor, RECEIPT, source, actor.entity_id, expires_on='UNTIL_REMOVED', data=data)


@hook('journey_command')
def declaration(session, aid, kind, payload):
    if kind == 'record_lineage_act':
        raise ValueError('A meaningful lineage act requires the native table-owner fact input, not actor-supplied world authority.')
    if kind != 'record_spiritual_state':
        return None
    from ..journey import require
    require(isinstance(payload, dict) and set(payload) == {'record'}
            and set(payload['record']) <= {'covenant'},
            'World facts require the native table-owner input; consent requires its own controller declaration.')
    return apply_declaration(session, aid, payload)


def apply_declaration(session, aid, payload):
    """Apply a validated native input; the public controller command only admits covenant choices."""
    from ..journey import require
    require(session.state['phase'] == 'travel', 'Record spiritual facts outside an unresolved combat activation.')
    require(set(payload) == {'record'}, 'Supply one typed spiritual record.')
    validate(payload['record'], internal=True)
    actor = session.state['actors'][aid]
    for source, facts in payload['record'].get('facts', {}).items():
        if 'host_id' in facts:
            require(source == aid, 'A hosting record belongs to the spirit whose presence it describes.')
            require(facts['host_id']['value'] != aid, 'A spirit cannot record itself as its own host or vessel.')
            combined = {**journey_record(actor).get('facts', {}).get(source, {}), **facts}
            require(combined.get('presence_kind', {}).get('value') in ('possessing_spirit', 'occupying_spirit'),
                    'Record the actual possessing or occupying spirit relation; a carried passenger or remote body is not one.')
            objects = session.state['battlefield'].get('objects', [])
            object_ids = {obj.get('object_id') for obj in objects if isinstance(obj, dict)}
            require(facts['host_id']['value'] in session.state['actors'] or facts['host_id']['value'] in object_ids,
                    'An occupying spirit requires its actual scene host or vessel; a remote source body is not a host here.')
    existing = journey_record(actor)
    previous_covenant = existing.get('covenant')
    next_covenant = payload['record'].get('covenant')
    third_office = bool(previous_covenant and next_covenant and spirit_level(actor['bundle']) >= 10
        and len(previous_covenant['offices']) == 2 and len(next_covenant['offices']) == 3
        and next_covenant['offices'][:2] == previous_covenant['offices']
        and {k:v for k,v in previous_covenant.items() if k not in ('offices', 'ritual_proficiency')}
            == {k:v for k,v in next_covenant.items() if k not in ('offices', 'ritual_proficiency')}
        and ('Ritualist' not in previous_covenant['offices']
             or previous_covenant.get('ritual_proficiency') == next_covenant.get('ritual_proficiency')))
    require(not previous_covenant or 'covenant' not in payload['record']
            or previous_covenant == next_covenant or third_office,
            'Recorded covenant obligations and Offices persist; changing them requires a legal retraining or covenant Source Rule.')
    # A covenant belongs to a learned tradition, never an invented ancestor.
    if payload['record'].get('covenant'):
        bundle = actor['bundle']
        owned = set(bundle.get('owned_ids', []))
        rows = bundle.get('typed_passives', [])
        require(any(str(r.get('feature_id', '')).startswith(CHANNELER) for r in rows)
                or any(str(v).startswith(CHANNELER) for v in owned)
                or any(str((a.get('parameters', {}).get('typed') or {}).get('source', '')).startswith(CHANNELER)
                       for a in bundle['action_catalog']), 'Only an acquired Ancestral Channeler can record its Lineage Covenant.')
        if previous_covenant != next_covenant:
            require(spirit_level(bundle) >= 3, 'Ancestor Offices require Spirit Awakening CL3.')
            require(len(next_covenant['offices']) <= (3 if spirit_level(bundle) >= 10 else 2), 'A third Ancestor Office requires CL10.')
    if payload['record'].get('covenant'):
        existing['covenant'] = deepcopy(payload['record']['covenant'])
        if not previous_covenant:
            existing['covenant_scene'] = journey_scene_id(session, aid)
    for source, facts in payload['record'].get('facts', {}).items():
        existing.setdefault('facts', {}).setdefault(source, {}).update(deepcopy(facts))
    identity = journey_scene_id(session, aid)
    for source,facts in payload['record'].get('facts',{}).items():
        if 'taboo_scene' in facts:
            existing['facts'][source]['taboo_scene']['scene_id'] = identity
    actor['travel_uses'][KEY] = existing
    actor['bundle'][KEY] = deepcopy(existing)
    session.emit('SPIRITUAL_STATE_RECORDED', aid, text='The table records source-scoped spiritual facts and obligations.')
    return True


@hook('fact_admission_schema')
def input_schema(session, source, subject, kind):
    """Use the reserve owner's single authority/commitment transport."""
    if source != INPUT_SOURCE or kind not in (WORLD_INPUT, SUBJECT_INPUT, LINEAGE_INPUT):
        return None
    prefixes = ('tianxia.tradition.spirit.ancestral_channeler.',
                'tianxia.tradition.spirit.boundary_walker.',
                'tianxia.tradition.spirit.soulstring_dancer.',
                'tianxia.tradition.spirit.equal_measure_scripture.',
                'tianxia.tradition.spirit.seraphic_molter.')
    sources = []
    for actor in session.state['actors'].values():
        bundle = actor['bundle']
        sources.extend(str(row.get('feature_id', '')) for row in bundle.get('typed_passives', []))
        sources.extend(str((row.get('parameters', {}).get('typed') or {}).get('source', ''))
                       for row in bundle.get('action_catalog', []))
    if not any(source.startswith(prefixes) for source in sources):
        return None
    return {'value_type': 'document', 'maximum_seconds': 86400,
            'authority': 'subject' if kind == SUBJECT_INPUT else 'table_owner',
            'combat': True, 'validate_value': True,
            'description': 'Record source-scoped spiritual circumstances.' if kind == WORLD_INPUT
                           else 'Choose whether you willingly receive this practitioner’s protection.'}


@hook('fact_admission_value')
def validate_input(session, payload):
    if payload.get('source') != INPUT_SOURCE or payload.get('kind') not in (WORLD_INPUT, SUBJECT_INPUT, LINEAGE_INPUT):
        return None
    from types import SimpleNamespace
    from ..journey import require
    state = deepcopy(session.state)
    state['phase'] = 'travel'
    if getattr(session, 'is_combat_fact_context', False):
        state['battlefield'] = {'objects': [{'object_id': key} for key in session.engine.state.objects]}
        for aid, actor in state['actors'].items():
            existing = read(session.engine.state.actors[aid])
            actor['travel_uses'] = {KEY: existing, 'lineage_favor_acts': [
                json.loads(entry['value']) for key, entry in existing.get('facts', {}).get(CHANNELER, {}).items()
                if key.startswith('lineage_act:')]}
    probe = SimpleNamespace(state=state, emit=lambda *args, **kwargs: None)
    if payload['kind'] == LINEAGE_INPUT:
        require(payload['scope'] == input_scope(CHANNELER, 'lineage_act:' + str(payload['value'].get('act_id', ''))),
                'Bind the declaration to this actual lineage act identity.')
        lineage_act(probe, payload['subject'], payload['value'])
        return True
    record = payload['value']
    validate(record)
    require(set(record) <= {'facts'} and bool(record.get('facts')),
            'This input records source facts; covenant choices use their own controller command.')
    require(len(record['facts']) == 1 and len(next(iter(record['facts'].values()))) == 1,
            'Declare one typed source fact with its own authority, readers and expiry.')
    source = next(iter(record['facts']))
    name = next(iter(record['facts'][source]))
    require(payload['scope'] == input_scope(source, name), 'Bind the scope to this exact source and fact, so amendments replace it.')
    subject_input = payload['kind'] == SUBJECT_INPUT
    for source, facts in record['facts'].items():
        require(source != 'spiritual_scene', 'Use the native table-owner end-scene command for a scene boundary.')
        require(bool(facts) and all((name == 'willing') == subject_input for name in facts),
                'Only the subject can supply willingness; world circumstances require the table owner.')
        if subject_input:
            require(source in session.state['actors'], 'Consent names its actual practitioner.')
        for entry in facts.values():
            require(set(entry.get('known_to', [])) <= set(payload['readers']),
                    'Known recipients must be authorized readers of this declaration.')
            require(entry.get('visibility') != 'public' or set(payload['readers']) == set(session.state['actors']),
                    'A public spiritual fact must be declared to every participant.')
    # Reuse the same native reference and ownership validation without mutating
    # the real session during admission's pure validation phase.
    apply_declaration(probe, payload['subject'], {'record': record})
    return True


def admitted_record(record):
    value = deepcopy(record['value'])
    for facts in value['facts'].values():
        for entry in facts.values():
            entry['admission_receipt'] = record['receipt_id']
            entry['known_to'] = list(record['readers'])
    return value


@hook('fact_admitted')
def journey_input(session, record):
    if record['source'] != INPUT_SOURCE:
        return
    if record['kind'] == LINEAGE_INPUT:
        lineage_act(session, record['subject'], record['value'])
    elif record['kind'] in (WORLD_INPUT, SUBJECT_INPUT):
        apply_declaration(session, record['subject'], {'record': admitted_record(record)})


@hook('source_fact_committed')
def combat_input(engine, record):
    if record['source'] != INPUT_SOURCE:
        return
    actor = engine.state.actors[record['subject']]
    existing = read(actor)
    if record['kind'] == LINEAGE_INPUT:
        value = deepcopy(record['value'])
        value['scene_id'] = scene_id(engine, actor)
        existing.setdefault('facts', {}).setdefault(CHANNELER, {})['lineage_act:' + value['act_id']] = {
            'value': json.dumps(value, sort_keys=True), 'ruling': value['ruling']}
        write(engine, actor, existing, INPUT_SOURCE)
        engine._gain_resource(actor, 'resource:named.favor', 1, INPUT_SOURCE)
        return
    if record['kind'] not in (WORLD_INPUT, SUBJECT_INPUT):
        return
    for source, facts in admitted_record(record)['facts'].items():
        existing.setdefault('facts', {}).setdefault(source, {}).update(facts)
    write(engine, actor, existing, INPUT_SOURCE)


def lineage_act(session, aid, payload):
    """Table input for subjective protection, fulfillment or accepted complication.

    This is a specific recorded lineage obligation and its meaningful outcome,
    never a generic approve/done action. Real checks earn Favor from CHECK_ROLLED
    instead. Repeating an unchanged described act cannot produce another award.
    """
    from ..journey import require
    actor = session.state['actors'][aid]
    previous = journey_record(actor)
    covenant = previous.get('covenant')
    require(covenant and session.state['phase'] == 'travel', 'A recorded lineage covenant is required.')
    require(set(payload) == {'act_id', 'kind', 'duty', 'description', 'meaningful', 'ruling'}, 'Record the act identity, kind, obligation and meaningful result.')
    require(payload['kind'] in ('protect', 'fulfill', 'complication') and payload['meaningful'] == 1
            and type(payload['meaningful']) is int, 'Only meaningful lineage protection, fulfillment or an accepted significant complication grants Favor.')
    require(all(isinstance(payload[k], str) and payload[k].strip() for k in ('act_id', 'description', 'ruling'))
            and payload['duty'] == covenant['duty'], 'The act must advance the recorded lineage Duty, with an actual table ruling.')
    acts = actor['travel_uses'].setdefault('lineage_favor_acts', [])
    for key, entry in previous.get('facts', {}).get(CHANNELER, {}).items():
        if key.startswith('lineage_act:'):
            old = json.loads(entry['value'])
            if not any(row['act_id'] == old['act_id'] for row in acts):
                acts.append(old)
    require(not any(a['act_id'] == payload['act_id'] for a in acts),
            'The same unchanged act grants Favor only once; reuse its actual recorded act identity.')
    identity = journey_scene_id(session,aid)
    acts.append({**deepcopy(payload), 'scene_id': identity})
    actor['bundle']['lineage_favor_acts'] = sum(a.get('scene_id') == identity for a in acts)
    if actor['travel_uses'].get('lineage_scene') == identity:
        pool = 'resource:named.favor'
        maximum = next(r['maximum'] for r in actor['bundle']['actor_template']['resources'] if r['resource_id'] == pool)
        actor['resources'][pool] = min(maximum, actor['resources'].get(pool, 0) + 1)
    session.emit('LINEAGE_DUTY_RESOLVED', aid, act_kind=payload['kind'], duty=payload['duty'], act_id=payload['act_id'],
                 text='A meaningful recorded lineage act grants one Ancestral Favor, up to its scene maximum.')
    return True


@hook('journey_encounter_prepare')
def transfer(session, aid):
    actor = session.state['actors'][aid]
    from ..fact_consent_admission import CONDITION
    inputs = [item for item in actor['bundle'].get('fact_consent_transport', [])
              if item['record']['source'] == INPUT_SOURCE and item['remaining'][0] > 0]
    features = [str(r.get('feature_id', '')) for r in actor['bundle'].get('typed_passives', [])]
    prefixes = ('tianxia.tradition.spirit.ancestral_channeler.', 'tianxia.tradition.spirit.equal_measure_scripture.',
                'tianxia.tradition.spirit.soulstring_dancer.', 'tianxia.tradition.spirit.seraphic_molter.')
    scoped = any(f.startswith(prefixes) for f in features)
    prior = actor.get('encounter_snapshot', {}).get('conditions', {})
    for key, raw in list(prior.items()):
        condition = json.loads(raw)
        if condition['condition_id'] == CONDITION and json.loads(condition['data']['record']).get('source') == INPUT_SOURCE:
            del prior[key]  # rebase the original committed receipt's remaining clock below
    has_scene_condition = any(json.loads(raw).get('data', {}).get('source_scene_id') for raw in prior.values())
    if not scoped and KEY not in actor['travel_uses'] and KEY not in actor['bundle'] and not has_scene_condition:
        return
    record = journey_record(actor)
    active_receipts = {item['record']['receipt_id'] for item in inputs}
    for facts in record.get('facts', {}).values():
        for key, entry in list(facts.items()):
            if entry.get('admission_receipt') and entry['admission_receipt'] not in active_receipts:
                del facts[key]
    identity = journey_scene_id(session, aid)
    actor['bundle']['spiritual_scene_id'] = identity
    # End source-owned scene state before the next native match is initialized.
    # The affected creature's clock cannot expire somebody else's Strings.
    for key,raw in list(prior.items()):
        condition = json.loads(raw)
        source_actor = condition.get('source_actor_id')
        recorded = condition.get('data',{}).get('source_scene_id')
        if recorded and source_actor in session.state['actors'] and recorded != journey_scene_id(session,source_actor):
            del prior[key]
    if any(f.startswith(CHANNELER) for f in features):
        previous = actor['travel_uses'].get('lineage_scene')
        actor['bundle']['lineage_scene_new'] = int(previous != identity)
        if previous and previous != identity:
            for entries in record.get('facts', {}).values():
                if 'taboo_scene' in entries and entries['taboo_scene'].get('scene_id') != identity:
                    entries['taboo_scene'].update(value=0, ruling='The previous native scene ended; lasting covenant obligations remain.')
        actor['travel_uses']['lineage_scene'] = identity
        actor['bundle']['lineage_favor_acts'] = sum(a.get('scene_id') == identity for a in actor['travel_uses'].get('lineage_favor_acts', []))
    if any(f.startswith('tianxia.tradition.spirit.equal_measure_scripture.') for f in features):
        if actor['travel_uses'].get('measure_scene') != identity:
            for kind in ('impact', 'motion', 'intent'):
                pool = 'resource:named.measure_' + kind
                if pool in actor['resources']:
                    actor['resources'][pool] = 0
        actor['travel_uses']['measure_scene'] = identity
    actor['travel_uses'][KEY] = record
    actor['bundle'][KEY] = deepcopy(record)


@hook('match_initialize')
@hook('activity_initialize')
def initialize(engine):
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is not None and bundle.get(KEY):
            write(engine, actor, bundle[KEY], 'system:spiritual_state')
        if actor is not None:
            for condition in list(actor.conditions.values()):
                recorded = condition.data.get('source_scene_id')
                source_actor = engine.state.actors.get(condition.source_actor_id)
                if recorded and source_actor is not None and recorded != scene_id(engine, source_actor):
                    engine._remove_condition_instance(actor, condition.instance_id, condition.source_definition_id,
                        payload={'reason': 'SOURCE_SCENE_ENDED'})


@hook('journey_native_activity')
def spiritual_activity(session):
    prefixes = ('tianxia.tradition.spirit.ancestral_channeler.', 'tianxia.tradition.spirit.boundary_walker.',
                'tianxia.tradition.spirit.soulstring_dancer.', 'tianxia.tradition.spirit.equal_measure_scripture.',
                'tianxia.tradition.spirit.seraphic_molter.')
    if any(str(row.get('feature_id', '')).startswith(prefixes)
           for actor in session.state['actors'].values() for row in actor['bundle'].get('typed_passives', [])):
        return True
    return None


@hook('journey_scene_end')
def scene_balances(session, previous_scene, next_scene):
    """The native world-owner boundary ends scene resources immediately.

    This never restores Resonance, clears a lasting Taboo or pays restitution.
    Turn-bound effects retain their own clocks, including across scene changes.
    """
    for aid, actor in session.state['actors'].items():
        features = [str(r.get('feature_id','')) for r in actor['bundle'].get('typed_passives', [])]
        pools = []
        if any(f.startswith(CHANNELER) for f in features):
            pools.append('resource:named.favor')
        if any(f.startswith('tianxia.tradition.spirit.equal_measure_scripture.') for f in features):
            pools.extend('resource:named.measure_'+kind for kind in ('impact','motion','intent'))
        for pool in pools:
            if pool in actor['resources']:
                before = actor['resources'][pool]
                actor['resources'][pool] = 0
                if before:
                    session.emit('SPIRIT_SCENE_RESOURCE_ENDED', aid, resource_id=pool, previous=before,
                                 text='A scene-limited spiritual resource ends; cultivation resources and obligations remain.')


def meaningful_hostile(engine, owner, target):
    """A table's source-specific hostile-participant ruling, never ally=enrollment."""
    declared = fact(owner, target.entity_id, 'meaningful_hostile')
    if declared is not None:
        return declared == 1
    # Procedure Addendum R7, Qualifying or Meaningful Event: a nonallied
    # creature's actual hostile action/forced save or damage qualifies. Use
    # committed action provenance, not an ally flag or a damage-derived tag.
    from ..relations import relation, ENEMY
    if relation(engine, owner, target) != ENEMY:
        return False
    from ..movement_steps import is_denial_event
    for event in engine.events:
        if event.actor_id == target.entity_id and is_denial_event(event) and owner.entity_id in event.target_ids:
            return True  # an actually resolved hostile crossing prohibition
        if event.actor_id != target.entity_id or event.event_type != 'INTENT_ACCEPTED':
            continue
        action = engine.action_catalog.get(event.source_definition_id)
        if action is not None and action.target_kind == 'HOSTILE_ENTITY' and owner.entity_id in event.target_ids:
            return True
    return False


def willing(owner, subject):
    """Consent is the subject's recorded decision about this owner, not its team."""
    return fact(subject, owner.entity_id, 'willing') == 1


def disputed(actor):
    from .lineage_reconciliation import strained
    facts = read(actor).get('facts', {})
    found = [(source, name, entry) for source, entries in facts.items() for name, entry in entries.items()
            if source in (CHANNELER, CHANNELER.removesuffix('.feature.'))
            and name in ('anchor_strained', 'taboo_scene', 'faction_dispute') and entry['value'] not in (0, '')]
    if strained(actor):
        found.append((CHANNELER.removesuffix('.feature.'), 'anchor_strained', {'value': 1,
            'ruling': 'The ancestor’s withdrawal strained the Soul Anchor; its lineage reconciliation remains incomplete.'}))
    return found


def possession_costs(engine, actor):
    bundle = next((row for row in engine.typed_bundle_documents if row['actor_id'] == actor.entity_id), {})
    if 'spiritual_path_cl' in bundle and not active_offices(actor):
        return ()
    extra = 1 if disputed(actor) else 0
    favor = (('favor', 1),) + ((('resonance', extra),) if extra else ())
    return (favor, (('resonance', 2 + extra),))


def choose_possession_payment(engine, actor, intent, source, trigger):
    """Both printed payment alternatives stay available to the owning player."""
    from .d20_rewrite import affordable
    from . import needle
    choices = {('favor' if any(p == 'favor' for p, _ in cost) else 'resonance'): cost
               for cost in possession_costs(engine, actor) if affordable(actor, (cost,)) is not None}
    if len(choices) <= 1:
        return next(iter(choices.values()), None)
    labels = {key: ' + '.join(f'{amount} ' + ('Ancestral Favor' if pool == 'favor' else 'Resonance')
                             for pool, amount in cost) for key, cost in choices.items()}
    picked = needle.ask(engine, intent, needle.checkpoint_id(engine, 'POSSESSION_PAYMENT', actor.entity_id), actor,
        'choice:needle.ancestral.possession_payment', list(choices), labels=labels, preferred=['favor'], allow_decline=True,
        prompt=f'{actor.display_name}: Possession by the Past after {trigger}. Choose how to pay.',
        name='Possession by the Past', feature_id=source, target_id=actor.entity_id)
    return choices[picked[0]] if picked else None


def associated(actor, skill):
    return bool(associated_offices(actor, skill))


def associated_offices(actor, skill):
    """Recorded Offices that actually cover a check, including its ritual choice."""
    covenant = read(actor).get('covenant', {})
    wanted = str(skill or '').casefold()
    return [office for office in active_offices(actor)
            if wanted in [s.casefold() for s in (*OFFICE_SKILLS[office],
                *([covenant['ritual_proficiency']] if office == 'Ritualist' else []))]]


@effect('destroy_spiritual_anatomy')
def destroy_anatomy(ctx, row):
    """Dispatch a source's complete printed anatomy-destruction procedure.

    Source rows supply every save, contest, injury/debt and recovery term. This
    interface invents no consequence or number and never targets personhood.
    """
    if row.get('explicit_destruction') != 1 or not isinstance(row.get('procedure'), list):
        raise ValueError('Spiritual anatomy destruction requires an explicit printed Source Rule procedure.')
    from ..typed_executor import effect_subjects, run_effects
    from . import run_strict
    for subject in effect_subjects(ctx, row, harmful=True):
        instances = [c for c in subject.conditions.values()
                     if c.data.get('spiritual_anatomy') == row.get('anatomy')]
        if not instances:
            continue
        run_effects(ctx, row['procedure'])
        for instance in instances:
            run_strict('spiritual_anatomy_destroyed', ctx, subject, instance, row)
