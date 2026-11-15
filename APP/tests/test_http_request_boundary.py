"""Real middleware regressions: rejected requests must not serve table assets
or refresh a fight's deployment activity; bracketed loopback IPv6 is valid.

Negative control: these requests reach the original middleware stack, which
serves stamped assets and records activity before its Host/Origin/token checks.
"""
import gzip
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings
from app.static_build import BUILD_HEADER


@pytest.fixture(scope="module")
def local_client(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    settings = Settings.from_env(root, tmp_path_factory.mktemp("http-boundary"))
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, app.state.agent_seats.table


@pytest.mark.parametrize("host", [
    "127.0.0.1", "127.0.0.1:8765", "localhost", "LOCALHOST:8765",
    "testserver", "[::1]", "[::1]:8765",
])
def test_loopback_authorities_reach_session(local_client, host):
    client, _ = local_client
    response = client.get("/api/session", headers={"host": host})
    assert response.status_code == 200
    assert response.json()["token"]
    assert response.headers[BUILD_HEADER]


@pytest.mark.parametrize("host", [
    "remote.invalid", "localhost.remote.invalid", "localhost:notaport",
    "127.0.0.1:65536", "localhost:80:90", "localhost:80/path",
    "localhost:80?", "localhost:80#", "localhost:80@localhost", "localhost:80@127.0.0.1",
    "[", "[::1]extra", "[::1]extra:80",
])
def test_only_complete_loopback_authorities_are_admitted(local_client, host):
    client, _ = local_client
    response = client.get("/api/session", headers={"host": host})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NON_LOOPBACK_HOST"
    assert response.headers[BUILD_HEADER]


@pytest.mark.parametrize("path", ["/tabletop", "/static/tabletop/build-check.js", "/static/tabletop/tabletop.js"])
@pytest.mark.parametrize(("method", "headers", "code"), [
    ("GET", {"host": "remote.invalid"}, "NON_LOOPBACK_HOST"),
    ("GET", {"origin": "http://remote.invalid"}, "ORIGIN_REJECTED"),
    ("POST", {}, "CSRF_TOKEN_REQUIRED"),
])
def test_stamped_assets_obey_the_same_request_boundary(local_client, path, method, headers, code):
    client, _ = local_client
    response = client.request(method, path, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == code
    assert response.headers[BUILD_HEADER]


@pytest.mark.parametrize(("method", "headers", "code"), [
    ("GET", {"host": "remote.invalid"}, "NON_LOOPBACK_HOST"),
    ("POST", {"origin": "http://remote.invalid"}, "ORIGIN_REJECTED"),
    ("POST", {}, "CSRF_TOKEN_REQUIRED"),
])
def test_rejected_requests_do_not_refresh_match_activity(local_client, method, headers, code):
    client, table = local_client
    match_id = "match:" + hashlib.sha256(code.encode()).hexdigest()[:24]
    manifest = table._match_dir(match_id) / "Manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"terminal_result":null}', encoding="utf-8")
    before = manifest.read_bytes()
    response = client.request(method, f"/api/tabletop/matches/{match_id}/not-a-route", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == code
    assert match_id not in table._last_requests
    assert match_id not in table._last_commands
    assert manifest.read_bytes() == before


def test_admitted_poll_and_command_keep_distinct_activity(local_client):
    client, table = local_client
    match_id = "match:" + "a" * 24
    manifest = table._match_dir(match_id) / "Manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"terminal_result":null}', encoding="utf-8")
    path = f"/api/tabletop/matches/{match_id}/not-a-route"
    assert client.get(path).status_code == 404
    assert match_id in table._last_requests
    assert match_id not in table._last_commands
    token = client.get("/api/session").json()["token"]
    assert client.post(path, headers={"x-foundry-token": token}).status_code == 404
    assert match_id in table._last_commands


@pytest.mark.parametrize("path", ["/tabletop", "/static/tabletop/build-check.js"])
def test_admitted_assets_keep_build_stamp_and_cache_policy(local_client, path):
    client, _ = local_client
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    build = response.headers[BUILD_HEADER]
    assert build == client.get("/api/session").headers[BUILD_HEADER]
    if path == "/tabletop":
        assert f"?v={build}" in response.text


def test_stamped_asset_compression_preserves_body_and_headers(local_client):
    client, _ = local_client
    path = "/static/tabletop/tabletop.js"
    identity = client.get(path, headers={"accept-encoding": "identity"})
    assert identity.status_code == 200
    assert "content-encoding" not in identity.headers
    assert len(identity.content) > 1000
    with client.stream("GET", path, headers={"accept-encoding": "gzip"}) as compressed:
        assert compressed.status_code == 200
        assert compressed.headers["content-encoding"] == "gzip"
        wire = b"".join(compressed.iter_raw())
        assert gzip.decompress(wire) == identity.content
        assert len(wire) < len(identity.content)
        assert int(compressed.headers["content-length"]) == len(wire)
        assert compressed.headers[BUILD_HEADER] == identity.headers[BUILD_HEADER]
        assert compressed.headers["cache-control"] == identity.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("encoding", ["identity", "gzip"])
def test_conditional_stamped_assets_keep_admission_and_cache_identity(local_client, encoding):
    client, _ = local_client
    path = "/static/tabletop/tabletop.js"
    initial = client.get(path, headers={"accept-encoding": encoding})
    headers = {"accept-encoding": encoding, "if-none-match": initial.headers["etag"]}
    cached = client.get(path, headers=headers)
    assert cached.status_code == 304
    assert cached.content == b""
    assert cached.headers["etag"] == initial.headers["etag"]
    assert cached.headers[BUILD_HEADER] == initial.headers[BUILD_HEADER]
    assert "accept-encoding" in cached.headers["vary"].lower()
    assert cached.headers["cache-control"] == "no-cache"
    rejected = client.get(path, headers={**headers, "host": "remote.invalid"})
    assert rejected.status_code == 403
    rejected = client.get(path, headers={**headers, "origin": "http://remote.invalid"})
    assert rejected.status_code == 403
    assert client.head(path, headers=headers).status_code == 304
