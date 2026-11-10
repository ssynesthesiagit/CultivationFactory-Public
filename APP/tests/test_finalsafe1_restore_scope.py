"""Finalization owns one database transaction and only its staged file outputs."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from app.core import Database, FoundryError, Settings, canonical_json
from character_creation import finalization
from tests.test_cg1_owner_resolution_finalization import _finalization_service_and_run


class Pipeline:
    """Synthetic local build; no vendor, owner data, providers, or model servers."""
    def __init__(self, db, fail_after):
        self.db = db
        self.fail_after = fail_after
        self.production_release = SimpleNamespace(_stable=lambda release: {
            "factory_authoring": {}, "command5": {}, "consumer": {},
            "portable_audit": {}, "clean_import": {},
        })

    def _execute_live(self, run, plan, **kwargs):
        root = self.db.settings.data_dir
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO owned VALUES ('character')")
            conn.execute("INSERT INTO locations VALUES (?)",
                         (str(self.db.published_path(root / "character_sheets" / "sheet.json")),))
        (root / "projects").mkdir(exist_ok=True)
        (root / "projects" / "p.json").write_text("finalized")
        (root / "character_sheets").mkdir(exist_ok=True)
        (root / "character_sheets" / "sheet.json").write_text("sheet")
        if self.fail_after == "stage1":
            raise RuntimeError("forced failure after stage1")
        return {"_production_release": {"production_artifact_identity": "release"},
                "sheet": {"path": str(root / "character_sheets" / "sheet.json")}}

    def _assert_completed_release_gate(self, outputs):
        if self.fail_after == "gate":
            raise RuntimeError("completion verification failed")
        assert (self.db.settings.data_dir / "character_sheets" / "sheet.json").read_text() == "sheet"


def service_at(tmp_path, *, fail_after=None, after_stage=None, data_dir=None):
    service, run, _ = _finalization_service_and_run(owner_resolutions=False)
    settings = Settings.from_env(data_dir=data_dir or tmp_path / "live")
    settings = replace(settings, security_dir=settings.data_dir / "security",
                       factory_zip=None, fixture_path=None)
    db = Database(settings)
    with db.transaction() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS character_creation_runs
          (run_id TEXT PRIMARY KEY, owner_decision TEXT, commit_json TEXT,
           final_revision INTEGER, output_json TEXT, status TEXT,
           updated_at TEXT, completed_at TEXT)""")
        conn.execute("INSERT OR IGNORE INTO character_creation_runs(run_id,status) VALUES (?,?)",
                     (run["run_id"], run["status"]))
        conn.execute("CREATE TABLE IF NOT EXISTS owned(value TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS locations(path TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS preferences(value TEXT)")
        if not conn.execute("SELECT 1 FROM preferences").fetchone():
            conn.execute("INSERT INTO preferences VALUES ('MANUAL_CHAT')")
    service.db = db
    run["created_at"] = "2026-10-01T00:00:00Z"
    run["request"]["typed_choice_snapshot"] = {"snapshot_sha256": "snapshot"}
    service._approved_candidate_for_finalization = lambda *a: {
        "candidate_identity": "reviewed", "deterministic": True,
        "independent_compilations": 2, "identities": {"sheet": "wrong"} if fail_after == "identity" else {},
    }
    service.candidate_gm_authoring = SimpleNamespace(candidate_compilation_authority=lambda *a, **k: {})
    service._require_frozen_choice_snapshot = lambda *a: {}
    service._record_stage_timings = lambda *a: None
    service._latest_attempt_id = lambda *a: None

    def append(*a, **k):
        with db.transaction() as conn:
            conn.execute("INSERT INTO owned VALUES ('attempt')")
    service._append_attempt = append

    def get(run_id):
        result = deepcopy(run)
        with db.connection() as conn:
            row = conn.execute("SELECT * FROM character_creation_runs WHERE run_id=?", (run_id,)).fetchone()
        result["status"] = row["status"]
        result["commit"] = json.loads(row["commit_json"] or "{}")
        result["outputs"] = json.loads(row["output_json"] or "{}")
        return result
    service.get = get

    def pipeline(staged_db):
        if after_stage:
            after_stage(db)
        return Pipeline(staged_db, fail_after)
    service._publication_service = pipeline
    return service, run


def assert_no_stage(service):
    assert list(finalization.publication_root(service.db).glob("*/data")) == []


@pytest.mark.parametrize("failure", ["stage1", "identity", "gate"])
def test_unrelated_preference_and_files_survive_failed_finalize(tmp_path, failure):
    entered, committed = threading.Event(), threading.Event()

    def writer(db):
        entered.wait(10)
        with Database(db.settings).transaction() as conn:
            conn.execute("UPDATE preferences SET value='STANDARD_API'")
        (db.settings.data_dir / "other.json").write_text("unrelated")
        committed.set()

    def after_stage(db):
        entered.set()
        assert committed.wait(10)

    service, run = service_at(tmp_path, fail_after=failure, after_stage=after_stage)
    thread = threading.Thread(target=writer, args=(service.db,))
    thread.start()
    try:
        with pytest.raises(FoundryError, match="rolled back"):
            service.finalize(run["run_id"], fail_after="stage1")
    finally:
        thread.join(15)
    assert not thread.is_alive()
    with service.db.connection() as conn:
        assert conn.execute("SELECT value FROM preferences").fetchone()[0] == "STANDARD_API"
        assert conn.execute("SELECT * FROM owned").fetchall() == []
        assert conn.execute("SELECT * FROM locations").fetchall() == []
    assert (service.db.settings.data_dir / "other.json").read_text() == "unrelated"
    assert not (service.db.settings.data_dir / "projects" / "p.json").exists()
    assert_no_stage(service)


def test_committed_wal_survives_through_open_and_fresh_connections(tmp_path):
    service, run = service_at(tmp_path, fail_after="stage1")
    reader = service.db.connect()
    reader.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM preferences").fetchall()
    with service.db.connection() as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO preferences VALUES ('committed-in-wal')")
    wal = Path(str(service.db.settings.db_path) + "-wal")
    assert wal.stat().st_size > 0
    inode = service.db.settings.db_path.stat().st_ino
    try:
        with pytest.raises(FoundryError):
            service.finalize(run["run_id"], fail_after="stage1")
        reader.execute("COMMIT")
        for conn in (reader, service.db.connect()):
            try:
                assert conn.execute("SELECT value FROM preferences ORDER BY rowid").fetchall()[1][0] == "committed-in-wal"
                assert conn.execute("SELECT * FROM owned").fetchall() == []
            finally:
                if conn is not reader:
                    conn.close()
        assert service.db.settings.db_path.stat().st_ino == inode
    finally:
        reader.close()
    assert_no_stage(service)


def test_failed_finalize_retry_succeeds_and_second_finalize_is_idempotent(tmp_path):
    service, run = service_at(tmp_path, fail_after="stage1")
    with pytest.raises(FoundryError):
        service.finalize(run["run_id"], fail_after="stage1")
    service._publication_service = lambda db: Pipeline(db, None)
    first = service.finalize(run["run_id"])
    assert first["status"] == "CLEAN_AND_FINALIZED"
    assert service.finalize(run["run_id"]) == first
    with service.db.connection() as conn:
        assert [row[0] for row in conn.execute("SELECT * FROM owned")] == ["character", "attempt"]
        stored = Path(conn.execute("SELECT path FROM locations").fetchone()[0])
        assert stored == Path(first["outputs"]["sheet"]["path"])
        assert stored.read_text() == "sheet"
    assert Path(first["outputs"]["sheet"]["path"]).read_text() == "sheet"
    assert_no_stage(service)


def test_nested_transaction_failure_rolls_back_only_its_savepoint(tmp_path):
    service, _ = service_at(tmp_path)
    with service.db.transaction(atomic=True) as outer:
        outer.execute("INSERT INTO owned VALUES ('outer')")
        with pytest.raises(RuntimeError):
            with Database(service.db.settings).transaction() as nested:
                assert nested is outer
                nested.execute("INSERT INTO owned VALUES ('inner')")
                raise RuntimeError("inner failure")
        with service.db.connection() as reader:
            assert reader is outer
            assert [row[0] for row in reader.execute("SELECT * FROM owned")] == ["outer"]
    with service.db.connection() as reader:
        assert [row[0] for row in reader.execute("SELECT * FROM owned")] == ["outer"]
