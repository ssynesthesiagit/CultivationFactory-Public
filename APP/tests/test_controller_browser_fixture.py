"""Socket-free coverage of the lead-run controller check's real HTTP fixtures.

These exercise ASGI routes, not rendered UI or the reserved-socket server launch.
"""
import io
import json
from types import SimpleNamespace
import urllib.error
import urllib.request

from fastapi.testclient import TestClient
import pytest

from tests import run_controller_browser as runner


@pytest.mark.parametrize('providers', [True, False])
def test_disposable_http_fixture_without_browser(tmp_path, monkeypatch, providers):
    data = tmp_path / 'data'
    runner.seed_sheets(data)
    path = data / 'providers.json'
    if providers:
        path.write_text(json.dumps({'providers': [
            {'id': pid, 'label': pid, 'kind': 'local', 'model': 'offline-' + pid,
             'base_url': 'http://testserver/controller-fixture/v1', 'timeout_s': 10,
             **({'prompt_profile': 'choices'} if pid == 'small' else {})}
            for pid in ('small', 'big')
        ]}))
    monkeypatch.setenv('FACTORY_SEAT_PROVIDERS', str(path))
    monkeypatch.setenv('TIANXIA_FOUNDRY_DATA', str(data))
    monkeypatch.setenv('TIANXIA_FOUNDRY_SECURITY_DIR', str(data / 'security'))
    for key in ('TIANXIA_FACTORY_ZIP', 'TIANXIA_FACTORY_FIXTURE'):
        monkeypatch.delenv(key, raising=False)
    with TestClient(runner.fixture_app(data), raise_server_exceptions=False) as client:
        def urlopen(request, timeout=None):
            request = urllib.request.Request(request) if isinstance(request, str) else request
            response = client.request(request.get_method(), request.full_url,
                                      headers=dict(request.header_items()), content=request.data)
            body = io.BytesIO(response.content)
            if response.status_code >= 400:
                raise urllib.error.HTTPError(request.full_url, response.status_code,
                                             response.reason_phrase, response.headers, body)
            return body

        monkeypatch.setattr(urllib.request, 'urlopen', urlopen)
        mid, name = runner.fixture('http://testserver', SimpleNamespace(poll=lambda: None), providers)
        assert mid and name == 'Controller fighter'
        assert path.exists() is providers
        state = client.get(f'/api/tabletop/matches/{mid}/state').json()
        assert state['menu']['actor_id'] == runner.ACTORS[0]
