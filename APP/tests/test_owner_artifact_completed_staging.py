from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.api import create_app
from app.core import FoundryError, Settings, sha256_file
from app.models import OwnerArtifactStageRequest


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "project.owner-artifact.completed"
VERIFIED_STATUS = "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"


def _stage_endpoint(app):
    return next(route.endpoint for route in app.routes if route.path == "/api/owner-artifacts/stage")


def _verified_result(source: Path, *, project_id: str = PROJECT_ID) -> dict:
    digest = sha256_file(source)
    return {
        "status": VERIFIED_STATUS,
        "project_id": project_id,
        "package_path": str(source.resolve()),
        "package_sha256": digest,
        "audit": {
            "valid": True,
            "path": str(source.resolve()),
            "sha256": digest,
            "bytes": source.stat().st_size,
            "manifest": {"project_id": project_id},
        },
    }


@pytest.fixture(scope="module")
def stage_context(tmp_path_factory):
    app = create_app(Settings.from_env(ROOT, tmp_path_factory.mktemp("owner-artifact-data")))
    return app, _stage_endpoint(app)


def test_completed_character_stages_and_restages_exact_verified_bytes_without_gm_export(
    stage_context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    app, stage = stage_context
    source = tmp_path / "verified-character.zip"
    payload = b"exact verified portable package bytes"
    source.write_bytes(payload)
    verified = _verified_result(source)
    gm_calls: list[tuple[tuple, dict]] = []

    def forbidden_gm_export(*args, **kwargs):
        gm_calls.append((args, kwargs))
        raise AssertionError("completed_character must not invoke GM export")

    monkeypatch.setattr(app.state.portable_characters, "verified_status", lambda project_id: verified)
    monkeypatch.setattr(app.state.gm_exports, "export", forbidden_gm_export)

    request = OwnerArtifactStageRequest(artifact_kind="completed_character", project_id=PROJECT_ID)
    first = stage(request)
    second = stage(request)

    expected_hash = hashlib.sha256(payload).hexdigest()
    assert first["artifact_kind"] == second["artifact_kind"] == "completed_character"
    assert first["path"] == second["path"] == str(source.resolve())
    assert first["filename"] == second["filename"] == source.name
    assert first["bytes"] == second["bytes"] == len(payload)
    assert first["sha256"] == second["sha256"] == expected_hash
    assert first["source_result"] == second["source_result"] == verified
    assert source.read_bytes() == payload
    assert gm_calls == []


@pytest.mark.parametrize(
    "state",
    [
        "missing",
        "stale",
        "unverified",
        "hash_mismatch",
        "audit_mismatch",
        "project_mismatch",
        "audit_manifest_mismatch",
    ],
)
def test_completed_character_rejects_noncurrent_verified_state_without_staging(
    stage_context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
):
    app, stage = stage_context
    source = tmp_path / "verified-character.zip"
    payload = b"package that must never be staged for an invalid state"
    source.write_bytes(payload)
    verified = _verified_result(source)
    if state == "missing":
        source.unlink()
    elif state == "stale":
        verified["status"] = "STALE"
    elif state == "unverified":
        verified["status"] = "PENDING"
    elif state == "hash_mismatch":
        verified["package_sha256"] = "0" * 64
    elif state == "audit_mismatch":
        verified["audit"]["sha256"] = "0" * 64
    elif state == "project_mismatch":
        verified["project_id"] = "another-project"
    elif state == "audit_manifest_mismatch":
        verified["audit"]["manifest"]["project_id"] = "another-project"
    gm_calls: list[tuple[tuple, dict]] = []

    monkeypatch.setattr(app.state.portable_characters, "verified_status", lambda project_id: verified)
    monkeypatch.setattr(app.state.gm_exports, "export", lambda *args, **kwargs: gm_calls.append((args, kwargs)))

    with pytest.raises(FoundryError) as exc:
        stage(OwnerArtifactStageRequest(artifact_kind="completed_character", project_id=PROJECT_ID))

    assert exc.value.code == "OWNER_ARTIFACT_COMPLETED_PACKAGE_NOT_CURRENT"
    assert exc.value.status_code == 409
    assert gm_calls == []
    if source.exists():
        assert source.read_bytes() == payload


def test_gm_character_retains_gm_export_delegation(stage_context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app, stage = stage_context
    source = tmp_path / "gm-character.zip"
    source.write_bytes(b"gm export bytes")
    export_result = {"exported": True, "path": str(source), "sha256": sha256_file(source), "bytes": source.stat().st_size}
    calls: list[tuple[str, str | None]] = []

    def gm_export(project_id: str, *, filename: str | None = None):
        calls.append((project_id, filename))
        return export_result

    monkeypatch.setattr(app.state.gm_exports, "export", gm_export)
    monkeypatch.setattr(app.state.portable_characters, "verified_status", lambda project_id: pytest.fail("GM export should not consult completed package staging"))

    staged = stage(OwnerArtifactStageRequest(artifact_kind="gm_character", project_id=PROJECT_ID, filename="chosen.zip"))

    assert calls == [(PROJECT_ID, "chosen.zip")]
    assert staged["artifact_kind"] == "gm_character"
    assert staged["path"] == str(source.resolve())
    assert staged["source_result"] == export_result
