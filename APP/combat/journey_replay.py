"""Native world/scene operations used by JourneyStore and its single replay journal.

These operations mutate only the detached journey session. JourneyStore records
their parameters and state hash alongside actor commands; replay calls the same
operations without writing or regranting benefits in the saved journey.
"""
from .ext import run_strict


def world(session, payload):
    from .fact_consent_admission import declare_world, KEY as FACTS
    receipt_id = declare_world(session, payload)
    receipt = next(r for r in session.state[FACTS] if r['receipt_id'] == receipt_id)
    run_strict('journey_world_fact_committed', session, receipt)


def scene(session, reason):
    """Start the next scene and record the table owner's system scene_end fact.

    `revision` is the journey revision the table owner saw: the value before this
    command increments it, which keeps the declaration scope identical on replay.
    """
    from .fact_consent_admission import declare_world
    revision = session.state['revision']
    previous = session.state.get('scene_id', session.state['journey_id'])
    number = int(session.state.get('scene_number', 0)) + 1
    current = session.state['journey_id'] + ':scene:' + str(number)
    session.state['scene_id'] = current
    session.state['scene_number'] = number
    run_strict('journey_scene_end', session, previous, current)
    subject = next(iter(session.state['actors']))
    receipt = declare_world(session, {
        'source': 'system:journey.scene', 'subject': subject, 'kind': 'scene_end',
        'scope': previous + ':' + str(revision), 'value': reason.strip(),
        'expires_at': int(session.clock()) + 1, 'readers': list(session.state['actors']),
    })
    session.emit('SCENE_ENDED', subject, authority='table_owner',
                 previous_scene=previous, next_scene=current, reason=reason.strip(),
                 declaration_receipt=receipt)
