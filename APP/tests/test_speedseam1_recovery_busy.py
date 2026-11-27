"""Regression checks for recovery ordering and Local Auto lock contention."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.api import create_app
from app.core import Settings
from combat import tabletop_service
from combat.gate3_storage import LocalMatchWriterLock
from combat.gate5_service import CombatService
from tests.worker2_support import ROOT, fixture


def test_recovered_session_is_not_cached_under_a_newer_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    _, table, mid = fixture(tmp_path, [], ask=False)
    fresh = CombatService(ROOT, tmp_path)
    host = fresh.fight_host(retain=True)
    state = table.state(mid)
    menu = state["menu"]

    def recover_then_other_writer(match_id):
        recovered = fresh._load_session(match_id)
        result = table.act(mid, menu["end_turn"], menu["decision_id"],
                           menu["state_version"], state["last_sequence"])
        assert result["status"] == "COMMITTED"
        return recovered

    monkeypatch.setattr(fresh, "recover_match", recover_then_other_writer)
    stale = host.session(mid)
    # A subsequent read must observe the commit, not accept the stale engine.
    monkeypatch.setattr(fresh, "recover_match", lambda match_id: None)
    current = host.session(mid)
    assert current.engine.state.state_version > stale.engine.state.state_version
    assert current.engine.state.state_version == fresh._load_session(mid).engine.state.state_version


@pytest.mark.parametrize("endpoint,body", [("local-step", {}), ("local-run", {"maximum_steps": 1})])
def test_local_auto_busy_is_retryable_over_http(tmp_path, monkeypatch, endpoint, body):
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    monkeypatch.setattr(tabletop_service, "TABLE_BUSY_WAIT_S", 0)
    combat, _, mid = fixture(tmp_path, [], ask=False)
    original = Draft202012Validator.check_schema
    Draft202012Validator.check_schema = classmethod(lambda cls, schema, format_checker=None: None)
    try:
        app = create_app(Settings.from_env(Path(__file__).resolve().parents[1], tmp_path))
    finally:
        Draft202012Validator.check_schema = original
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
    with LocalMatchWriterLock(combat._match_dir(mid) / ".tabletop_action.lock", mid):
        response = client.post(f"/api/combat/matches/{mid}/{endpoint}", json=body, headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "TABLETOP_BUSY"
    assert tabletop_service.TABLE_BUSY_MESSAGE in response.text
