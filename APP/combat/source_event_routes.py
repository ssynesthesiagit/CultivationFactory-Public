"""Owner-only campaign source-event HTTP routes behind Foundry session CSRF.

Never register these on an actor/model tool router. The ordinary loopback and
session-token middleware authenticates the local owner; evidence is private.
"""
from pydantic import StrictInt
from .models import StrictModel


class SourceEventRequest(StrictModel):
    document: dict
    evidence: dict
    state_version: StrictInt


def register_source_event_routes(app, table):
    def invoke(call):
        from app.core import FoundryError
        from .tabletop import TabletopError
        try:
            return call()
        except TabletopError as exc:
            raise FoundryError(exc.code, str(exc), status_code=exc.status_code) from exc
        except ValueError as exc:
            raise FoundryError('TABLETOP_SOURCE_EVENT_INVALID', str(exc), status_code=422) from exc

    @app.post('/api/tabletop/matches/{match_id}/source-events')
    def record(match_id: str, body: SourceEventRequest):
        return invoke(lambda: table.record_source_event(match_id, body.document, body.evidence, body.state_version))

    @app.post('/api/tabletop/matches/{match_id}/source-events/synchronize')
    def synchronize(match_id: str):
        return invoke(lambda: table.synchronize_source_events(match_id))
