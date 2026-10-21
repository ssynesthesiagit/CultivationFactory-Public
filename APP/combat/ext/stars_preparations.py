"""Native basic Star Anchor preparation and its exact scene/combat lifetime.

Core Stars Rules grant a ten-minute, 24-hour, PB-limited preparation. These
anchors add a source profile to an actual object, carried item, the preparer's
tattooed compass or a particular location; they never invent HP, teleportation,
perception relays or the separate paid Star Anchor talent's attunements.
"""
import copy
import json
from fractions import Fraction

from . import hook

SOURCE = 'tianxia.sphere.stars'
KEY = SOURCE + ':basic_anchors'
PREPARE = SOURCE + ':prepare_basic_anchor'
END = SOURCE + ':end_basic_anchor'
CONDITION = 'condition:typed.stars.prepared_anchor'
MAP = 'tianxia.talent.stars.star_map'
MAP_KEY = SOURCE + ':prepared_maps'
MAP_PREPARE = SOURCE + ':prepare_star_map'
MAP_BLOCK = 'stars_map_preparation'
MAP_CANVASES = frozenset(('tianxia.mortal.gear.map', 'tianxia.mortal.gear.paper',
    'tianxia.mortal.gear.parchment'))
MAP_CATEGORIES = frozenset(('major_road', 'settlement', 'mountain_ridge', 'river',
    'known_star_anchor', 'known_portal', 'known_danger', 'celestial_disturbance_direction',
    'sunrise_direction', 'sunset_direction', 'visible_constellation_direction'))


@hook('compile_passives')
def map_grant(passives, info):
    """The compiler's admitted ownership is available at this public phase."""
    if MAP not in info.get('owned_ids', ()) or any(row.get('block') == MAP_BLOCK for row in passives):
        return passives
    return [*passives, {'block': MAP_BLOCK, 'feature_id': MAP}]


@hook('compile_bundle')
def map_acquisition(bundle, info):
    # compile_bundle supplies the sheet, not owned_ids. The earlier immutable
    # compile_passives marker is the admitted ownership receipt for this phase.
    row = map_row(bundle)
    if row is None or row.get('pool'):
        return bundle
    from ..factory_compiler import primary_resource
    pool = primary_resource(info['owner_sheet'])[0]
    return {**bundle, 'typed_passives': [{**old, 'pool': pool} if old is row else old
        for old in bundle.get('typed_passives', ())]}


def map_row(bundle):
    return next((row for row in bundle.get('typed_passives', ())
        if row.get('block') == MAP_BLOCK and row.get('feature_id') == MAP), None)


@hook('carried_item_interactions')
def map_holding(engine, actor):
    """Reuse the native general holding producer; no second item/hand schema."""
    return True if any(row.get('block') == MAP_BLOCK and row.get('feature_id') == MAP
        for row in engine.typed_passive_rows.get(actor.entity_id, ())) else None


@hook('carried_item_interactions_tracking')
def map_holding_catalog(engine):
    return True if any(map_row(bundle) is not None for bundle in getattr(engine, 'typed_bundle_documents', ())) else None


def canvases(session, actor_id):
    from ..journey_inventory import possessions
    return [item for item in possessions(session, actor_id) if item.get('item_id') in MAP_CANVASES]


@hook('fact_admission_schema')
def chart_schema(session, source, subject, kind):
    if (source != MAP or kind not in ('charted_area', 'map_reliability') or getattr(session, 'is_combat_fact_context', False)
            or subject not in session.state['actors'] or map_row(session.state['actors'][subject]['bundle']) is None):
        return None
    if kind == 'map_reliability':
        return {'value_type': 'document', 'authority': 'table_owner', 'validate_value': True,
            'maximum_seconds': 86400,
            'description': 'Star Map: identify the actual carried reference map, record whether it is '
                'a reliable source for this area, and explain the provenance ruling. This does not '
                'prepare a Star Map, spend CP or reveal any hidden features.'}
    return {'value_type': 'document', 'authority': 'subject', 'validate_value': True,
        'maximum_seconds': 86400,
        'description': 'Star Map: identify the actual map, paper or parchment, the area you currently '
            'observe, clearly remember or study through a reliable map, and only its features you know. '
            'This private declaration grants no hidden knowledge, preparation, resource or Alignment.'}


@hook('fact_admission_value')
def chart_value(session, payload):
    if payload.get('source') != MAP or payload.get('kind') not in ('charted_area', 'map_reliability'):
        return None
    if getattr(session, 'is_combat_fact_context', False):
        return False
    data, aid = payload.get('value'), payload.get('subject')
    if payload['kind'] == 'map_reliability':
        return (aid in session.state['actors'] and map_row(session.state['actors'][aid]['bundle']) is not None
            and isinstance(data, dict) and set(data) == {'reference_identity', 'reliable', 'basis'}
            and type(data.get('reliable')) is int and data['reliable'] in (0, 1)
            and type(data.get('basis')) is str and 1 <= len(data['basis'].strip()) <= 1000
            and payload.get('scope') == data.get('reference_identity')
            and any(item['object'] == data.get('reference_identity') and item.get('item_id') == 'tianxia.mortal.gear.map'
                for item in canvases(session, aid)))
    if (aid not in session.state['actors'] or map_row(session.state['actors'][aid]['bundle']) is None
            or not isinstance(data, dict)
            or set(data) != {'item_identity', 'area_name', 'basis', 'basis_detail', 'known_features', 'reference_identity'}
            or payload.get('scope') != data.get('item_identity')
            or data.get('basis') not in ('current_observation', 'clear_memory', 'reliable_map')
            or not all(type(data.get(k)) is str and 1 <= len(data[k].strip()) <= 1000
                for k in ('area_name', 'basis_detail'))
            or not any(item['object'] == data.get('item_identity') for item in canvases(session, aid))):
        return False
    if data['basis'] == 'reliable_map':
        from ..fact_consent_admission import read
        reference = data.get('reference_identity')
        if type(reference) is not str:
            return False
        ruling = read(session, MAP, aid, 'map_reliability', reference, aid)
        if (ruling is None or ruling.get('authority') != 'table_owner' or ruling['value']['reliable'] != 1
                or not any(item['object'] == reference for item in canvases(session, aid))):
            return False
    elif data.get('reference_identity') != '':
        return False
    features = data['known_features']
    return (isinstance(features, list) and len(features) <= 100
        and all(isinstance(row, dict) and set(row) == {'category', 'description'}
            and type(row.get('category')) is str and row['category'] in MAP_CATEGORIES
            and type(row.get('description')) is str and 1 <= len(row['description'].strip()) <= 1000
            for row in features))


def map_options(session, actor_id):
    from ..fact_consent_admission import read
    actor = session.state['actors'][actor_id]
    row = map_row(actor['bundle'])
    if row is None or actor['resources'].get(row['pool'], 0) < 1:
        return []
    result = []
    for item in canvases(session, actor_id):
        record = read(session, MAP, actor_id, 'charted_area', item['object'], actor_id)
        if record is not None:
            result.append({'id': MAP_PREPARE + ':' + item['object'], 'kind': 'activate', 'auto_select': 0,
                'payload': {'feature': MAP_PREPARE, 'item_identity': item['object'], 'knowledge_receipt': record['receipt_id']},
                'label': 'Prepare Star Map of ' + record['value']['area_name'] + ' on ' + item['name'] +
                    '. Takes 10 minutes and 1 Cultivation Point from your Path pool; lasts 24 hours. '
                    'Holding it grants Star Alignment. Records only your declared known features; reveals no secrets.'})
    return result


def owns(bundle):
    return any(row.get('block') == 'stars' and row.get('kind') == 'starbolt'
        for row in bundle.get('typed_passives', ()))


def ledger(actor):
    return actor.get('source_states', {}).get(KEY, {})


def targets(session, actor_id):
    """Actual local preparation surfaces, without granting or duplicating items."""
    from ..journey_inventory import JourneyInventoryContext, possessions
    context = JourneyInventoryContext(session)
    actor = context.state.actors[actor_id]
    values = [{'kind': 'location', 'identity': session.state['battlefield']['stable_id'],
        'position': dict(session.state['actors'][actor_id]['position']), 'label': 'this location'},
        {'kind': 'body', 'identity': actor_id, 'label': 'your tattooed compass'}]
    values.extend({'kind': 'item', 'identity': item['object'], 'label': item.get('name') or 'your carried item'}
        for item in possessions(session, actor_id))
    from ..object_geometry import target_cells
    from ..object_rules import label, solid_surface
    for obj in context.state.objects.values():
        if (obj.unattended and not obj.destroyed and obj.current_hp != 0 and solid_surface(obj) is True
                and context.grid.distance_between_cell_sets_ft(
                    context._actor_volume(actor), target_cells(context, obj)) <= 5):
            values.append({'kind': 'object', 'identity': obj.object_id, 'label': label(obj),
                'battlefield': session.state['battlefield']['stable_id']})
    return values


@hook('journey_options')
def options(session, actor_id):
    actor = session.state['actors'][actor_id]
    if session.state['phase'] != 'travel' or actor['incapacitated'] or not owns(actor['bundle']):
        return []
    rows = [{'id': END + ':' + key, 'kind': 'activate', 'payload': {'feature': END, 'anchor': key},
        'label': 'End your Star Anchor on ' + value['label'] + '. No time or CP cost.'}
        for key, value in ledger(actor).items()]
    rows.extend(map_options(session, actor_id))
    if len(ledger(actor)) < actor['bundle']['actor_template']['proficiency_bonus']:
        rows.extend({'id': PREPARE + ':' + value['kind'] + ':' + value['identity'], 'kind': 'activate',
            'payload': {'feature': PREPARE, 'surface': value}, 'auto_select': 0,
            'label': 'Prepare your Star Anchor on ' + value['label'] +
                '. Takes 10 minutes, no CP; lasts 24 hours. Within 30 feet it grants Star Alignment. '
                'Maximum your Proficiency Bonus; grants no teleportation or remote senses.'}
            for value in targets(session, actor_id))
    return rows


@hook('journey_command')
def prepare(session, actor_id, kind, payload):
    if kind != 'activate' or payload.get('feature') not in (PREPARE, END, MAP_PREPARE):
        return None
    from ..journey import require
    actor = session.state['actors'][actor_id]
    require(session.state['phase'] == 'travel' and not actor['incapacitated'] and owns(actor['bundle']),
        'Only an active Stars cultivator can prepare or end these Star Anchors outside combat.')
    if payload['feature'] == MAP_PREPARE:
        from ..fact_consent_admission import read
        require(any(row['payload'] == payload for row in map_options(session, actor_id)),
            'Choose your current Star Map canvas and source-bound knowledge declaration.')
        identity = payload['item_identity']
        knowledge = copy.deepcopy(read(session, MAP, actor_id, 'charted_area', identity, actor_id))
        pool = map_row(actor['bundle'])['pool']
        actor['resources'][pool] -= 1
        session.emit('RESOURCE_SPENT', actor_id, source=MAP, resource_id=pool, amount=1,
            current=actor['resources'][pool])
        session.tick(600)
        if actor['incapacitated'] or not any(item['object'] == identity for item in canvases(session, actor_id)):
            session.emit('STAR_MAP_PREPARATION_INTERRUPTED', actor_id,
                text='Star Map preparation was interrupted after payment; no prepared map was created.')
            return True
        actor.setdefault('source_states', {}).setdefault(MAP_KEY, {})[identity] = {
            'kind': 'map', 'identity': identity, 'label': knowledge['value']['area_name'],
            'knowledge_receipt': knowledge['receipt_id'],
            'chart': json.dumps(knowledge['value'], sort_keys=True), 'expires': str(session.clock() + 86400)}
        session.emit('STAR_MAP_PREPARED', actor_id, source=MAP, item_identity=identity,
            knowledge_receipt=knowledge['receipt_id'], duration_seconds=86400, preparation_seconds=600)
        return True
    if payload['feature'] == END:
        require(set(payload) == {'feature', 'anchor'} and type(payload['anchor']) is str
            and payload['anchor'] in ledger(actor), 'Choose one of your actual Star Anchors.')
        record = actor['source_states'][KEY].pop(payload['anchor'])
        session.emit('STAR_ANCHOR_ENDED', actor_id, anchor=payload['anchor'], label=record['label'])
        return True
    require(set(payload) == {'feature', 'surface'} and payload['surface'] in targets(session, actor_id),
        'Choose an actual local surface from your current Star Anchor preparation menu.')
    surface = copy.deepcopy(payload['surface'])
    require(len(ledger(actor)) < actor['bundle']['actor_template']['proficiency_bonus'],
        'End one of your existing Star Anchors before preparing another beyond your Proficiency Bonus.')
    session.tick(600)
    if actor['incapacitated'] or surface not in targets(session, actor_id):
        session.emit('STAR_ANCHOR_PREPARATION_INTERRUPTED', actor_id,
            text='The ten-minute Star Anchor preparation was interrupted; no anchor was created.')
        return True
    anchors = actor.setdefault('source_states', {}).setdefault(KEY, {})
    identity = session.state['journey_id'] + ':' + str(len(session.state['events']))
    anchors[identity] = {**surface, 'expires': str(session.clock() + 86400)}
    session.emit('STAR_ANCHOR_PREPARED', actor_id, anchor=identity, surface=surface,
        duration_seconds=86400, preparation_seconds=600, cost=0)
    return True


@hook('journey_elapsed')
def elapsed(session, actor_id, previous, seconds, moving):
    actor = session.state['actors'][actor_id]
    for source_key in (KEY, MAP_KEY):
        records = actor.get('source_states', {}).get(source_key, {})
        for key, record in list(records.items()):
            if Fraction(record['expires']) <= session.clock():
                del records[key]
                session.emit('STAR_MAP_EXPIRED' if source_key == MAP_KEY else 'STAR_ANCHOR_EXPIRED', actor_id, anchor=key)


@hook('journey_actor_continued')
def continued(session, actor_id, previous_clock):
    states = session.state['actors'][actor_id].get('source_states', {})
    claimed = [key for key in (KEY, MAP_KEY) if key in states]
    if not claimed:
        return None
    for key in claimed:
        for record in states[key].values():
            record['expires'] = str(session.clock() + max(Fraction(0), Fraction(record['expires']) - previous_clock))
    elapsed(session, actor_id, session.clock(), 0, ())
    return claimed


@hook('journey_combat_setup')
def setup(session, actor_id):
    actor = session.state['actors'][actor_id]
    records = {**ledger(actor), **actor.get('source_states', {}).get(MAP_KEY, {})}
    if not owns(actor['bundle']) or not records:
        return None
    return {'stars_basic_anchors': {key: {**record,
        'remaining_seconds': str(Fraction(record['expires']) - session.clock())}
        for key, record in records.items() if Fraction(record['expires']) > session.clock()}}


@hook('match_initialize')
def import_anchors(engine):
    from .effect_durations import round_token
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        records = (bundle.get('journey_setup') or {}).get('stars_basic_anchors') or {}
        if actor is None or not records:
            continue
        if not owns(bundle):
            raise ValueError('Only the actual acquired Stars owner can continue a prepared Star Anchor.')
        for key, record in records.items():
            if any(c.condition_id == CONDITION and c.data.get('anchor') == key for c in actor.conditions.values()):
                continue
            remaining = Fraction(record['remaining_seconds'])
            if remaining <= 0:
                continue
            rounds = -(-remaining.numerator // (remaining.denominator * 6))
            engine._apply_condition(actor, CONDITION, PREPARE, actor.entity_id,
                expires_on=round_token(engine, rounds), data={'anchor': key,
                    'record': json.dumps(record, sort_keys=True),
                    'label': ('Prepared Star Map: ' if record['kind'] == 'map' else 'Star Anchor: ') + record['label']})


def positions(engine, actor):
    """Current real Anchor positions; destroyed/unknown/moved-away surfaces do not qualify."""
    from ..gate2_runtime_models import Position
    from ..item_locations import carried_item
    from ..object_geometry import target_cells
    for condition in actor.conditions.values():
        if condition.condition_id != CONDITION or condition.source_actor_id != actor.entity_id:
            continue
        record = json.loads(condition.data['record'])
        kind, identity = record['kind'], record['identity']
        if kind == 'body' and identity in engine.state.actors:
            yield engine._actor_volume(engine.state.actors[identity])
        elif kind == 'item':
            located = carried_item(engine, identity)
            if located is not None:
                yield engine._actor_volume(located[0])
        elif kind == 'object':
            obj = engine.state.objects.get(identity)
            if (record['battlefield'] == engine.battlefield_document['stable_id']
                    and obj is not None and not obj.destroyed and obj.current_hp != 0):
                yield target_cells(engine, obj)
        elif kind == 'location' and identity == engine.battlefield_document['stable_id']:
            yield (Position.model_validate(record['position']),)


def holding_map(engine, actor):
    """An actual talent-prepared map currently occupying this creature's hand."""
    from ..item_locations import carried_item
    for owner in (actor,):
        for condition in owner.conditions.values():
            if condition.condition_id != CONDITION or condition.source_actor_id != owner.entity_id:
                continue
            record = json.loads(condition.data['record'])
            if record['kind'] == 'map':
                located = carried_item(engine, record['identity'])
                if located is not None and located[0] is actor and located[2]:
                    return True
    return False


@hook('presentation_hidden_conditions')
def private_charts(engine, actor):
    """The private chart description is mechanical storage, not public lore."""
    return [c.instance_id for c in actor.conditions.values()
        if c.condition_id == CONDITION and json.loads(c.data['record'])['kind'] == 'map']


@hook('journey_snapshot_actor')
def snapshot(creature, session, actor_id, engine):
    if not any(c.condition_id == CONDITION for c in creature.conditions.values()):
        return creature
    clone = creature.model_copy(deep=True)
    clone.conditions = {key: c for key, c in clone.conditions.items() if c.condition_id != CONDITION}
    return clone


@hook('journey_encounter_settled')
def export_anchors(session, actor_id, engine, creature):
    actor = session.state['actors'][actor_id]
    if not {KEY, MAP_KEY}.intersection(actor.get('source_states', {})):
        return
    records, maps = {}, {}
    for condition in creature.conditions.values():
        if condition.condition_id != CONDITION or condition.source_actor_id != actor_id:
            continue
        record = json.loads(condition.data['record'])
        remaining = Fraction(record.pop('remaining_seconds')) - (engine.state.round_number - 1) * 6
        if remaining > 0:
            record['expires'] = str(session.clock() + remaining)
            (maps if record['kind'] == 'map' else records)[condition.data['anchor']] = record
    actor['source_states'][KEY] = records
    if MAP_KEY in actor['source_states'] or maps:
        actor['source_states'][MAP_KEY] = maps
