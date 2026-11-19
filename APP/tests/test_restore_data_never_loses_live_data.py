"""Publication failure and interruption never restore the database or data root."""
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings
from character_creation import auto_token, finalization
from tests.test_finalsafe1_restore_scope import assert_no_stage, service_at


@pytest.fixture(autouse=True)
def no_automatic_portraits(monkeypatch):
    monkeypatch.setattr(auto_token, "start", lambda *a, **k: None)


@pytest.mark.parametrize("boundary", [
    "after_staging", "after_database_commit", "mid_promotion", "after_promotion",
])
def test_failure_at_each_publication_boundary_is_atomic(tmp_path, boundary):
    service, run = service_at(tmp_path)
    live = service.db.settings.data_dir
    (live / "projects").mkdir()
    previous = live / "projects" / "p.json"
    previous.write_text("previous")
    (live / "unrelated.json").write_text("keep")
    sealed = live / "sealed_snapshot"
    sealed.mkdir()
    (sealed / "manifest.json").write_text("sealed original")
    sealed.chmod(0o500)
    with service.db.connection() as conn:
        before = [tuple(row) for row in conn.execute("SELECT * FROM preferences")]
    if boundary == "after_staging":
        with pytest.raises(FoundryError) as caught:
            service.finalize(run["run_id"], fail_after=boundary)
        assert caught.value.code == "CG1_FINALIZATION_ROLLED_BACK"
        assert previous.read_text() == "previous"
        assert service.get(run["run_id"])["status"] == "READY_FOR_REVIEW"
        assert not (live / "character_sheets" / "sheet.json").exists()
    else:
        assert service.finalize(run["run_id"], fail_after=boundary)["status"] == "CLEAN_AND_FINALIZED"
        assert previous.read_text() == "finalized"
        assert (live / "character_sheets" / "sheet.json").read_text() == "sheet"
    with service.db.connection() as conn:
        assert [tuple(row) for row in conn.execute("SELECT * FROM preferences")] == before
        assert len(conn.execute("SELECT * FROM owned").fetchall()) == (0 if boundary == "after_staging" else 2)
    assert (live / "unrelated.json").read_text() == "keep"
    assert (sealed / "manifest.json").read_text() == "sealed original"
    assert sealed.stat().st_mode & 0o777 == 0o500
    assert_no_stage(service)
    sealed.chmod(0o700)


def _crash_finalize(root, boundary):
    auto_token.start = lambda *a, **k: None
    service, run = service_at(Path(root))
    original = finalization.failpoint

    def crash(phase, fail_after):
        if phase == boundary:
            os._exit(73)
        original(phase, fail_after)
    finalization.failpoint = crash
    service.finalize(run["run_id"])
    os._exit(74)  # The requested boundary must have been reached.


@pytest.mark.parametrize("boundary", ["after_staging", "after_database_commit", "mid_promotion"])
def test_interrupted_finalize_recovers_from_lifecycle_record(tmp_path, boundary):
    service, run = service_at(tmp_path)
    live = service.db.settings.data_dir
    (live / "projects").mkdir()
    (live / "projects" / "p.json").write_text("previous")
    (live / "unrelated.json").write_text("keep")
    child = multiprocessing.get_context("spawn").Process(
        target=_crash_finalize, args=(str(tmp_path), boundary),
    )
    child.start()
    child.join(30)
    if child.is_alive():
        child.terminate()
        child.join(10)
        pytest.fail("publication subprocess did not reach its crash boundary")
    assert child.exitcode == 73

    with service.db.connection() as conn:
        row = conn.execute("SELECT status,commit_json FROM character_creation_runs").fetchone()
    if boundary == "after_staging":
        assert row["status"] == "READY_FOR_REVIEW"
    else:
        assert row["status"] == "PUBLISHING"
        receipt = json.loads(row["commit_json"])["publication"]
        directory = finalization.publication_root(service.db) / receipt["directory"]
        if boundary == "mid_promotion":
            # Replaced bytes must still exist until the entire publication completes.
            # Depending on sorted ordering the replaced project may not be first yet.
            assert (directory / "data" / "projects" / "p.json").exists() or (
                directory / "replaced" / "projects" / "p.json").read_text() == "previous"

    # Exercise the actual startup recovery entry point, not just finish().
    from character_creation import CharacterCreationExecutionService
    from project_store.service import ProjectStore
    reopened_db = Database(service.db.settings)
    CharacterCreationExecutionService(
        reopened_db, stage1=None, provider=None, project_store=ProjectStore(reopened_db),
    )
    result = service.get(run["run_id"])
    if boundary == "after_staging":
        assert result["status"] == "READY_FOR_REVIEW"
        assert (live / "projects" / "p.json").read_text() == "previous"
        assert not (live / "character_sheets" / "sheet.json").exists()
    else:
        assert result["status"] == "CLEAN_AND_FINALIZED"
        assert (live / "projects" / "p.json").read_text() == "finalized"
        assert (live / "character_sheets" / "sheet.json").read_text() == "sheet"
    with reopened_db.connection() as conn:
        assert conn.execute("SELECT value FROM preferences").fetchone()[0] == "MANUAL_CHAT"
        assert len(conn.execute("SELECT * FROM owned").fetchall()) == (0 if boundary == "after_staging" else 2)
    assert (live / "unrelated.json").read_text() == "keep"
    assert_no_stage(service)


def test_failed_promotion_keeps_replaced_files_until_retry(tmp_path, monkeypatch):
    service, run = service_at(tmp_path)
    live = service.db.settings.data_dir
    (live / "projects").mkdir()
    previous = live / "projects" / "p.json"
    previous.write_text("previous")
    real_replace = os.replace

    def fail(src, dst):
        if Path(dst) == previous and "data" in Path(src).parts:
            raise OSError("disk unavailable")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(FoundryError) as caught:
        service.finalize(run["run_id"])
    assert caught.value.code == "CG1_PUBLICATION_PENDING"
    pending = service.get(run["run_id"])
    assert pending["status"] == "PUBLISHING"
    receipt = pending["commit"]["publication"]
    directory = finalization.publication_root(service.db) / receipt["directory"]
    assert (directory / "replaced" / "projects" / "p.json").read_text() == "previous"
    monkeypatch.setattr(os, "replace", real_replace)
    assert service.finalize(run["run_id"])["status"] == "CLEAN_AND_FINALIZED"
    assert previous.read_text() == "finalized"
    assert_no_stage(service)
