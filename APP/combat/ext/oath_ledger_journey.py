"""Oath-Ledger outside combat and encounter continuation.

Uses the shared source/consent admission and journey source_states contracts.
No independent fact, consent, inventory, activity or health schema is created.
Combat and journey share the source-owned Obligation model in oath_ledger.
"""
import json
from . import hook
from .oath_ledger import PREFIX, ROWS, Obligation, RECORD, MARK, QI
from ..fact_consent_admission import read, canonical
from ..journey import require
from ..gate2_runtime_models import Position


def owns(session, actor, feature):
    return any(r.get('block') == 'oath_ledger' and r.get('feature_id') == feature
               for r in session.state['actors'][actor]['bundle'].get('typed_passives', ()))


def source_state(session, actor):
    return session.state['actors'][actor].setdefault('source_states', {}).setdefault('oath_ledger',
        {'records': {}, 'completed': [], 'marks': {}})


@hook('fact_admission_schema')
def schema(session, source, subject, kind):
    if source not in ROWS or subject not in session.state['actors']:
        return
    owners = [aid for aid in session.state['actors'] if owns(session, aid, source)]
    if not owners:
        return
    if kind == 'obligation' and subject in owners:
        return {'value_type': 'document', 'maximum_seconds': 30 * 86400, 'authority': 'table_owner',
                'description': 'The seven explicit, meaningful and possible terms of a witnessed obligation.'}
    if kind in ('acceptance', 'dismissal'):
        return {'value_type': 'flag', 'maximum_seconds': 30 * 86400,
                'description': 'This creature explicitly accepts or dismisses the named obligation.'}


@hook('journey_options')
def options(session, actor):
    out = []
    for source in (PREFIX + 'record_the_promise', PREFIX + 'oathkeeper_s_record'):
        if not owns(session, actor, source):
            continue
        out.append({'id': 'oath:' + source.rsplit('.', 1)[-1], 'kind': 'oath_record',
            'payload': {'source': source, 'scope': ''}, 'auto_select': 0,
            'label': ('Record an accepted promise: 1 Qi; at most 8 hours.' if source.endswith('record_the_promise') else
                      'Record a voluntary oath: 1-minute ritual, 2 Qi; all participants within 10 feet; at most three active oaths.')})
    return out or None


@hook('journey_command')
def record_command(session, actor, kind, payload):
    if kind != 'oath_record':
        return
    require(set(payload) == {'source', 'scope'}, 'Choose the source and the declared obligation.')
    source, scope = payload['source'], payload['scope']
    require(source in {PREFIX + 'record_the_promise', PREFIX + 'oathkeeper_s_record'} and owns(session, actor, source),
            'This creature has not acquired that Oath-Ledger feature.')
    declaration = read(session, source, actor, 'obligation', scope, actor)
    require(declaration is not None and declaration['authority'] == 'table_owner',
            'The table owner must record the concrete external terms first.')
    document = Obligation.model_validate(declaration['value'])
    require(document.obligation_id == scope, 'Use the declared obligation’s actual identity.')
    state = source_state(session, actor)
    require(scope not in state['records'] and scope not in state['completed'],
            'This obligation is already recorded or has already granted its fulfillment reward.')
    recorded = source.endswith('oathkeeper_s_record')
    if recorded:
        require(sum(r['recorded_oath'] for r in state['records'].values()) < 3,
                'Oathkeeper’s Record permits three simultaneous Recorded Oaths.')
        require(document.sanction is not None, 'Establish the Recorded Sanction when making this oath.')
    now = int(session.clock())
    origin = Position.model_validate(session.state['actors'][actor]['position'])
    for party in document.parties:
        require(party in session.state['actors'], 'Every participant must be present.')
        creature = session.state['actors'][party]
        point = Position.model_validate(creature['position'])
        require(session.grid.distance_ft(origin, point) <= (10 if recorded else 60),
                'All participants must be in this recording’s printed range.')
        accepted = read(session, source, party, 'acceptance', scope, actor)
        require(accepted is not None and accepted['value'] == 1,
                'Every participant must explicitly accept through their own controller.')
        require(session.grid.line_of_sight(origin, point), 'The keeper must perceive the acceptance.')
    creature = session.state['actors'][actor]
    cost = 2 if recorded else 1
    require(creature['resources'].get(QI, 0) >= cost, 'The keeper cannot pay the recording’s Qi cost.')
    creature['resources'][QI] -= cost
    session.emit('RESOURCE_SPENT', actor, source=source, resource=QI, amount=cost)
    if recorded:
        session.tick(60)
    expires = (-1 if recorded and document.duration_seconds == 0 else int(session.clock()) +
               (document.duration_seconds if recorded else min(28800, document.duration_seconds or 28800)))
    state['records'][scope] = {'document': canonical(document.model_dump(mode='json')), 'source': source,
        'expires_at': expires, 'recorded_oath': int(recorded), 'declaration': declaration['receipt_id'], 'seen': [],
        'positions': {aid: canonical(session.state['actors'][aid]['position']) for aid in document.parties}}
    session.emit('OATH_RECORDED', actor, source=source, obligation=scope, duration_seconds=expires-int(session.clock()),
                 ritual_seconds=60 if recorded else 0, declaration_receipt=declaration['receipt_id'])
    return True


@hook('journey_elapsed')
def elapsed(session, actor, previous_seconds, seconds, moving_ids):
    data = session.state['actors'][actor].get('source_states', {}).get('oath_ledger')
    if data is None:
        return
    for key, record in list(data['records'].items()):
        if 0 <= record['expires_at'] <= session.clock():
            del data['records'][key]
            for target, marks in data['marks'].items():
                data['marks'][target] = [m for m in marks if m['obligation'] != key]
            session.emit('OATH_ENDED', actor, source=record['source'], obligation=key, reason='The stated duration ended.')


@hook('journey_command')
def dismiss(session, actor, kind, payload):
    if kind != 'oath_dismiss':
        return
    require(set(payload) == {'scope'}, 'Name the recorded oath to dismiss.')
    scope = payload['scope']
    state = source_state(session, actor)
    require(scope in state['records'], 'That obligation is not recorded by this keeper.')
    record = state['records'][scope]
    doc = json.loads(record['document'])
    for party in doc['parties']:
        participant = session.state['actors'][party]
        snapshot = participant.get('encounter_snapshot') or {}
        if snapshot.get('life_state') == 'DEAD':
            continue
        accepted = read(session, record['source'], party, 'dismissal', scope, actor)
        require(accepted is not None and accepted['value'] == 1, 'All surviving participants must explicitly dismiss this oath.')
    del state['records'][scope]
    for target, marks in state['marks'].items():
        state['marks'][target] = [m for m in marks if m['obligation'] != scope]
    session.emit('OATH_ENDED', actor, source=record['source'], obligation=scope, reason='All surviving participants dismissed it.')
    return True


@hook('journey_scene_end')
def scene_end(session, previous, current):
    for actor in session.state['actors'].values():
        state = actor.get('source_states', {}).get('oath_ledger')
        if state is not None:
            state['marks'] = {}


@hook('journey_combat_bundle')
def combat_bundle(bundle, session, actor):
    data = session.state['actors'][actor].get('source_states', {}).get('oath_ledger')
    if data is None:
        return bundle
    from copy import deepcopy
    out = deepcopy(bundle)
    out['oath_ledger_continuation'] = {'records': canonical(data['records']), 'seconds': int(session.clock())}
    return out


@hook('match_initialize')
def restore_records(engine):
    for bundle in engine.typed_bundle_documents:
        data = bundle.get('oath_ledger_continuation')
        if data is None:
            continue
        owner = engine.state.actors.get(bundle['actor_id'])
        if owner is None:
            continue
        for key, record in json.loads(data['records']).items():
            seconds = -1 if record['expires_at'] < 0 else record['expires_at'] - data['seconds']
            if seconds == 0 or seconds < 0 and record['expires_at'] >= 0:
                continue
            doc = json.loads(record['document'])
            doc.update({'created_round': engine.state.round_number,
                'deadline_round': -1 if seconds < 0 else engine.state.round_number + (seconds + 5)//6, 'origin': record['declaration'],
                'seen': record['seen'], 'resolved': 0, 'recorded_oath': record['recorded_oath']})
            engine._apply_condition(owner, RECORD, record['source'], owner.entity_id, expires_on='UNTIL_REMOVED',
                data={'document': canonical(doc), 'label': 'Recorded obligation: ' + doc['term']})


@hook('journey_snapshot_actor')
def snapshot_actor(creature, session, actor, engine):
    """Source state uses its own elapsed clock; do not duplicate it in health."""
    if not any(c.condition_id in {RECORD, MARK} for c in creature.conditions.values()):
        return creature
    out = creature.model_copy(deep=True)
    out.conditions = {key: c for key, c in out.conditions.items() if c.condition_id not in {RECORD, MARK}}
    return out


@hook('journey_encounter_settled')
def encounter_settled(session, actor, engine, creature):
    from .oath_ledger import ledger
    data = session.state['actors'][actor].get('source_states', {}).get('oath_ledger')
    current = ledger(engine, creature)
    if data is None and not current:
        return
    data = source_state(session, actor)
    data['records'] = {}
    for condition, doc in current:
        remaining = -1 if doc['deadline_round'] < 0 else (doc['deadline_round'] - engine.state.round_number) * 6
        if remaining == 0 or remaining < 0 and doc['deadline_round'] >= 0:
            continue
        data['records'][doc['obligation_id']] = {'document': canonical(doc), 'source': condition.source_definition_id,
            'expires_at': -1 if remaining < 0 else int(session.clock()) + remaining, 'recorded_oath': int(doc.get('recorded_oath', 0)),
            'declaration': doc['origin'], 'seen': doc['seen'],
            'positions': {aid: canonical(session.state['actors'][aid]['position']) for aid in doc['parties']}}
    data['marks'] = {}
