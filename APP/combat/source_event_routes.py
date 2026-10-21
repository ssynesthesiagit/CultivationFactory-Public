"""Owner-only campaign source-event HTTP routes behind Foundry session CSRF.

Never register these on an actor/model tool router. The ordinary loopback and
session-token middleware authenticates the local owner; evidence is private.

Refusal text from validators is developer diagnostics, not player copy: a
ValueError can quote private evidence or internal rule wording, so the 422 body
carries only a fixed sentence. The exception stays chained for server logs.
"""
from pydantic import StrictInt
from .models import StrictModel

SOURCE_EVENT_REFUSED = 'This source event cannot be recorded in the current fight state.'


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
            if exc.code == 'TABLETOP_SOURCE_EVENT_INVALID':
                raise FoundryError(exc.code, SOURCE_EVENT_REFUSED, status_code=422) from exc
            raise FoundryError(exc.code, str(exc), status_code=exc.status_code) from exc
        except ValueError as exc:
            raise FoundryError('TABLETOP_SOURCE_EVENT_INVALID', SOURCE_EVENT_REFUSED, status_code=422) from exc

    @app.post('/api/tabletop/matches/{match_id}/source-events')
    def record(match_id: str, body: SourceEventRequest):
        return invoke(lambda: table.record_source_event(match_id, body.document, body.evidence, body.state_version))

    @app.post('/api/tabletop/matches/{match_id}/source-events/synchronize')
    def synchronize(match_id: str):
        return invoke(lambda: table.synchronize_source_events(match_id))
