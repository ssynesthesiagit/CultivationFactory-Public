"""Native shared short-rest roster, consent and elapsed-time producer.

RecoveryFacts supplies the source-scoped scene ruling. Each participant joins
with their own journey command. Completion requires one uninterrupted hour;
movement, combat, incapacitation or withdrawal breaks membership. Consumers
receive only that actual completed roster and must check their own ownership.
"""
from . import hook, query, run_strict
from ..journey import require
from ..recovery_sources import RecoveryFacts, genuine

SOURCE = 'system:recovery.shared_rest'


@hook('fact_admission_schema')
def scene_schema(session, source, subject, kind):
    if source == SOURCE and kind == 'recovery_scene' and subject in session.state['actors']:
        return {'value_type': 'document', 'maximum_seconds': 86400, 'authority': 'table_owner',
                'description': 'The actual shared recovery scene, its source and exclusions; joining remains creature-owned.'}


@hook('journey_options')
def menu(session, aid):
    rest = session.state.get('shared_rest')
    if rest is None or rest['finished']:
        return start_options(session, aid)
    if aid not in rest['roster']:
        if aid not in rest['facts']['recipient_ids']:
            return None
        return [{'id': 'rest:join', 'kind': 'join_shared_rest', 'payload': {},
            'label': 'Join the shared recovery rest willingly; rest for one hour.'}]
    result = [{'id': 'rest:leave', 'kind': 'leave_shared_rest', 'payload': {},
        'label': 'Leave the shared rest; receive no completion benefit.'}]
    if aid == rest['leader']:
        result.append({'id': 'rest:complete', 'kind': 'finish_shared_rest', 'payload': {},
            'label': 'Finish the shared short rest after every participant has rested for one hour.'})
    return result


def start_options(session, aid):
    """Offer each legal way the recorded shared-rest scene can start, for humans and automatic seats alike.

    Only the creature who recorded the scene (and is not incapacitated) may start it. Each offered start names
    one beneficiary group from the shared_rest_beneficiaries seam; the default is the empty group. Groups are
    applied only to creatures who actually finish the rest.
    """
    actor = session.state['actors'][aid]
    if actor['incapacitated']:
        return None
    from ..fact_consent_admission import read
    record = read(session, SOURCE, aid, 'recovery_scene', session.state['journey_id'], aid)
    if record is None:
        return None
    facts = RecoveryFacts.model_validate(record['value'])
    if facts.actor_id != aid or facts.scene != 'shared_rest' or not set(facts.recipient_ids) <= session.state['actors'].keys():
        return None
    groups = sorted({tuple(group) for reply in query('shared_rest_beneficiaries', session, aid, tuple(facts.recipient_ids))
                     for group in (reply or [])}) or [()]
    return [{'id': 'rest:start:' + ','.join(group), 'kind': 'start_shared_rest',
        'payload': {'scene_receipt': record['receipt_id'], 'selected_ids': list(group)},
        'label': 'Start a one-hour shared short rest in the recorded scene' + (
            ', choosing ' + ', '.join(session.state['actors'][i]['name'] for i in group) + ' as beneficiaries.'
            if group else ', with no beneficiaries chosen.')}
        for group in groups]


@hook('journey_command')
def command(session, aid, kind, payload):
    if kind not in ('start_shared_rest', 'join_shared_rest', 'leave_shared_rest', 'finish_shared_rest'):
        return None
    actor = session.state['actors'][aid]
    if kind == 'start_shared_rest':
        require(not actor['incapacitated'], 'An incapacitated creature cannot conduct a shared recovery rest.')
        require(not session.state.get('shared_rest') or session.state['shared_rest']['finished'], 'Finish or leave the current rest first.')
        from ..fact_consent_admission import read
        require(set(payload) <= {'scene_receipt', 'selected_ids'} and 'scene_receipt' in payload,
                'Choose a current table-owner recovery scene before starting this rest.')
        record = read(session, SOURCE, aid, 'recovery_scene', session.state['journey_id'], aid)
        require(record is not None and record['receipt_id'] == payload['scene_receipt'],
                'The table owner must record the real recovery scene first.')
        facts = RecoveryFacts.model_validate(record['value'])
        require(facts.actor_id == aid and facts.scene == 'shared_rest', 'Record the actual shared recovery scene.')
        require(set(facts.recipient_ids) <= session.state['actors'].keys(), 'Choose creatures present in this journey.')
        session.state['shared_rest'] = {'leader': aid, 'facts': facts.model_dump(mode='json'),
            'scene_receipt': record['receipt_id'],
            'roster': {aid: session.state['seconds']}, 'positions': {aid: dict(actor['position'])},
            'incapacitated': {aid: int(actor['incapacitated'])},
            'selected_ids': list(payload.get('selected_ids', ())), 'finished': 0}
        session.emit('SHARED_REST_STARTED', aid, source_ids=list(facts.source_ids))
        return True
    require(not payload, 'Joining, leaving and finishing rest take no extra parameters.')
    rest = session.state.get('shared_rest')
    require(rest is not None and not rest['finished'], 'There is no active shared rest.')
    if kind == 'join_shared_rest':
        require(aid in rest['facts']['recipient_ids'], 'This creature is outside the declared rest group.')
        require(aid not in rest['roster'], 'This creature already joined the rest.')
        rest['roster'][aid] = session.state['seconds']
        rest['positions'][aid] = dict(actor['position'])
        rest['incapacitated'][aid] = int(actor['incapacitated'])
        session.emit('SHARED_REST_JOINED', aid)
    elif kind == 'leave_shared_rest':
        rest['roster'].pop(aid, None)
        if aid == rest['leader']:
            rest['finished'] = 1
        session.emit('SHARED_REST_LEFT', aid)
    else:
        require(aid == rest['leader'], 'Only the rest leader can finish this rest.')
        require(rest['roster'] and aid in rest['roster'], 'The leader must have rested with the group.')
        remaining = max(0, max(t + 3600 for t in rest['roster'].values()) - session.state['seconds'])
        session.tick(remaining)
        require(aid in rest['roster'], 'The shared rest was interrupted.')
        facts = RecoveryFacts.model_validate(rest['facts'])
        from ..fact_consent_admission import read
        current = read(session, SOURCE, aid, 'recovery_scene', session.state['journey_id'], aid)
        require(current is not None and current['receipt_id'] == rest['scene_receipt'],
                'The recovery scene expired or changed; record and conduct a current rest.')
        roster = tuple(i for i, start in rest['roster'].items() if session.state['seconds'] - start >= 3600)
        rest['finished'] = 1
        session.emit('SHARED_SHORT_REST_COMPLETED', aid, roster=list(roster), seconds=3600)
        run_strict('shared_short_rest_recovery', session, aid, roster)
        # A chosen beneficiary who did not finish the rest with the group receives nothing.
        run_strict('shared_short_rest_completed', session, aid, roster, facts,
                   tuple(i for i in rest['selected_ids'] if i in roster))
    return True


@hook('journey_state_changed')
def interrupt(session, aid):
    rest = session.state.get('shared_rest')
    if rest is None or rest['finished'] or aid not in rest['roster']:
        return
    actor = session.state['actors'][aid]
    if (session.state['phase'] != 'travel' or actor['incapacitated'] and not rest['incapacitated'].get(aid)
            or actor['position'] != rest['positions'][aid]):
        rest['roster'].pop(aid)
        if aid == rest['leader']:
            rest['finished'] = 1
        session.emit('SHARED_REST_INTERRUPTED', aid)
