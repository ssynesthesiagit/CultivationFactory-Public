"""DELETE2 startup probes: migrated scratch databases; no GUI or live services."""
import json
import copy
import hashlib
import time
from pathlib import Path

import pytest

from app.api import create_app
from app.core import FoundryError, Settings
from project_store.deletion_queue import ProjectDeletionQueue, hidden_project_ids, project_matches
from project_store.permanent_deletion import PermanentProjectDeletion
from project_store.service import ProjectStore
from character_library_archive import CharacterLibraryArchiveService
from tests.test_project_permanent_deletion import seed, project_state, insert

ROOT = Path(__file__).resolve().parents[1]
PID = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
THIRD = "00000000-0000-4000-8000-000000000003"


@pytest.fixture(scope="module")
def persisted_bindings(tmp_path_factory):
    """Real saved MatchLock/Genesis documents, without loading or replaying."""
    from combat.gate3_storage import Gate3Persistence
    session = Gate3Persistence(ROOT, tmp_path_factory.mktemp("delete2-bindings")).create_match(
        match_seed="DELETE2-BINDINGS", maximum_rounds=2)
    return {name: json.loads((session.store.match_dir / name).read_text())
            for name in ("MatchLock.json", "GenesisState.json")}


def write_bindings(match, persisted_bindings, actor_id="actor:factory." + PID):
    docs = copy.deepcopy(persisted_bindings)
    docs["MatchLock.json"]["match_id"] = "scratch-fight"
    old = docs["MatchLock.json"]["actor_ids"][0]
    docs["MatchLock.json"]["actor_ids"][0] = actor_id
    genesis = docs["GenesisState.json"]
    genesis["match_id"] = genesis["state"]["match_id"] = "scratch-fight"
    actor = genesis["state"]["actors"].pop(old)
    actor["entity_id"] = actor_id
    genesis["state"]["actors"][actor_id] = actor
    for name, doc in docs.items():
        (match / name).write_text(json.dumps(doc))
    return docs


def capture_preserved(db):
    """Independent DELETE1 oracle: capture before the target exists.

    Never consult deletion's ownership walk or ownership path constants.
    """
    with db.connection() as conn:
        rows = {table: [tuple(r) for r in conn.execute(f'SELECT * FROM "{table}"')]
                for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    files = {p.relative_to(db.settings.data_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in db.settings.data_dir.rglob("*") if p.is_file()
             and not p.name.startswith("foundry.sqlite3")}
    return rows, files


def assert_preserved(db, expected):
    rows, files = expected
    with db.connection() as conn:
        for table, before in rows.items():
            after = [tuple(r) for r in conn.execute(f'SELECT * FROM "{table}"')]
            for row in before:
                assert after.count(row) == before.count(row), table
    for relative, digest in files.items():
        assert hashlib.sha256((db.settings.data_dir / relative).read_bytes()).hexdigest() == digest, relative


def request(db, pid=PID):
    return ProjectDeletionQueue(db).request(pid, requested_by="scratch-owner", confirmation=pid)


def failure_reason(db):
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM project_deletion_requests WHERE project_id=?", (PID,)).fetchone()
        assert row["status"] == "failed"
        return row["reason"]


def test_request_undo_hide_is_durable_and_idempotent(fresh_db):
    store = seed(fresh_db, state="saved_draft")
    seed(fresh_db, OTHER, state="saved_draft")
    before = project_state(fresh_db, PID)
    queue = ProjectDeletionQueue(fresh_db)
    with pytest.raises(FoundryError, match="Confirm"):
        queue.request(PID, requested_by="owner", confirmation=OTHER)
    assert request(fresh_db)["queued"]
    assert project_state(fresh_db, PID) == before
    assert hidden_project_ids(fresh_db) == {PID}
    assert [row["project_id"] for row in store.list_projects()] == [OTHER]
    with fresh_db.connection() as conn:
        original = tuple(conn.execute("SELECT * FROM project_deletion_requests").fetchone())
    request(fresh_db)
    with fresh_db.connection() as conn:
        assert tuple(conn.execute("SELECT * FROM project_deletion_requests").fetchone()) == original
    assert queue.hidden_cards()[0]["working_name"] == f"Character {PID}"
    assert ProjectDeletionQueue(fresh_db).undo(PID)["changed"]
    assert not queue.undo(PID)["changed"]
    assert not hidden_project_ids(fresh_db)
    assert {row["project_id"] for row in store.list_projects()} == {PID, OTHER}
    assert not list(fresh_db.settings.data_dir.glob("backups/deleted-characters/*.zip"))


def test_startup_deletes_exact_project_independent_oracle_and_restore(fresh_db):
    seed(fresh_db, OTHER, "saved_draft")
    seed(fresh_db, THIRD, "saved_draft")
    for relative in ("security/test-key", "vendor/test-vendor.bin", "shared-private.bin", "Combat/shared.bin"):
        path = fresh_db.settings.data_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"scratch preservation " + relative.encode())
    preserved = capture_preserved(fresh_db)
    store = seed(fresh_db, state="saved_draft")
    before = project_state(fresh_db, PID)
    request(fresh_db)
    # The real application startup processes before constructing services/cache
    # warmers. Retained projects are saved drafts so startup cleanup is inert.
    app = create_app(settings=fresh_db.settings)
    result = app.state.startup_deletions[0]
    assert result["status"] == "deleted" and result["cleanup_pending"] is None
    assert project_state(fresh_db, PID)[0] == {}
    assert PID in hidden_project_ids(fresh_db)  # retained fights stay hidden
    assert_preserved(fresh_db, preserved)
    store.restore_project_permanently(fresh_db.settings.data_dir / result["backup"])
    assert project_state(fresh_db, PID) == before
    assert PID not in hidden_project_ids(fresh_db)
    assert_preserved(fresh_db, preserved)


@pytest.mark.parametrize("stage", ["after_quarantine", "after_rows"])
def test_midway_failure_restores_and_keeps_failed_card(fresh_db, monkeypatch, stage):
    seed(fresh_db, OTHER, "saved_draft")
    preserved = capture_preserved(fresh_db)
    seed(fresh_db)
    before = project_state(fresh_db, PID)
    request(fresh_db)
    original = PermanentProjectDeletion.delete_rows
    def fail(self, conn, schema, rows):
        if stage == "after_rows":
            original(self, conn, schema, rows)
        raise OSError("scratch injected failure")
    monkeypatch.setattr(PermanentProjectDeletion, "delete_rows", fail)
    queue = ProjectDeletionQueue(fresh_db)
    assert queue.process_at_startup()[0]["status"] == "failed"
    assert project_state(fresh_db, PID) == before
    assert_preserved(fresh_db, preserved)
    assert "scratch" not in failure_reason(fresh_db)
    # Neither ordinary shutdown nor startup cleanup may erase this card.
    store = ProjectStore(fresh_db)
    store.cleanup_temporary_projects(reason="scratch startup")
    assert queue.hidden_cards()[0]["deletion_status"] == "failed"
    assert project_state(fresh_db, PID) == before
    assert not queue.process_at_startup()  # failure is not silently retried
    assert queue.undo(PID)["changed"]


def test_quarantined_bytes_are_verified_and_newer_bytes_restored(fresh_db, monkeypatch):
    seed(fresh_db, state="saved_draft")
    request(fresh_db)
    original = PermanentProjectDeletion.move_owned
    target_file = fresh_db.settings.data_dir / "projects" / PID / "data.bin"
    def move(source, target):
        if source == target_file.parent:
            target_file.write_bytes(b"newer bytes after verification")
        original(source, target)
    monkeypatch.setattr(PermanentProjectDeletion, "move_owned", staticmethod(move))
    assert ProjectDeletionQueue(fresh_db).process_at_startup()[0]["status"] == "failed"
    assert target_file.read_bytes() == b"newer bytes after verification"
    assert "files changed" in failure_reason(fresh_db)
    with fresh_db.connection() as conn:
        assert conn.execute("SELECT 1 FROM projects WHERE project_id=?", (PID,)).fetchone()


def test_postcommit_cleanup_error_restores_from_verified_backup(fresh_db, monkeypatch):
    seed(fresh_db, state="saved_draft")
    before = project_state(fresh_db, PID)
    request(fresh_db)
    original = PermanentProjectDeletion.remove_stage
    def fail(stage):
        if stage.name.startswith(".delete-"):
            # A partially cleaned quarantine cannot be the restoration source.
            file = next(stage.rglob("data.bin"))
            file.unlink()
            raise OSError("scratch partial cleanup")
        original(stage)
    monkeypatch.setattr(PermanentProjectDeletion, "remove_stage", staticmethod(fail))
    result = ProjectDeletionQueue(fresh_db).process_at_startup()[0]
    assert result["status"] == "failed"
    assert project_state(fresh_db, PID) == before
    assert "restored" in failure_reason(fresh_db)


@pytest.mark.parametrize("status", ["WAITING_FOR_RESPONSE", "NEEDS_REVIEW", "UNKNOWN_FUTURE_STATUS"])
def test_unfinished_run_refused_at_startup_and_shown(fresh_db, status):
    seed(fresh_db, state="saved_draft", run_status=status)
    before = project_state(fresh_db, PID)
    request(fresh_db)
    app = create_app(settings=fresh_db.settings)
    assert app.state.startup_deletions[0]["status"] == "failed"
    assert "Cancel or finish" in failure_reason(fresh_db)
    assert project_state(fresh_db, PID) == before
    assert app.state.project_deletion_queue.hidden_cards()[0]["deletion_reason"]


@pytest.mark.parametrize("binding", ["factory_team", "factory_opponent", "portable"])
@pytest.mark.parametrize("complete", [False, True])
def test_fight_bindings_block_unfinished_and_preserve_finished(fresh_db, binding, complete, persisted_bindings, monkeypatch, tmp_path):
    seed(fresh_db, state="saved_draft")
    match = fresh_db.settings.data_dir / "Combat/Matches/scratch-fight"
    match.mkdir(parents=True)
    docs = write_bindings(match, persisted_bindings)
    if binding == "portable":
        from tests.test_c3d_p1_portable_live_combat import _import_runtime, RUNTIME_PACKAGE
        from combat.gate5_service import CombatService
        from combat.portable_runtime_authority import build_runtime_authority, runtime_actor_id
        from combat.canonical import canonical_sha256
        _import_runtime(monkeypatch, fresh_db, tmp_path)
        entry = CombatService(ROOT, fresh_db.settings.data_dir).combatant_library.inventory().accepted_candidates[0]
        data = build_runtime_authority(entry, RUNTIME_PACKAGE, qi_current=0, martial_focus_current=0,
                                       provenance_id="delete2-test").model_dump(mode="json", by_alias=True)
        data["project_id"] = PID
        data["runtime_actor_id"] = runtime_actor_id(PID, data["package_sha256"])
        data.pop("authority_sha256")
        data["authority_sha256"] = canonical_sha256(data)
        write_bindings(match, persisted_bindings, data["runtime_actor_id"])
        name = "PortableRuntimeAuthority.json"
    elif binding == "factory_opponent":
        name, data = "FactoryIntegration.json", {"factory_match": {"project_ids": [OTHER], "opponent_actor_ids": ["actor:factory." + PID]}}
        # Real factory opponents are also recorded in MatchLock/Genesis.
        actor = docs["GenesisState.json"]["state"]["actors"].pop(docs["MatchLock.json"]["actor_ids"][1])
        docs["MatchLock.json"]["actor_ids"][1] = "actor:factory." + OTHER
        actor["entity_id"] = "actor:factory." + OTHER
        docs["GenesisState.json"]["state"]["actors"][actor["entity_id"]] = actor
        for filename, doc in docs.items():
            (match / filename).write_text(json.dumps(doc))
    else:
        name, data = "FactoryIntegration.json", {"factory_match": {"project_ids": [PID]}}
    if name == "FactoryIntegration.json":
        data.update(schema="TianxiaFactoryCombatIntegration.v1", match_id="scratch-fight",
                    participant_control_modes={a: "MANUAL" for a in docs["MatchLock.json"]["actor_ids"]})
    (match / name).write_text(json.dumps(data))
    (match / "Manifest.json").write_text(json.dumps({"status": "COMPLETE" if complete else "ACTIVE"}))
    preserved = capture_preserved(fresh_db)
    request(fresh_db)
    result = ProjectDeletionQueue(fresh_db).process_at_startup()[0]
    assert result["status"] == ("deleted" if complete else "failed")
    assert project_matches(fresh_db, {PID})[PID] == [("scratch-fight", complete)]
    for relative, digest in preserved[1].items():
        if relative.startswith("Combat/"):
            assert hashlib.sha256((fresh_db.settings.data_dir / relative).read_bytes()).hexdigest() == digest
    if not complete:
        assert "Finish" in failure_reason(fresh_db)


def test_empty_queue_fast_noop_without_filesystem_or_ownership(fresh_db, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("An empty queue must not inspect project files")
    monkeypatch.setattr(PermanentProjectDeletion, "__init__", forbidden)
    before = capture_preserved(fresh_db)
    start = time.perf_counter()
    assert ProjectDeletionQueue(fresh_db).process_at_startup() == []
    assert project_matches(fresh_db, set()) == {}
    assert time.perf_counter() - start < 1
    assert_preserved(fresh_db, before)


@pytest.mark.parametrize("failure", ["quarantine_rollback", "zip_restore"])
def test_incomplete_recovery_halts_every_application_startup(fresh_db, monkeypatch, failure, caplog):
    from project_store.deletion_recovery import recover
    import app.api as api
    seed(fresh_db, OTHER, "saved_draft")
    preserved = capture_preserved(fresh_db)
    seed(fresh_db, state="saved_draft")
    before = project_state(fresh_db, PID)
    request(fresh_db)
    with monkeypatch.context() as faults:
        def no_services(*args, **kwargs):
            pytest.fail("Services must never be constructed over an incomplete data root")
        faults.setattr(api, "CatalogService", no_services)
        if failure == "quarantine_rollback":
            original_move = PermanentProjectDeletion.move_owned
            moves = []
            def fail_move(source, target):
                if source.parent.name.startswith(".delete-"):
                    raise OSError("scratch reverse move failure")
                original_move(source, target)
                moves.append((source, target))
            def fail_rows(*args):
                assert moves
                raise OSError("scratch database failure")
            faults.setattr(PermanentProjectDeletion, "move_owned", staticmethod(fail_move))
            faults.setattr(PermanentProjectDeletion, "delete_rows", fail_rows)
        else:
            def cleanup(stage):
                next(stage.rglob("data.bin")).unlink()
                raise OSError("scratch cleanup failure")
            def restore(*args):
                raise OSError("scratch restore failure")
            faults.setattr(PermanentProjectDeletion, "remove_stage", staticmethod(cleanup))
            faults.setattr(PermanentProjectDeletion, "restore", restore)
        for attempt in range(2):
            with pytest.raises(RuntimeError, match="Factory startup stopped") as error:
                create_app(settings=fresh_db.settings)
            with fresh_db.connection() as conn:
                row = dict(conn.execute("SELECT * FROM project_deletion_requests WHERE project_id=?", (PID,)).fetchone())
                assert row["recovery_required"] == 1 and row["status"] == "failed"
                exists = conn.execute("SELECT 1 FROM projects WHERE project_id=?", (PID,)).fetchone()
                assert bool(exists) == (failure == "quarantine_rollback")
            assert str(fresh_db.settings.data_dir / row["backup"]) in str(error.value)
            assert str(fresh_db.settings.data_dir / row["quarantine"]) in str(error.value)
            assert "python -m project_store.deletion_recovery" in str(error.value)
            assert not ProjectDeletionQueue(fresh_db).undo(PID)["changed"]
            with pytest.raises(FoundryError, match="recover"):
                request(fresh_db)
            assert PID in hidden_project_ids(fresh_db)
        assert "No normal service was started" in caplog.text
    # Recovery is offline and project-only. It verifies exact rows/files before
    # releasing the durable halt, including the absent-project-row case.
    conflict = fresh_db.settings.data_dir / "projects" / PID
    conflict.mkdir()
    conflict_file = conflict / "owner-preserved.bin"
    conflict_file.write_bytes(b"preserve conflicting partial publication")
    with pytest.raises(FoundryError):
        recover(fresh_db, PID)
    assert conflict_file.read_bytes() == b"preserve conflicting partial publication"
    with fresh_db.connection() as conn:
        assert conn.execute("SELECT recovery_required FROM project_deletion_requests WHERE project_id=?", (PID,)).fetchone()[0] == 1
    conflict_file.unlink()
    conflict.rmdir()
    assert recover(fresh_db, PID)["recovered"]
    assert project_state(fresh_db, PID) == before
    assert_preserved(fresh_db, preserved)
    assert ProjectDeletionQueue(fresh_db).process_at_startup() == []
    assert request(fresh_db)["queued"]
    with fresh_db.connection() as conn:
        assert conn.execute("SELECT quarantine FROM project_deletion_requests WHERE project_id=?", (PID,)).fetchone()[0] is None
    assert ProjectDeletionQueue(fresh_db).undo(PID)["changed"]


@pytest.mark.parametrize("filename,value", [
    ("MatchLock.json", "missing"), ("GenesisState.json", "missing"),
    ("MatchLock.json", {}), ("GenesisState.json", None),
    ("MatchLock.json", {"actor_ids": []}),
    ("FactoryIntegration.json", {}), ("FactoryIntegration.json", None),
    ("PortableRuntimeAuthority.json", {}), ("PortableRuntimeAuthority.json", None),
    ("actors", {}), ("actors", []), ("identity", "wrong-fight"),
    ("missing_portable", None),
])
def test_unknown_fight_binding_refused_on_application_startup(fresh_db, persisted_bindings, filename, value):
    seed(fresh_db, state="saved_draft")
    before = project_state(fresh_db, PID)
    match = fresh_db.settings.data_dir / "Combat/Matches/scratch-fight"
    match.mkdir(parents=True)
    # Start from a real persisted shape with verified unrelated participants.
    docs = write_bindings(match, persisted_bindings,
                          "portable-character:unknown-project" if filename == "missing_portable" else "actor:factory." + OTHER)
    if filename == "actors":
        docs["GenesisState.json"]["state"]["actors"] = value
        (match / "GenesisState.json").write_text(json.dumps(docs["GenesisState.json"]))
    elif filename == "identity":
        docs["GenesisState.json"]["match_id"] = value
        (match / "GenesisState.json").write_text(json.dumps(docs["GenesisState.json"]))
    elif filename == "missing_portable":
        pass  # Runtime actor ownership cannot be recovered from its hash.
    elif value == "missing":
        (match / filename).unlink()
    else:
        (match / filename).write_text(json.dumps(value))
    (match / "Manifest.json").write_text(json.dumps({"status": "ACTIVE"}))
    request(fresh_db)
    app = create_app(settings=fresh_db.settings)
    assert app.state.startup_deletions[0]["status"] == "failed"
    assert "bindings" in failure_reason(fresh_db)
    assert app.state.project_deletion_queue.hidden_cards()[0]["deletion_reason"] == failure_reason(fresh_db)
    assert project_state(fresh_db, PID) == before
    assert not list(fresh_db.settings.data_dir.glob("backups/deleted-characters/*.zip"))


def test_hidden_card_api_and_undo_no_duplicate_archive(fresh_db, monkeypatch, persisted_bindings):
    seed(fresh_db, state="saved_draft")
    CharacterLibraryArchiveService(fresh_db).archive(PID)
    app = create_app(settings=fresh_db.settings)
    endpoints = {route.path: route.endpoint for route in app.routes if hasattr(route, "methods")
                 and ("GET" in route.methods or route.path.endswith(("/delete-permanently", "/undo-delete")))}
    monkeypatch.setattr(app.state.combat, "factory_characters", lambda: [{"project_id": PID}, {"project_id": OTHER}])
    from combat.gate3_storage import encode_match_directory_name
    match_name = encode_match_directory_name("scratch-fight")
    match = fresh_db.settings.data_dir / "Combat/Matches" / match_name
    match.mkdir(parents=True)
    write_bindings(match, persisted_bindings)
    (match / "Manifest.json").write_text(json.dumps({"status": "ACTIVE"}))
    monkeypatch.setattr(app.state.combat, "list_matches", lambda: [{"match_id": "scratch-fight"}, {"match_id": "other-fight"}])
    endpoints["/api/character-library/{project_id}/delete-permanently"](PID, {"confirm_project_id": PID})
    assert endpoints["/api/projects"]() == []
    assert endpoints["/api/characters"]() == []
    assert endpoints["/api/character-library"]() == []
    assert endpoints["/api/combat/factory-characters"]() == [{"project_id": OTHER}]
    assert endpoints["/api/combat/matches"]() == [{"match_id": "other-fight"}]
    cards = endpoints["/api/character-library/archived"]()
    assert len(cards) == 1 and cards[0]["deletion_status"] == "queued"
    assert endpoints["/api/character-library/{project_id}/undo-delete"](PID)["changed"]
    assert endpoints["/api/character-library/archived"]()[0]["archived_at"]
    assert len(endpoints["/api/combat/matches"]()) == 2
