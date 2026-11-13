"""The HTTP admission boundary precedes activity and stamped assets."""
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client_and_app(tmp_path):
    app = create_app(Settings.from_env(ROOT, tmp_path))
    return TestClient(app), app


@pytest.mark.parametrize(
    "headers,code",
    [
        ({"host": "evil.example", "x-foundry-token": "valid"}, "NON_LOOPBACK_HOST"),
        ({"origin": "http://evil.example", "x-foundry-token": "valid"}, "ORIGIN_REJECTED"),
        ({}, "CSRF_TOKEN_REQUIRED"),
    ],
)
def test_refused_commands_do_not_record_activity(client_and_app, headers, code):
    client, app = client_and_app
    headers = dict(headers)
    if "x-foundry-token" in headers:
        headers["x-foundry-token"] = app.state.session_token
    table = app.state.agent_seats.table
    before_requests = dict(table._last_requests)
    before_commands = dict(table._last_commands)
    response = client.post("/api/tabletop/matches/synthetic/settings", json={}, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == code
    assert "x-factory-build" in response.headers
    assert table._last_requests == before_requests
    assert table._last_commands == before_commands


def test_refused_stamped_module_is_not_served(client_and_app):
    client, _ = client_and_app
    path = "/static/tabletop/build-check.js"
    assert client.get(path).status_code == 200
    response = client.get(path, headers={"host": "evil.example"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NON_LOOPBACK_HOST"
    assert "x-factory-build" in response.headers


@pytest.mark.parametrize(
    "host,expected",
    [
        ("[::1]:8765", 200),
        ("localhost:8765", 200),
        ("localhost.evil", 403),
        ("127.0.0.1@evil", 403),
        ("localhost:bad", 403),
        ("", 403),
    ],
)
def test_host_authority(client_and_app, host, expected):
    client, _ = client_and_app
    response = client.get("/api/session", headers={"host": host})
    assert response.status_code == expected
    assert "x-factory-build" in response.headers


def test_malformed_host_logs_one_timing_line(client_and_app, monkeypatch):
    client, app = client_and_app
    info = Mock()
    monkeypatch.setattr(app.state.timing_logger, "info", info)
    response = client.get("/api/session?secret=hidden", headers={"host": "[::1"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NON_LOOPBACK_HOST"
    info.assert_called_once()
    line = info.call_args.args[0]
    assert "path=/api/session status=403" in line
    assert "secret" not in line
