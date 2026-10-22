"""Journey world/scene transaction adapters.

The durable command replay ledger is owned by JourneyStore in journey.py;
these adapters perform its world-fact and scene-end operations and emit
extension notifications. They intentionally keep no parallel replay state.
"""
from .ext import run_strict


def world(session, payload):
    from .fact_consent_admission import declare_world, KEY as FACTS
    receipt_id = declare_world(session, payload)
    receipt = next(r for r in session.state[FACTS] if r['receipt_id'] == receipt_id)
    run_strict('journey_world_fact_committed', session, receipt)


def scene(session, reason):
    previous = session.state.get('scene_id', session.state['journey_id'])
    number = int(session.state.get('scene_number', 0)) + 1
    current = session.state['journey_id'] + ':scene:' + str(number)
    session.state['scene_id'] = current
    session.state['scene_number'] = number
    run_strict('journey_scene_end', session, previous, current)
    session.emit('SCENE_ENDED', next(iter(session.state['actors'])), authority='table_owner',
                 previous_scene=previous, next_scene=current, reason=reason.strip())
