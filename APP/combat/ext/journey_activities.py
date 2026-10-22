"""Default-inert elapsed work protocol for source-owned outside-combat procedures.

activity_spec(session, aid, source, parameters) returns exactly one validated
{seconds, label} or None. activity_started/finished receive the immutable row.
Only activity_work advances its work clock; wait, travel, combat and incapacity
interrupt it. Consumers retain rules, admission, payment and completion policy.
"""
from copy import deepcopy
from . import hook, query, run_strict
from ..journey import require, integer

KEY = 'journey:activity'


def current(session, aid):
    return session.state['actors'][aid].get('source_states', {}).get(KEY)


@hook('journey_command')
def command(session, aid, kind, payload):
    if kind not in ('activity_start', 'activity_work', 'activity_cancel'):
        return None
    actor = session.state['actors'][aid]
    require(not actor['incapacitated'], 'An incapacitated creature cannot perform an activity.')
    states = actor.setdefault('source_states', {})
    row = current(session, aid)
    if kind == 'activity_start':
        require(not row and set(payload) == {'source', 'parameters'} and type(payload['source']) is str
                and isinstance(payload['parameters'], dict), 'Choose one available activity and its parameters.')
        specs = [s for s in run_strict('activity_spec', session, aid, payload['source'], payload['parameters']) if s is not None]
        require(len(specs) == 1, 'That activity is not available to this creature.')
        spec = specs[0]
        require(integer(spec['seconds'], 1) and type(spec['label']) is str, 'An activity needs a positive elapsed work duration.')
        row = {'source': payload['source'], 'parameters': deepcopy(payload['parameters']),
               'required_seconds': spec['seconds'], 'worked_seconds': 0, 'label': spec['label'],
               'started_at': int(session.clock()), 'journey_id': session.state['journey_id']}
        run_strict('activity_started', session, aid, row)
        states[KEY] = row
        session.emit('ACTIVITY_STARTED', aid, activity=deepcopy(row))
    elif kind == 'activity_cancel':
        require(row is not None and not payload, 'Choose the current activity to cancel.')
        del states[KEY]
        run_strict('activity_interrupted', session, aid, row)
        session.emit('ACTIVITY_INTERRUPTED', aid, source=row['source'])
    else:
        require(row is not None and set(payload) == {'seconds'} and integer(payload['seconds'], 1)
                and payload['seconds'] <= row['required_seconds'] - row['worked_seconds'], 'Work only the remaining whole seconds of the current activity.')
        run_strict('activity_validate', session, aid, row)
        session.tick(payload['seconds'])
        run_strict('activity_validate', session, aid, row)
        row['worked_seconds'] += payload['seconds']
        session.emit('ACTIVITY_WORKED', aid, source=row['source'], seconds_worked=payload['seconds'], total=row['worked_seconds'])
        if row['worked_seconds'] == row['required_seconds']:
            run_strict('activity_finished', session, aid, row)
            del states[KEY]
            session.emit('ACTIVITY_FINISHED', aid, activity=deepcopy(row))
    return True


@hook('journey_before_command')
def interrupt(session, aid, kind, payload):
    # Work is deliberately exclusive. A command can cancel first; declarations
    # and recipient choices do not themselves claim work or interrupt it.
    for who, actor in session.state['actors'].items():
        row=current(session,who)
        if not row: continue
        ordinary=(kind in ('wait','move','long_rest','short_rest','incapacitated') and who==aid
                  or kind in ('enter_combat','finish'))
        source_interrupt=any(reply is True for reply in run_strict('activity_command_interrupts',session,who,row,aid,kind,payload))
        if ordinary or source_interrupt:
            del actor['source_states'][KEY]
            run_strict('activity_interrupted',session,who,row)
            session.emit('ACTIVITY_INTERRUPTED',who,source=row['source'])


@hook('journey_options')
def options(session, aid):
    row = current(session, aid)
    if not row or session.state['phase'] != 'travel':
        return None
    return [{'id': 'activity:work', 'kind': 'activity_work', 'auto_select': 0,
             'payload': {'seconds': row['required_seconds'] - row['worked_seconds']},
             'label': session.state['actors'][aid]['name']+': work '+str(row['required_seconds']-row['worked_seconds'])+' more seconds to finish '+row['label']},
            {'id': 'activity:cancel', 'kind': 'activity_cancel', 'auto_select': 0,
             'payload': {}, 'label': 'Stop '+row['label']+'; unfinished work is interrupted'}]
