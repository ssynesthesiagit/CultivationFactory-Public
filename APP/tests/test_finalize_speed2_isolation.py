"""Installed-character read failures must not hide healthy combat candidates."""

from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
import pytest

from app.api import create_app
from app.core import Settings
from app.validation_cache import _file_hashes
from combat.pre_encounter import CombatantLibraryService
from tests.test_c3b_pre_encounter import ROOT, _install


def _install_pair(data):
    healthy = _install(data, directory="healthy")
    broken = _install(data, directory="unreadable")
    return healthy, broken


def _deny_reads(monkeypatch, path, error_type):
    # A real, stat-able installation, with an OS read failure independent of
    # metadata changes. Evict digest instrumentation so the fingerprint reads
    # the file even after a successful inventory warmed the digest cache.
    before = path.stat()
    _file_hashes.clear()
    original_open = Path.open
    state = {"denied": True, "attempts": 0}

    def open_path(self, *args, **kwargs):
        if self == path and state["denied"]:
            state["attempts"] += 1
            raise error_type(f"Cannot read installed character file: {path.name}")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_path)
    assert path.is_file() and path.stat() == before
    return state


def _assert_isolated(inventory, entry, broken):
    assert inventory.accepted_candidates == (entry,)
    assert inventory.accepted_count == 1
    assert inventory.duplicate_identical_count == 0
    assert inventory.blocked_count == 1
    block = inventory.blocked_candidates[0]
    assert block.installed_record == str(broken / "current.json")
    assert block.code == "C3B_CANDIDATE_VALIDATION_FAILED"
    assert "Cannot read installed character file" in block.message


@pytest.mark.parametrize("filename", ["current.json", "current.zip"])
@pytest.mark.parametrize("error_type", [PermissionError, OSError])
def test_inventory_isolates_unreadable_installation_cold_warm_and_recovery(
    tmp_path, monkeypatch, filename, error_type,
):
    data = tmp_path / "data"
    _, broken = _install_pair(data)
    warm = CombatantLibraryService(ROOT, data)
    before = warm.inventory()
    assert before.accepted_count == 1 and before.duplicate_identical_count == 1
    entry = before.accepted_candidates[0]
    state = _deny_reads(monkeypatch, broken / filename, error_type)

    for service in (warm, CombatantLibraryService(ROOT, data)):
        for _ in range(2):
            attempts = state["attempts"]
            _assert_isolated(service.inventory(), entry, broken)
            assert state["attempts"] > attempts
        state["denied"] = False
        recovered = service.inventory()
        assert recovered == before
        state["denied"] = True
        _file_hashes.clear()


@pytest.mark.parametrize("filename", ["current.json", "current.zip"])
def test_candidate_api_keeps_healthy_installation_when_another_is_unreadable(
    tmp_path, monkeypatch, filename,
):
    settings = Settings.from_env(ROOT, tmp_path / "api-data")
    _, broken = _install_pair(settings.data_dir)
    # Match the existing C3B API harness: schemas have separate validation
    # coverage; this test exercises real routes, library, package and storage.
    with monkeypatch.context() as schema_patch:
        schema_patch.setattr(
            Draft202012Validator, "check_schema",
            classmethod(lambda cls, schema, format_checker=None: None),
        )
        app = create_app(settings)
    before = app.state.combatant_library.inventory()
    entry = before.accepted_candidates[0]
    state = _deny_reads(monkeypatch, broken / filename, PermissionError)

    with TestClient(app) as client:
        for _ in range(2):
            response = client.get("/api/combat/candidates")
            assert response.status_code == 200, response.text
            inventory = response.json()
            assert inventory["accepted_count"] == inventory["blocked_count"] == 1
            assert inventory["accepted_candidates"][0]["entry_id"] == entry.entry_id
            assert inventory["blocked_candidates"][0]["installed_record"] == str(broken / "current.json")
            detail = client.get(f"/api/combat/candidates/{quote(entry.entry_id, safe='')}")
            assert detail.status_code == 200, detail.text
            assert detail.json() == entry.model_dump(mode="json", by_alias=True)
        state["denied"] = False
        recovered = client.get("/api/combat/candidates")
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["accepted_count"] == 1
        assert recovered.json()["blocked_count"] == 0
        assert recovered.json()["duplicate_identical_count"] == 1
