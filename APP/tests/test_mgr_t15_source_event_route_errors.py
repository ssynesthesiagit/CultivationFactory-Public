"""Finding 4 regression (MGR-T15 Oath-Skin Frame F12R): source-event 422 bodies stay generic.

The validators raise ValueError with developer diagnostics. Those strings must not
reach the player through the HTTP error body. The route is registered on a minimal
app with a fake table, so this file needs no fight fixture and no private harness.
"""
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core import FoundryError
from combat.source_event_routes import SOURCE_EVENT_REFUSED, register_source_event_routes
from combat.tabletop import TabletopError
from tests.async_support import run_asgi

LEAK = 'Use the exact controlling Oath-Skin Frame source; private evidence text: story-secret-42'
BODY = {'document': {'event_id': 'x'}, 'evidence': {}, 'state_version': 1}


class RaisingTable:
    def __init__(self, error):
        self.error = error

    def record_source_event(self, match_id, document, evidence, state_version):
        raise self.error

    def synchronize_source_events(self, match_id):
        raise self.error


def _client_for(error):
    app = FastAPI()

    @app.exception_handler(FoundryError)
    async def handler(request, exc: FoundryError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    register_source_event_routes(app, RaisingTable(error))
    return app


def _post(app, path, body=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            return await client.post(path, json=body)
    return run_asgi(run())


def test_validator_value_error_is_not_echoed_in_422_body():
    response = _post(_client_for(ValueError(LEAK)), '/api/tabletop/matches/m1/source-events', BODY)
    assert response.status_code == 422
    assert LEAK not in response.text
    error = response.json()['error']
    assert error['code'] == 'TABLETOP_SOURCE_EVENT_INVALID'
    assert error['message'] == SOURCE_EVENT_REFUSED


def test_tabletop_source_event_refusal_is_not_echoed_in_422_body():
    error = TabletopError('TABLETOP_SOURCE_EVENT_INVALID', LEAK, 422)
    response = _post(_client_for(error), '/api/tabletop/matches/m1/source-events', BODY)
    assert response.status_code == 422
    assert LEAK not in response.text
    assert response.json()['error']['message'] == SOURCE_EVENT_REFUSED


def test_synchronize_value_error_is_not_echoed_in_422_body():
    response = _post(_client_for(ValueError(LEAK)), '/api/tabletop/matches/m1/source-events/synchronize')
    assert response.status_code == 422
    assert LEAK not in response.text


def test_other_tabletop_errors_keep_their_own_message():
    error = TabletopError('TABLETOP_SOMETHING_ELSE', 'Visible ordinary refusal.', 409)
    response = _post(_client_for(error), '/api/tabletop/matches/m1/source-events', BODY)
    assert response.status_code == 409
    assert response.json()['error']['message'] == 'Visible ordinary refusal.'
