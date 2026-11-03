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
    previous = session.state.get('scene_id', session.state['journey_id'])
    number = int(session.state.get('scene_number', 0)) + 1
    current = session.state['journey_id'] + ':scene:' + str(number)
    session.state['scene_id'] = current
    session.state['scene_number'] = number
    run_strict('journey_scene_end', session, previous, current)
    session.emit('SCENE_ENDED', next(iter(session.state['actors'])), authority='table_owner',
                 previous_scene=previous, next_scene=current, reason=reason.strip())
