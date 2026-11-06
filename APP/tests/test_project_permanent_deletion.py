"""DELETE1 integration probes use migrated scratch databases only."""
from __future__ import annotations

import hashlib
import asyncio
import json
import os
import sqlite3
import zipfile
from dataclasses import replace
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api import create_app
from app.core import FoundryError, Settings
from character_library_archive import CharacterLibraryArchiveService
from project_store.permanent_deletion import PermanentProjectDeletion, PROJECT_FOLDERS, PROJECT_FILES, RUN_FOLDERS, RUN_ID_FOLDERS
from project_store.service import ProjectStore

ROOT = Path(__file__).resolve().parents[1]


def insert(conn, table, **values):
    """Fill non-null metadata for a small production-schema storage probe."""
    for column in conn.execute(f'PRAGMA table_info("{table}")'):
        if column["name"] not in values and column["notnull"] and column["dflt_value"] is None:
            values[column["name"]] = 1 if column["type"] == "INTEGER" else "probe"
    conn.execute(f'INSERT INTO "{table}"({",".join(values)}) VALUES({",".join("?" for _ in values)})', list(values.values()))


def seed(db, pid="00000000-0000-4000-8000-000000000001", state="temporary", run_status="CANCELLED"):
    CharacterLibraryArchiveService(db)
    run_id = f"cg1.run.{pid}"
    with db.transaction() as conn:
        insert(conn, "projects", project_id=pid, working_name=f"Character {pid}", status="draft", project_json="{}")
        ProjectStore._set_builder_lifecycle(conn, pid, state, source="delete1_test")
        insert(conn, "character_creation_runs", run_id=run_id, project_id=pid,
               execution_mode="MANUAL_CHAT", status=run_status, request_json="{}")
        insert(conn, "character_creation_attempt_history", attempt_id=f"attempt-{pid}", run_id=run_id,
               project_id=pid, action_type="CANCEL_BUILD", status="CANCELLED", response_bytes=b"\x00\xffattempt")
        insert(conn, "dcc_controller_run_bindings", run_id=run_id, project_id=pid,
               route_mode="DETERMINISTIC_CREATIVE_CONTROLLER", binding_json="{}", binding_sha256="a" * 64,
               request_sha256="b" * 64, state="INACTIVE")
        insert(conn, "dcc_walk_state", run_id=run_id, committed_sha256="c" * 64, event_head_sha256="d" * 64)
        insert(conn, "events", project_id=pid, sequence_no=1, event_id=f"event-{pid}", event_json="{}")
        insert(conn, "snapshots", project_id=pid, sequence_no=1, state_json="{}")
        insert(conn, "event_hash_mappings", project_id=pid, old_event_hash=f"legacy-{pid}", new_event_hash=f"canonical-{pid}")
        insert(conn, "stage2_proposals", project_id=pid, proposal_id=f"proposal-{pid}", status="committed", proposal_json="{}")
        insert(conn, "stage2_commit_attempts", project_id=pid, proposal_id=f"proposal-{pid}", attempt_id=f"stage2-{pid}",
               status="committed", retryable=0)
        insert(conn, "projection_runs", project_id=pid, projection_id=f"projection-{pid}", generated_dir=f"projects/{pid}/projection")
        insert(conn, "projection_artifacts", projection_id=f"projection-{pid}", artifact_name="sheet", path=f"projects/{pid}/projection/sheet", bytes=4)
    root = db.settings.data_dir
    for folder in PROJECT_FOLDERS:
        directory = root / folder / pid
        directory.mkdir(parents=True)
        (directory / "data.bin").write_bytes(b"\x00\xff" + pid.encode())
        (directory / "empty").mkdir()
    for folder in PROJECT_FILES:
        (root / folder).mkdir(exist_ok=True)
        (root / folder / f"{pid}.json").write_text(json.dumps({"owner": pid}))
    digest = hashlib.sha256(run_id.encode()).hexdigest()
    for folder, length in RUN_FOLDERS.items():
        directory = root / folder / digest[:length]
        directory.mkdir(parents=True)
        (directory / "run.json").write_text(json.dumps({"project_id": pid}))
    for folder in RUN_ID_FOLDERS:
        directory = root / folder / run_id
        directory.mkdir(parents=True)
        (directory / "data.json").write_text("{}")
    diagnostic = root / "diagnostics/character_creation" / f"{digest[:32]}.jsonl"
    diagnostic.parent.mkdir(parents=True, exist_ok=True)
    diagnostic.write_text("{}\n")
    review_name = "final-review." + hashlib.sha256(pid.encode()).hexdigest()
    review = root / "factory_final_character/reviews" / f"{review_name}.json"
    review.parent.mkdir(exist_ok=True)
    review.write_text(json.dumps({"record_id": review_name, "binding": {"project_id": pid}}))
    return ProjectStore(db)


def project_state(db, pid):
    service = PermanentProjectDeletion(db)
    with db.connection() as conn:
        _, rows = service.snapshot(conn, pid)
    normalized = {t: [{k: v for k, v in r.items() if k != "__rowid__"} for r in rs] for t, rs in rows.items()}
    paths = service.paths(pid, rows)
    return normalized, service.tree(paths)


def everything_else(db, pid):
    """Hash all unrelated rows and file bytes, including shared metadata."""
    service = PermanentProjectDeletion(db)
    with db.connection() as conn:
        schema, owned = service.snapshot(conn, pid)
        rows = {}
        for table in schema:
            ids = {r["__rowid__"] for r in owned.get(table, [])}
            try:
                rows[table] = [tuple(r) for r in conn.execute(f'SELECT rowid,* FROM "{table}" ORDER BY rowid') if r[0] not in ids]
            except sqlite3.OperationalError:
                assert not ids, "Project-owned tables must have row identities"
                rows[table] = sorted(tuple(r) for r in conn.execute(f'SELECT * FROM "{table}"'))
    paths = service.paths(pid, owned)
    files = {}
    for path in sorted(db.settings.data_dir.rglob("*")):
        relative = path.relative_to(db.settings.data_dir).as_posix()
        if (relative.startswith("backups/") or relative.startswith("foundry.sqlite3")
                or any(relative == p or relative.startswith(p + "/") for p in paths)):
            continue
        if path.is_file():
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(repr((rows, files)).encode()).hexdigest()


def test_delete_attempt_history_backup_restore_and_other_projects_identical(fresh_db):
    db = fresh_db
    store = seed(db)
    seed(db, "00000000-0000-4000-8000-000000000002", "saved_draft")
    (db.settings.data_dir / "shared-private.bin").write_bytes(b"owner data")
    before = project_state(db, "00000000-0000-4000-8000-000000000001")
    others = everything_else(db, "00000000-0000-4000-8000-000000000001")
    result = store.delete_project_permanently("00000000-0000-4000-8000-000000000001")
    assert result["deleted"] and result["cleanup_pending"] is None
    backup = db.settings.data_dir / result["backup"]
    assert backup.parent == db.settings.data_dir / "backups/deleted-characters"
    assert project_state(db, "00000000-0000-4000-8000-000000000001")[0] == {}
    assert everything_else(db, "00000000-0000-4000-8000-000000000001") == others
    with zipfile.ZipFile(backup) as archive:
        assert archive.testzip() is None
        assert "character_creation_attempt_history" in json.loads(archive.read("manifest.json"))["rows"]
    assert store.restore_project_permanently(backup) == {"project_id": "00000000-0000-4000-8000-000000000001", "restored": True}
    assert project_state(db, "00000000-0000-4000-8000-000000000001") == before
    assert everything_else(db, "00000000-0000-4000-8000-000000000001") == others
    with pytest.raises(FoundryError):
        store.restore_project_permanently(backup)


def test_restore_preserves_library_revision_and_future_trigger_updates(fresh_db):
    pid = "00000000-0000-4000-8000-000000000001"
    store = seed(fresh_db)
    with fresh_db.transaction() as conn:
        conn.execute("UPDATE project_library_source_revision SET revision=37 WHERE project_id=?", (pid,))
    before = project_state(fresh_db, pid)
    result = store.delete_project_permanently(pid)
    store.restore_project_permanently(fresh_db.settings.data_dir / result["backup"])
    assert project_state(fresh_db, pid) == before
    with fresh_db.transaction() as conn:
        conn.execute("UPDATE projects SET project_id=project_id WHERE project_id=?", (pid,))
        assert conn.execute("SELECT revision FROM project_library_source_revision WHERE project_id=?", (pid,)).fetchone()[0] == 38


@pytest.mark.parametrize("state,status,archived,allowed", [
    ("saved_draft", "CANCELLED", False, True),
    ("completed", "CLEAN_AND_FINALIZED", False, False),
    ("temporary", "CLEAN_AND_FINALIZED", False, False),
    ("completed", "CLEAN_AND_FINALIZED", True, True),
    ("saved_draft", "WAITING_FOR_RESPONSE", False, False),
    ("saved_draft", "NEEDS_REVIEW", True, False),
    ("saved_draft", "UNKNOWN_FUTURE_STATUS", True, False),
])
def test_eligibility(fresh_db, state, status, archived, allowed):
    store = seed(fresh_db, state=state, run_status=status)
    if archived:
        CharacterLibraryArchiveService(fresh_db).archive("00000000-0000-4000-8000-000000000001")
    before = project_state(fresh_db, "00000000-0000-4000-8000-000000000001")
    if allowed:
        store.delete_project_permanently("00000000-0000-4000-8000-000000000001")
    else:
        with pytest.raises(FoundryError):
            store.delete_project_permanently("00000000-0000-4000-8000-000000000001")
        assert project_state(fresh_db, "00000000-0000-4000-8000-000000000001") == before
        assert not (fresh_db.settings.data_dir / "backups/deleted-characters").exists()


def test_active_project_requires_archive(fresh_db):
    store = seed(fresh_db, state="saved_draft")
    with fresh_db.transaction() as conn:
        conn.execute("UPDATE projects SET status='active' WHERE project_id='00000000-0000-4000-8000-000000000001'")
    with pytest.raises(FoundryError):
        store.delete_project_permanently("00000000-0000-4000-8000-000000000001")


@pytest.mark.parametrize("pid", ["", ".", "..", "../keep", "/", "a/b", "a\\b", "a.b", "x\x00", "ü", "a" * 129, "reviews"])
def test_odd_ids_refused(fresh_db, pid):
    store = seed(fresh_db)
    before = everything_else(fresh_db, "none")
    with pytest.raises(FoundryError):
        store.delete_project_permanently(pid)
    assert everything_else(fresh_db, "none") == before


@pytest.mark.parametrize("location", ["folder", "nested", "backup"])
def test_symlinks_refused_without_touching_target(fresh_db, tmp_path, location):
    store = seed(fresh_db)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "00000000-0000-4000-8000-000000000002").write_bytes(b"untouched")
    if location == "folder":
        target = fresh_db.settings.data_dir / "workspaces/00000000-0000-4000-8000-000000000001/empty"
        target.rmdir()
        target.symlink_to(outside, target_is_directory=True)
    elif location == "nested":
        (fresh_db.settings.data_dir / "projects/00000000-0000-4000-8000-000000000001/link").symlink_to(outside, target_is_directory=True)
    else:
        (fresh_db.settings.data_dir / "backups/deleted-characters").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FoundryError):
        store.delete_project_permanently("00000000-0000-4000-8000-000000000001")
    assert (outside / "00000000-0000-4000-8000-000000000002").read_bytes() == b"untouched"
    with fresh_db.connection() as conn:
        assert conn.execute("SELECT 1 FROM projects WHERE project_id='00000000-0000-4000-8000-000000000001'").fetchone()


def test_database_failure_restores_only_quarantined_paths(fresh_db):
    store = seed(fresh_db)
    seed(fresh_db, "00000000-0000-4000-8000-000000000002")
    before = project_state(fresh_db, "00000000-0000-4000-8000-000000000001")
    others = everything_else(fresh_db, "00000000-0000-4000-8000-000000000001")
    with fresh_db.transaction() as conn:
        conn.execute("CREATE TRIGGER forced_delete_failure BEFORE DELETE ON projects BEGIN SELECT RAISE(ABORT,'forced'); END")
    with pytest.raises(sqlite3.IntegrityError, match="forced"):
        store.delete_project_permanently("00000000-0000-4000-8000-000000000001")
    assert project_state(fresh_db, "00000000-0000-4000-8000-000000000001") == before
    assert everything_else(fresh_db, "00000000-0000-4000-8000-000000000001") == others
    with fresh_db.connection() as conn:
        assert not conn.execute("SELECT * FROM project_permanent_delete_authorizations").fetchall()
    assert len(list((fresh_db.settings.data_dir / "backups/deleted-characters").iterdir())) == 1


def test_corrupt_backup_refused_before_delete(fresh_db, monkeypatch):
    store = seed(fresh_db)
    before = project_state(fresh_db, "00000000-0000-4000-8000-000000000001")
    def fail(*args):
        raise FoundryError("TEST_BAD_ZIP", "forced bad zip")
    monkeypatch.setattr(PermanentProjectDeletion, "read_backup", fail)
    with pytest.raises(FoundryError, match="forced bad zip"):
        store.delete_project_permanently("00000000-0000-4000-8000-000000000001")
    assert project_state(fresh_db, "00000000-0000-4000-8000-000000000001") == before


def test_append_only_protection_still_applies(fresh_db):
    seed(fresh_db)
    for table in ("character_creation_attempt_history", "dcc_controller_run_bindings", "projects", "stage2_commit_attempts"):
        with pytest.raises(sqlite3.IntegrityError):
            with fresh_db.transaction() as conn:
                conn.execute(f'DELETE FROM "{table}"')


def test_cross_project_link_without_project_column_is_refused(fresh_db):
    store = seed(fresh_db)
    other = "00000000-0000-4000-8000-000000000002"
    seed(fresh_db, other)
    with fresh_db.transaction() as conn:
        conn.execute("CREATE TABLE cross_project_link(link_id TEXT PRIMARY KEY, left_run TEXT REFERENCES dcc_controller_run_bindings(run_id), right_run TEXT REFERENCES dcc_controller_run_bindings(run_id))")
        conn.execute("INSERT INTO cross_project_link VALUES(?,?,?)", ("link", "cg1.run.00000000-0000-4000-8000-000000000001", f"cg1.run.{other}"))
    with pytest.raises(FoundryError, match="another project"):
        store.delete_project_permanently("00000000-0000-4000-8000-000000000001")
    with fresh_db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM projects").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM cross_project_link").fetchone()[0] == 1


@pytest.mark.parametrize("other_binding", [False, True])
def test_approval_evidence_json_binding_protects_other_projects(fresh_db, other_binding):
    store = seed(fresh_db)
    pid = "00000000-0000-4000-8000-000000000001"
    other = "00000000-0000-4000-8000-000000000002"
    seed(fresh_db, other)
    with fresh_db.transaction() as conn:
        insert(conn, "exact_approval_challenges", challenge_id="delete1-challenge",
               subject_type="stage2_proposal", subject_id=f"proposal-{pid}",
               status="consumed", challenge_json="{}")
        insert(conn, "exact_approval_evidence", evidence_id="delete1-evidence",
               challenge_id="delete1-challenge", subject_type="stage2_proposal",
               subject_id=f"proposal-{pid}", evidence_json=json.dumps({
                   "approval_context": {"project_id": other if other_binding else pid},
               }))
    service = PermanentProjectDeletion(fresh_db)
    if other_binding:
        # Capture every row/file without using the ownership walk under test.
        with fresh_db.connection() as conn:
            before_rows = list(conn.iterdump())
        before_files = service.tree([f"{folder}/{project}" for folder in PROJECT_FOLDERS for project in (pid, other)])
        with pytest.raises(FoundryError, match="another project"):
            store.delete_project_permanently(pid)
        with fresh_db.connection() as conn:
            assert list(conn.iterdump()) == before_rows
        assert service.tree([f"{folder}/{project}" for folder in PROJECT_FOLDERS for project in (pid, other)]) == before_files
        assert not (fresh_db.settings.data_dir / "backups/deleted-characters").exists()
    else:
        before = project_state(fresh_db, pid)
        others = everything_else(fresh_db, pid)
        result = store.delete_project_permanently(pid)
        assert everything_else(fresh_db, pid) == others
        backup = fresh_db.settings.data_dir / result["backup"]
        # Restore uses the same ownership rules, even for an edited archive.
        with zipfile.ZipFile(backup) as source:
            members = {name: source.read(name) for name in source.namelist()}
        manifest = json.loads(members["manifest.json"])
        manifest["rows"]["exact_approval_evidence"][0]["evidence_json"] = json.dumps({
            "approval_context": {"project_id": other},
        })
        members["manifest.json"] = json.dumps(manifest).encode()
        conflicting = backup.parent / "conflicting-approval.zip"
        with zipfile.ZipFile(conflicting, "w") as target:
            for name, content in members.items():
                target.writestr(name, content)
        with pytest.raises(FoundryError, match="another project"):
            store.restore_project_permanently(conflicting)
        assert project_state(fresh_db, pid)[0] == {}
        assert not (fresh_db.settings.data_dir / "projects" / pid).exists()
        assert everything_else(fresh_db, pid) == others
        store.restore_project_permanently(backup)
        assert project_state(fresh_db, pid) == before
        assert everything_else(fresh_db, pid) == others


def test_restore_commit_failure_removes_only_its_published_files(fresh_db, monkeypatch):
    store = seed(fresh_db)
    pid = "00000000-0000-4000-8000-000000000001"
    seed(fresh_db, "00000000-0000-4000-8000-000000000002")
    result = store.delete_project_permanently(pid)
    others = everything_else(fresh_db, pid)
    original = fresh_db.transaction
    @contextmanager
    def fail_commit():
        with original() as conn:
            yield conn
            raise FoundryError("FORCED_RESTORE_FAILURE", "forced restore commit failure")
    monkeypatch.setattr(fresh_db, "transaction", fail_commit)
    with pytest.raises(FoundryError, match="forced restore"):
        store.restore_project_permanently(fresh_db.settings.data_dir / result["backup"])
    assert project_state(fresh_db, pid)[0] == {}
    assert everything_else(fresh_db, pid) == others
    assert not (fresh_db.settings.data_dir / "projects" / pid).exists()
    assert len(list((fresh_db.settings.data_dir / "backups/deleted-characters").iterdir())) == 1


def test_read_only_project_files_round_trip(fresh_db):
    store = seed(fresh_db)
    pid = "00000000-0000-4000-8000-000000000001"
    directory = fresh_db.settings.data_dir / "projects" / pid
    (directory / "data.bin").chmod(0o400)
    directory.chmod(0o500)
    before = project_state(fresh_db, pid)
    result = store.delete_project_permanently(pid)
    store.restore_project_permanently(fresh_db.settings.data_dir / result["backup"])
    assert project_state(fresh_db, pid) == before
    directory.chmod(0o700)


def test_restore_refuses_backup_path_and_manifest_traversal(fresh_db):
    store = seed(fresh_db)
    pid = "00000000-0000-4000-8000-000000000001"
    result = store.delete_project_permanently(pid)
    backup = fresh_db.settings.data_dir / result["backup"]
    with pytest.raises(FoundryError):
        store.restore_project_permanently(fresh_db.settings.data_dir / "../outside.zip")
    with zipfile.ZipFile(backup) as source:
        members = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(members["manifest.json"])
    manifest["roots"].append("../outside")
    members["manifest.json"] = json.dumps(manifest).encode()
    bad = backup.parent / "bad.zip"
    with zipfile.ZipFile(bad, "w") as target:
        for name, content in members.items():
            target.writestr(name, content)
    with pytest.raises(FoundryError):
        store.restore_project_permanently(bad)
    assert project_state(fresh_db, pid)[0] == {}


def test_wrong_database_root_refused(fresh_db):
    seed(fresh_db)
    fresh_db.settings = replace(fresh_db.settings, db_path=fresh_db.settings.data_dir.parent / "wrong.sqlite3")
    with pytest.raises(FoundryError, match="exact data root"):
        PermanentProjectDeletion(fresh_db)


@pytest.mark.skipif(os.getenv("DELETE1_HTTP_TESTS") != "1", reason="Opt-in HTTP transport check; lead runs outside sandbox (TestClient portal stalls here).")
def test_http_api_requires_token_and_matching_confirmation(tmp_path):
    app = create_app(settings=Settings.from_env(ROOT, tmp_path / "api-data"))
    seed(app.state.projects.db, state="saved_draft")
    client = TestClient(app)
    route = "/api/character-library/00000000-0000-4000-8000-000000000001/delete-permanently"
    assert client.post(route, json={"confirm_project_id": "00000000-0000-4000-8000-000000000001"}).status_code == 403
    headers = {"X-Foundry-Token": client.get("/api/session").json()["token"]}
    assert client.post(route, headers=headers, json={"confirm_project_id": "00000000-0000-4000-8000-000000000002"}).status_code == 400
    assert client.post(route, headers=headers, json={}).status_code == 400
    response = client.post(route, headers=headers, json={"confirm_project_id": "00000000-0000-4000-8000-000000000001"})
    assert response.status_code == 200, response.text
    assert response.json()["queued"] is True
    client.close()


def test_api_middleware_token_and_route_confirmation(tmp_path):
    """Exercise the actual token gate and route without a cross-thread portal."""
    app = create_app(settings=Settings.from_env(ROOT, tmp_path / "api-data"))
    seed(app.state.projects.db, state="saved_draft")
    pid = "00000000-0000-4000-8000-000000000001"
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/character-library/{project_id}/delete-permanently")
    gate = next(middleware.kwargs["dispatch"] for middleware in app.user_middleware if middleware.kwargs.get("dispatch", lambda: None).__name__ == "loopback_security")
    async def request(token, body):
        scope = {"type": "http", "method": "POST", "path": f"/api/character-library/{pid}/delete-permanently", "headers": [(b"host", b"testserver")], "query_string": b""}
        if token:
            scope["headers"].append((b"x-foundry-token", token.encode()))
        async def downstream(_request):
            try:
                return JSONResponse(endpoint(pid, body))
            except FoundryError as error:
                return JSONResponse(error.to_dict(), status_code=error.status_code)
        return await gate(Request(scope), downstream)
    assert asyncio.run(request(None, {"confirm_project_id": pid})).status_code == 403
    assert asyncio.run(request("wrong-token", {"confirm_project_id": pid})).status_code == 403
    assert asyncio.run(request(app.state.session_token, {})).status_code == 400
    assert asyncio.run(request(app.state.session_token, {"confirm_project_id": "different"})).status_code == 400
    response = asyncio.run(request(app.state.session_token, {"confirm_project_id": pid}))
    assert response.status_code == 200
    assert json.loads(response.body)["queued"] is True
    with app.state.db.connection() as conn:
        request = conn.execute("SELECT * FROM project_deletion_requests WHERE project_id=?", (pid,)).fetchone()
        assert request["requested_by"] == app.state.principal.principal_id
        assert request["confirmation"] == pid
        assert request["requested_at"]
        assert conn.execute("SELECT 1 FROM projects WHERE project_id=?", (pid,)).fetchone()
