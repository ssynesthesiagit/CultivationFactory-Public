"""Journey world/scene transaction adapters.

The durable command replay ledger is owned by JourneyStore in journey.py;
these adapters perform its world-fact and scene-end operations and emit
extension notifications. They intentionally keep no parallel replay state.
Consumer: JourneySession.gm, which is the one world-fact commit, so
JourneyStore.record_world_fact and a cold replay run this same code.
Consumer: JourneyStore.end_scene, which owns the store checks and the
journaled save, and JourneyStore.replay, which runs the same scene transition
for the journaled command. One scene-ending implementation, no replay copy.
"""
from .ext import run_strict


def world(session, payload):
    from .fact_consent_admission import declare_world, KEY as FACTS
    receipt_id = declare_world(session, payload)
    receipt = next(r for r in session.state[FACTS] if r['receipt_id'] == receipt_id)
    run_strict('journey_world_fact_committed', session, receipt)


def scene(session, reason):
    """Open the next scene and record the table owner's declaration receipt.

    Consumers: JourneyStore.end_scene (live, journaled) and JourneyStore.replay
    (cold replay of the same journal command), so both run one transition.
    """
    previous = session.state.get('scene_id', session.state['journey_id'])
    from .fact_consent_admission import declare_world
    subject = next(iter(session.state['actors']))
    receipt = declare_world(session, {
        'source': 'system:journey.scene', 'subject': subject, 'kind': 'scene_end',
        'scope': previous + ':' + str(session.state['revision']), 'value': reason.strip(),
        'expires_at': int(session.clock()) + 1, 'readers': list(session.state['actors']),
    })
    number = int(session.state.get('scene_number', 0)) + 1
    current = session.state['journey_id'] + ':scene:' + str(number)
    session.state['scene_id'] = current
    session.state['scene_number'] = number
    run_strict('journey_scene_end', session, previous, current)
    session.emit('SCENE_ENDED', subject, authority='table_owner',
                 previous_scene=previous, next_scene=current, reason=reason.strip(),
                 declaration_receipt=receipt)

