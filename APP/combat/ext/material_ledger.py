"""Finite, sourced holdings shared by Gathering, Alchemy and Thread.

External sources enter only through CombatService.journey_admit (GM authority,
revision and nonempty provenance required). This module owns identity, integer
quantities and transfers, not ability outcomes. No source means no inventory.
Public API: sources, holdings, take, consume, record, owned and numbers.
All transactions run inside JourneyStore's single locked atomic commit.
"""
from copy import deepcopy
import re
from . import hook
from ..journey import require, integer

KINDS = ('raw_material', 'common_reagents', 'currency', 'thread_tool', 'harvest_tool', 'container')
CONTEXTS = ('scene', 'downtime', 'market', 'sect_field', 'wilderness_route', 'strategic_project')


def text(value, label):
    require(isinstance(value, str) and 0 < len(value.strip()) <= 1000, f'Record {label}.')
    return value.strip()


def identity(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}', value),
            'Use a stable source identity (letters, digits, dot, colon, dash or underscore).')
    return value


def owned(session, aid, feature):
    return feature in session.state['actors'][aid]['bundle'].get('material_abilities', {}).get('owned', ())


def numbers(session, aid):
    return session.state['actors'][aid]['bundle'].get('material_abilities', {})


def holdings(session, aid):
    return session.state['actors'][aid].setdefault('material_holdings', {})


def sources(session):
    return session.state.get('material_sources', {})


def record(session, aid, kind, **data):
    session.emit(kind, aid, **deepcopy(data))


def take(session, aid, source_id, amount):
    source = sources(session).get(source_id)
    require(source is not None and aid in source['known_to'] and integer(amount, 1)
            and source['remaining'] >= amount, 'Choose an admitted source with enough available material.')
    require(not source.get('exclusive_to') or source['exclusive_to'] == aid, 'This supply belongs to another creature.')
    source['remaining'] -= amount
    serial = source['quantity'] - source['remaining']
    key = f'{source_id}:{serial}'
    require(key not in holdings(session, aid), 'That portion was already collected.')
    row = {'id': key, 'source_id': source_id, 'name': source['name'], 'kind': source['kind'],
           'unit': source['unit'], 'quantity': amount, 'acquired_at': session.state['seconds'],
           'provenance': source['provenance']}
    holdings(session, aid)[key] = row
    record(session, aid, 'MATERIAL_COLLECTED', holding=key, source_id=source_id, quantity=amount)
    return row


def consume(session, aid, key, amount, *, kind=None):
    row = holdings(session, aid).get(key)
    require(row is not None and integer(amount, 1) and row['quantity'] >= amount
            and (kind is None or row['kind'] == kind), 'Choose enough of your own suitable recorded material.')
    row['quantity'] -= amount
    record(session, aid, 'MATERIAL_CONSUMED', holding=key, source_id=row['source_id'], quantity=amount)
    return row


@hook('journey_persistent_fields')
def persistent():
    return ('material_holdings', 'gathering_learning', 'material_preparation')


@hook('journey_shared_fields')
def shared():
    return ('material_sources',)


@hook('journey_admission')
def admit(session, aid, kind, payload, reason):
    if kind != 'material_source':
        return None
    required = {'id', 'name', 'kind', 'context', 'material', 'unit', 'quantity', 'known_to'}
    require(required <= set(payload) <= required | {'exclusive_to'}, 'Record a complete typed material source.')
    sid = identity(payload['id'])
    require(sid not in sources(session), 'This source identity already exists; it cannot be refilled by readmission.')
    require(payload['kind'] in KINDS and payload['context'] in CONTEXTS, 'Choose a known source kind and context.')
    require(integer(payload['quantity'], 1), 'Source quantities must be positive whole units.')
    known = payload['known_to']
    require(isinstance(known, list) and all(isinstance(a,str) and a in session.state['actors'] for a in known)
            and len(known) == len(set(known)), 'Name the journey creatures who actually know this source.')
    owner = payload.get('exclusive_to', '')
    require(isinstance(owner,str) and (owner == '' or owner in session.state['actors']), 'Choose the actual owner of a restricted supply.')
    row = {**deepcopy(payload), 'id': sid, 'exclusive_to': owner, 'remaining': payload['quantity'],
           'provenance': text(reason, 'the source provenance'), 'admitted_by': 'GM'}
    for field in ('name', 'material', 'unit'):
        row[field] = text(row[field], field)
    if row['kind'] == 'currency':
        require(row['unit'] == 'gp', 'Record currency in whole gold pieces.')
    session.state.setdefault('material_sources', {})[sid] = row
    record(session, aid, 'MATERIAL_SOURCE_ADMITTED', source_id=sid, reason=reason)
    return True


@hook('journey_command')
def collect(session, aid, kind, payload):
    if kind != 'collect_material':
        return None
    require(set(payload) == {'source', 'quantity'} and isinstance(payload['source'],str) and integer(payload['quantity'],1), 'Choose a source and whole quantity.')
    source = sources(session).get(payload['source'])
    require(source is not None and 'harvest' not in source,
            'Harvestable sources require Clean Harvest; collecting cannot bypass the check.')
    require(not session.state['actors'][aid]['incapacitated'], 'An incapacitated creature cannot collect supplies.')
    take(session, aid, payload['source'], payload['quantity'])
    return True


@hook('journey_options')
def options(session, aid):
    if session.state['phase'] != 'travel' or session.state['actors'][aid]['incapacitated']:
        return None
    return [{'id': 'collect:' + sid, 'kind': 'collect_material',
             'payload': {'source': sid, 'quantity': 1},
             'label': f"Collect one {s['unit']} of {s['name']} from its recorded source."}
            for sid, s in sorted(sources(session).items())
            if aid in s['known_to'] and s['remaining'] > 0 and 'harvest' not in s
            and (not s['exclusive_to'] or s['exclusive_to'] == aid)]


@hook('journey_view')
def project(state, viewer_id):
    if 'material_sources' not in state and not any('material_holdings' in a for a in state['actors'].values()):
        return None
    state = deepcopy(state)
    state.pop('replay_base', None)
    state.pop('command_journal', None)
    state.pop('material_sources', None)  # DC, hazards and unrevealed signs are GM facts.
    for aid, actor in state['actors'].items():
        if aid != viewer_id:
            for key in ('material_holdings', 'gathering_learning', 'material_preparation'):
                actor.pop(key, None)
    state['events'] = [e for e in state['events'] if not e['kind'].startswith(('MATERIAL_', 'HARVEST_', 'REAGENT_'))
                       or e['actor_id'] == viewer_id]
    return state


@hook('compile_bundle')
def seal(bundle, info):
    """Seal acquired IDs/numbers for material consumers; never grant features."""
    ids = set(info['owned_ids'])
    if 'THREAD_BASE_SPOOL_AND_STRAND' not in ids:
        return None
    return {**bundle, 'material_abilities': {'owned': sorted(ids),
            **info['numbers'], 'ability_mods': dict(info['mods'])}}

