"""Journey world/scene transaction adapters.

The durable command replay ledger is owned by JourneyStore in journey.py;
these adapters perform its world-fact operation and emit extension
notifications. Consumer: JourneySession.gm, which is the one world-fact commit,
so JourneyStore.record_world_fact and a cold replay run this same code.
Scene endings are JourneyStore.end_scene only (one implementation).
They intentionally keep no parallel replay state.
"""
from .ext import run_strict


def world(session, payload):
    from .fact_consent_admission import declare_world, KEY as FACTS
    receipt_id = declare_world(session, payload)
    receipt = next(r for r in session.state[FACTS] if r['receipt_id'] == receipt_id)
    run_strict('journey_world_fact_committed', session, receipt)

