from __future__ import annotations

import json
import ast
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.api import create_app
from app.core import Database, FoundryError, Settings
from character_library_archive import CharacterLibraryArchiveService
from tests import pre_summary_library_support


ROOT = Path(__file__).resolve().parents[1]


def _minimal_database(tmp_path, active_status: str):
    db = Database(Settings.from_env(ROOT, tmp_path / "data"))
    with db.transaction() as conn:
        conn.execute("CREATE TABLE projects(project_id TEXT PRIMARY KEY)")
        conn.execute(
            """CREATE TABLE character_creation_runs(
               run_id TEXT PRIMARY KEY,
               project_id TEXT NOT NULL,
               status TEXT NOT NULL,
               updated_at TEXT NOT NULL,
               state_json TEXT NOT NULL,
               FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
            )"""
        )
        conn.execute(
            """CREATE TABLE events(
               project_id TEXT NOT NULL,
               sequence_no INTEGER NOT NULL,
               event_json TEXT NOT NULL,
               PRIMARY KEY(project_id, sequence_no),
               FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
            )"""
        )
        conn.execute(
            """CREATE TABLE snapshots(
               project_id TEXT NOT NULL,
               sequence_no INTEGER NOT NULL,
               state_json TEXT NOT NULL,
               PRIMARY KEY(project_id, sequence_no),
               FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
            )"""
        )
        conn.execute("INSERT INTO projects(project_id) VALUES(?)", ("saved",))
        conn.execute("INSERT INTO projects(project_id) VALUES(?)", ("active",))
        conn.execute(
            "INSERT INTO character_creation_runs(run_id,project_id,status,updated_at,state_json) VALUES(?,?,?,?,?)",
            ("run", "active", active_status, "2026-09-05T16:25:52Z", "{malformed-run-state"),
        )
        conn.execute("INSERT INTO events(project_id,sequence_no,event_json) VALUES(?,?,?)", ("active", 1, "{malformed-event"))
        conn.execute("INSERT INTO snapshots(project_id,sequence_no,state_json) VALUES(?,?,?)", ("active", 1, "{malformed-snapshot"))
    return db


@pytest.mark.parametrize("active_status", ("PREPARING_REQUEST", "WAITING_FOR_RESPONSE"))
def test_archive_service_is_reversible_idempotent_and_preserves_pending_state(tmp_path, active_status):
    db = _minimal_database(tmp_path, active_status)
    service = CharacterLibraryArchiveService(db)

    def protected_rows():
        with db.connection() as conn:
            return {
                "projects": [tuple(row) for row in conn.execute("SELECT * FROM projects ORDER BY project_id")],
                "runs": [tuple(row) for row in conn.execute("SELECT * FROM character_creation_runs ORDER BY run_id")],
                "events": [tuple(row) for row in conn.execute("SELECT * FROM events ORDER BY project_id,sequence_no")],
                "snapshots": [tuple(row) for row in conn.execute("SELECT * FROM snapshots ORDER BY project_id,sequence_no")],
            }

    first = service.archive("saved")
    second = service.archive("saved")
    assert first["changed"] is True
    assert second == {**first, "changed": False}
    assert service.archived_project_ids() == {"saved"}
    assert service.list_archived() == [{"project_id": "saved", "archived_at": first["archived_at"]}]

    restored = service.restore("saved")
    assert restored == {"project_id": "saved", "archived": False, "changed": True}
    assert service.restore("saved") == {"project_id": "saved", "archived": False, "changed": False}
    assert service.archived_project_ids() == set()

    before_pending = protected_rows()
    pending_first = service.archive("active")
    pending_second = service.archive("active")
    assert pending_first["changed"] is True
    assert pending_second == {**pending_first, "changed": False}
    assert protected_rows() == before_pending
    assert service.restore("active") == {"project_id": "active", "archived": False, "changed": True}
    assert protected_rows() == before_pending

    with pytest.raises(FoundryError) as missing_archive:
        service.archive("missing")
    assert missing_archive.value.code == "CHARACTER_LIBRARY_PROJECT_NOT_FOUND"
    assert missing_archive.value.status_code == 404

    with pytest.raises(FoundryError) as missing:
        service.restore("missing")
    assert missing.value.code == "CHARACTER_LIBRARY_PROJECT_NOT_FOUND"
    assert missing.value.status_code == 404


def test_user_facing_project_lists_filter_archive_markers(tmp_path, monkeypatch):
    app = create_app(settings=Settings.from_env(ROOT, tmp_path / "app-data"))
    projects = [
        {
            "project_id": "visible", "working_name": "Visible", "status": "draft",
            "compile_status": "NOT_STARTED", "updated_at": "2026-09-05T16:25:52Z",
        },
        {
            "project_id": "hidden", "working_name": "Hidden", "status": "draft",
            "compile_status": "NOT_STARTED", "updated_at": "2026-09-05T16:25:52Z",
        },
    ]
    monkeypatch.setattr(app.state.projects, "list_projects", lambda: projects)
    monkeypatch.setattr(app.state.character_creation, "recoverable", lambda: [])
    monkeypatch.setattr(app.state.character_library_archives, "archived_project_ids", lambda: {"hidden"})
    monkeypatch.setattr(
        app.state.character_library_archives,
        "list_archived",
        lambda: [{"project_id": "hidden", "archived_at": "2026-09-05T16:30:00Z"}],
    )

    library_route = next(
        route for route in app.routes
        if route.path == "/api/character-library" and "GET" in route.methods
    )
    recovery_route = next(
        route for route in app.routes
        if route.path == "/api/character-builder/recovery" and "GET" in route.methods
    )
    project_route = next(route for route in app.routes if route.path == "/api/projects" and "GET" in route.methods)
    archived_route = next(
        route for route in app.routes
        if route.path == "/api/character-library/archived" and "GET" in route.methods
    )

    assert [row["project_id"] for row in library_route.endpoint()] == ["visible"]
    assert [row["project_id"] for row in project_route.endpoint()] == ["visible"]
    assert archived_route.endpoint() == [{**projects[1], "archived_at": "2026-09-05T16:30:00Z"}]

    monkeypatch.setattr(
        app.state.character_creation,
        "recoverable",
        lambda: [{"project_id": "visible"}, {"project_id": "hidden"}, {"status": "malformed-no-project-id"}],
    )
    assert recovery_route.endpoint() == [{"project_id": "visible"}, {"status": "malformed-no-project-id"}]


def test_character_library_reuses_identity_until_project_revision_changes(tmp_path, monkeypatch):
    app = create_app(settings=Settings.from_env(ROOT, tmp_path / "app-data"))
    project_id = "library-cache-regression"
    with app.state.db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects (
                   project_id, working_name, status, revision, created_at, updated_at,
                   target_factory_version, target_candidate_schema_version,
                   target_gm_screen_version, quality_target, project_json,
                   compatibility_projection_status, compile_status,
                   consumer_verification_status
               ) VALUES (?, ?, 'draft', 0, '2026-09-01', '2026-09-01',
                         'fixture', 'fixture', 'fixture', 'rival/boss',
                         '{"user_locks": []}', 'DRAFT', 'NOT_COMPILED', 'NOT_RUN')""",
            (project_id, "Library cache fixture"),
        )
    monkeypatch.setattr(app.state.character_creation, "recoverable", lambda: [])
    route = next(
        route.endpoint for route in app.routes
        if route.path == "/api/character-library" and "GET" in route.methods
    )

    identity_reads = {"run": 0, "locks": 0}
    original_connect = app.state.db.connect

    def traced_connect():
        conn = original_connect()
        conn.set_trace_callback(
            lambda sql: identity_reads.__setitem__(
                "run", identity_reads["run"] + 1
            ) if "accepted_descriptive_fields_json" in sql else
            identity_reads.__setitem__(
                "locks", identity_reads["locks"] + 1
            ) if "json_each(p.project_json" in sql else None
        )
        return conn

    monkeypatch.setattr(app.state.db, "connect", traced_connect)
    app.state.fill_missing_character_library_summaries()
    assert [row["project_id"] for row in route()] == [project_id]
    assert identity_reads == {"run": 1, "locks": 1}

    route()
    assert identity_reads == {"run": 1, "locks": 1}

    with app.state.db.transaction() as conn:
        conn.execute(
            "UPDATE projects SET revision=revision+1, updated_at='2026-09-02' WHERE project_id=?",
            (project_id,),
        )
    app.state.fill_missing_character_library_summaries()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _index: route(), range(2)))
    assert identity_reads == {"run": 2, "locks": 2}
    with app.state.db.connection() as conn:
        summary = conn.execute(
            "SELECT fingerprint FROM project_library_summary WHERE project_id=?", (project_id,)
        ).fetchone()
    assert summary and summary["fingerprint"]


def test_character_library_summary_survives_reload_and_invalidates_run_name_and_locks(tmp_path, monkeypatch):
    data_dir = tmp_path / "app-data"
    app = create_app(settings=Settings.from_env(ROOT, data_dir))
    project_id = "library-summary-regression"
    locks = [
        {"field": "target_cl", "value": 5},
        {"field": "character_sheet.locked_choices", "value": {
            "background_choice": ["background.sage"],
            "path_choice": ["path.sword"],
        }},
    ]
    project_json = json.dumps({"user_locks": locks}, separators=(",", ":"))
    with app.state.db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects (
                   project_id, working_name, status, revision, created_at, updated_at,
                   target_factory_version, target_candidate_schema_version,
                   target_gm_screen_version, quality_target, project_json,
                   compatibility_projection_status, compile_status,
                   consumer_verification_status
               ) VALUES (?, 'AI-proposed character', 'draft', 0, '2026-09-01', '2026-09-01',
                         'fixture', 'fixture', 'fixture', 'rival/boss', ?, 'DRAFT', 'NOT_COMPILED', 'NOT_RUN')""",
            (project_id, project_json),
        )
        conn.execute(
            """INSERT INTO character_creation_runs(
                   run_id,project_id,starting_revision,execution_mode,idempotency_key,
                   request_json,status,created_at,updated_at,completed_at,
                   accepted_descriptive_fields_json,owner_descriptive_fields_json
               ) VALUES('run-library','library-summary-regression',0,'MANUAL_CHAT','key','{}',
                        'IN_PROGRESS','2026-09-01','2026-09-02',NULL,
                        '{"identity":{"name":"Misty","title":"Young Master"}}','{}')"""
        )
    monkeypatch.setattr(app.state.character_creation, "recoverable", lambda: [])
    app.state.fill_missing_character_library_summaries()
    route = next(route.endpoint for route in app.routes if route.path == "/api/character-library" and "GET" in route.methods)
    first = route()[0]
    assert {key: first[key] for key in ("name", "title", "target_cl", "background", "paths", "completed_at", "last_worked_at")} == {
        "name": "Misty", "title": "Young Master", "target_cl": 5,
        "background": "Sage", "paths": ["Sword"], "completed_at": None,
        "last_worked_at": "2026-09-02",
    }

    # A new app instance represents a process reload: it reads the persisted summary
    # and must not evaluate JSON from either oversized source column again.
    reloaded = create_app(settings=Settings.from_env(ROOT, data_dir))
    monkeypatch.setattr(reloaded.state.character_creation, "recoverable", lambda: [])
    sql_seen: list[str] = []
    connect = reloaded.state.db.connect
    def traced_connect():
        conn = connect()
        conn.set_trace_callback(sql_seen.append)
        return conn
    monkeypatch.setattr(reloaded.state.db, "connect", traced_connect)
    reloaded_route = next(route.endpoint for route in reloaded.routes if route.path == "/api/character-library" and "GET" in route.methods)
    assert reloaded_route()[0]["name"] == "Misty"
    assert not any("accepted_descriptive_fields_json" in sql or "json_each(p.project_json" in sql for sql in sql_seen)

    def current_row():
        return reloaded_route()[0]

    # Name acceptance and run completion both change the summary fingerprint.
    with reloaded.state.db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET accepted_descriptive_fields_json=?,updated_at=? WHERE run_id='run-library'",
            ('{"identity":{"name":"Interim","title":"Sage"}}', '2026-09-02'),
        )
        conn.execute(
            "UPDATE character_creation_runs SET accepted_descriptive_fields_json=? WHERE run_id='run-library'",
            ('{"identity":{"name":"Misty Bright","title":"Sage"}}',),
        )
    # Several accepted identities in the same second, then another process.
    reloaded = create_app(settings=Settings.from_env(ROOT, data_dir))
    monkeypatch.setattr(reloaded.state.character_creation, "recoverable", lambda: [])
    reloaded_route = next(route.endpoint for route in reloaded.routes if route.path == "/api/character-library" and "GET" in route.methods)
    reloaded.state.fill_missing_character_library_summaries()
    changed_name = current_row()
    assert (changed_name["name"], changed_name["title"], changed_name["last_worked_at"]) == ("Misty Bright", "Sage", "2026-09-02")
    with reloaded.state.db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET status='CLEAN_AND_FINALIZED',completed_at=?,updated_at=? WHERE run_id='run-library'",
            ('2026-09-04', '2026-09-04'),
        )
    reloaded.state.fill_missing_character_library_summaries()
    assert current_row()["completed_at"] == "2026-09-04"

    # Lock changes advance the project revision/update marker and refresh lock-derived facts.
    locks[0]["value"] = 7
    with reloaded.state.db.transaction() as conn:
        conn.execute(
            "UPDATE projects SET revision=revision+1,updated_at=?,project_json=? WHERE project_id=?",
            ('2026-09-05', json.dumps({"user_locks": locks}, separators=(",", ":")), project_id),
        )
    reloaded.state.fill_missing_character_library_summaries()
    assert current_row()["target_cl"] == 7


def test_background_summary_fill_does_not_block_list_and_deduplicates_project(tmp_path, monkeypatch):
    app = create_app(settings=Settings.from_env(ROOT, tmp_path / "background-fill"))
    project_id = "library-background-fill"
    with app.state.db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects (project_id,working_name,status,revision,created_at,updated_at,
                   target_factory_version,target_candidate_schema_version,target_gm_screen_version,quality_target,
                   project_json,compatibility_projection_status,compile_status,consumer_verification_status)
               VALUES (?,'Background fixture','draft',0,'2026-09-01','2026-09-01','f','c','g','rival/boss','{}','DRAFT','NOT_COMPILED','NOT_RUN')""",
            (project_id,),
        )
    monkeypatch.setattr(app.state.character_creation, "recoverable", lambda: [])
    route = next(route.endpoint for route in app.routes if route.path == "/api/character-library" and "GET" in route.methods)
    started, release = threading.Event(), threading.Event()
    calls = {"count": 0}
    original_reader = app.state.library_summary_identity_reader

    def slow_reader(conn, current_project_id):
        calls["count"] += 1
        started.set()
        assert release.wait(5)
        return original_reader(conn, current_project_id)

    monkeypatch.setattr(app.state, "library_summary_identity_reader", slow_reader)
    worker = threading.Thread(target=app.state.fill_missing_character_library_summaries, daemon=True)
    worker.start()
    assert started.wait(5)
    # A concurrent fill observes the same project in flight and does no duplicate extraction.
    duplicate = threading.Thread(target=app.state.fill_missing_character_library_summaries, daemon=True)
    duplicate.start()
    rows = route()
    assert [row["project_id"] for row in rows] == [project_id]
    assert rows[0]["name"] == "Background fixture"
    assert rows[0]["summary_pending"] is True
    assert calls["count"] == 1
    # Extraction is still paused. A writer must finish before it is released,
    # and changing the source requires a fresh snapshot before publication.
    with ThreadPoolExecutor(max_workers=1) as pool:
        def change_source():
            with app.state.db.transaction() as conn:
                conn.execute("UPDATE projects SET project_json=? WHERE project_id=?",
                             (json.dumps({"user_locks": [{"field": "target_cl", "value": 9}]}), project_id))
        pool.submit(change_source).result(timeout=2)
    release.set()
    worker.join(5)
    duplicate.join(5)
    assert not worker.is_alive() and not duplicate.is_alive()
    assert calls["count"] == 2
    assert route()[0]["target_cl"] == 9
    assert route()[0]["summary_pending"] is False
    with app.state.db.connection() as conn:
        assert conn.execute("SELECT 1 FROM project_library_summary WHERE project_id=?", (project_id,)).fetchone()


def test_fight_roster_filters_archived_characters(tmp_path, monkeypatch):
    app = create_app(settings=Settings.from_env(ROOT, tmp_path / "app-data"))
    monkeypatch.setattr(
        app.state.combat, "factory_characters",
        lambda: [{"project_id": "visible"}, {"project_id": "hidden"}],
    )
    monkeypatch.setattr(app.state.character_library_archives, "archived_project_ids", lambda: {"hidden"})
    roster_route = next(
        route for route in app.routes
        if route.path == "/api/combat/factory-characters" and "GET" in route.methods
    )
    assert roster_route.endpoint() == [{"project_id": "visible"}]


def test_library_summary_migration_preserves_existing_database_rows(tmp_path):
    fresh = create_app(settings=Settings.from_env(ROOT, tmp_path / "fresh-data"))
    with fresh.state.db.connection() as conn:
        assert conn.execute("SELECT 1 FROM project_library_summary LIMIT 1").fetchone() is None
        assert conn.execute("SELECT 1 FROM schema_migrations WHERE version='034_project_library_summary.sql'").fetchone()

    app = create_app(settings=Settings.from_env(ROOT, tmp_path / "existing-data"))
    with app.state.db.transaction() as conn:
        conn.execute(
            "INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,"
            "target_factory_version,target_candidate_schema_version,target_gm_screen_version,quality_target,"
            "project_json,compatibility_projection_status,compile_status,consumer_verification_status) "
            "VALUES('pre-summary','Existing','draft',0,'2026-09-01','2026-09-01','f','c','g','rival/boss','{}','DRAFT','NOT_COMPILED','NOT_RUN')"
        )
        # Recreate the schema state of a pre-migration database while retaining
        # its existing project data, then apply the normal migration runner.
        conn.execute("DROP TABLE project_library_summary")
        conn.execute("DELETE FROM schema_migrations WHERE version='034_project_library_summary.sql'")
        conn.execute("DELETE FROM schema_migration_journal WHERE version='034_project_library_summary.sql'")
        conn.execute("INSERT INTO schema_migrations(version,applied_at) VALUES('032_project_library_summary.sql','2026-10-01')")
    app.state.db.migrate()
    with app.state.db.connection() as conn:
        assert conn.execute("SELECT 1 FROM project_library_summary LIMIT 1").fetchone() is None
        assert conn.execute("SELECT working_name FROM projects WHERE project_id='pre-summary'").fetchone()[0] == "Existing"
        assert conn.execute("SELECT 1 FROM schema_migrations WHERE version='032_project_library_summary.sql'").fetchone()
        assert conn.execute("SELECT 1 FROM schema_migrations WHERE version='034_project_library_summary.sql'").fetchone()


def test_library_full_fixture_equivalence_to_pre_summary_endpoint(tmp_path):
    """Compare every field and ordering with the retained pre-lane implementation.

    Only synthetic rows are used, including oversized identity/lock documents.
    Recovery/action projections are real, rather than replaced with empty mocks.
    """
    import app.api as api_module

    settings = Settings.from_env(ROOT, tmp_path / "equivalence")
    app = create_app(settings=settings)
    with app.state.db.transaction() as conn:
        for index, (project_id, status) in enumerate([
            ("active", "WAITING_FOR_RESPONSE"), ("finished-new", "CLEAN_AND_FINALIZED"),
            ("finished-old", "CLEAN_AND_FINALIZED"), ("archived", "WAITING_FOR_RESPONSE"),
            ("abandoned", "ABANDONED"),
        ]):
            stamp = f"2026-09-0{index + 1}"
            project_json = json.dumps({"user_locks": [
                {"field": "target_cl", "value": 5},
                {"field": "character_sheet.locked_choices", "value": {
                    "background_choice": ["background.sage"], "path_choice": ["path.sword"]}},
            ], "padding": "x" * (2 * 1024 * 1024)})
            conn.execute(
                "INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,"
                "target_factory_version,target_candidate_schema_version,target_gm_screen_version,quality_target,"
                "project_json,compatibility_projection_status,compile_status,consumer_verification_status) "
                "VALUES(?,'AI-proposed character','draft',0,?,?,'f','c','g','rival/boss',?,'DRAFT','NOT_COMPILED','NOT_RUN')",
                (project_id, stamp, stamp, project_json),
            )
            conn.execute(
                "INSERT INTO character_creation_runs(run_id,project_id,starting_revision,execution_mode,idempotency_key,"
                "request_json,status,created_at,updated_at,completed_at,accepted_descriptive_fields_json) "
                "VALUES(?,?,0,'MANUAL_CHAT',?,'{}',?,?,?,?,?)",
                (project_id, project_id, project_id, status, stamp, stamp,
                 stamp if status == "CLEAN_AND_FINALIZED" else None,
                 json.dumps({"identity": {"name": project_id.title(), "title": "Sage"}, "padding": "x" * (4 * 1024 * 1024)})),
            )
    app.state.character_library_archives.archive("archived")
    route = next(route.endpoint for route in app.routes if route.path == "/api/character-library" and "GET" in route.methods)
    # Compile just the three historical list functions, not another application
    # or checkout. Their globals use this same scratch database and real services.
    source = Path(pre_summary_library_support.__file__).read_text()
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in {
        "_library_identity", "_library_cached_facts", "character_library"}]
    assert len(nodes) == 3
    for node in nodes:
        node.decorator_list = []
    namespace = dict(vars(api_module))
    namespace.update(zip(route.__code__.co_freevars, (cell.cell_contents for cell in route.__closure__)))
    namespace["_library_identity_cache"] = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "pre-summary-library", "exec"), namespace)
    expected = namespace["character_library"]()
    assert len(expected) == 4
    assert any(row["workflow"]["active_run"] for row in expected)
    assert any(row["completed_at"] for row in expected)
    assert any(row["workflow"].get("action_availability") for row in expected)
    app.state.fill_missing_character_library_summaries()
    for current in (app, create_app(settings=settings)):
        endpoint = next(route.endpoint for route in current.routes if route.path == "/api/character-library" and "GET" in route.methods)
        for _ in range(2):
            actual = endpoint()
            # source_revision and summary_pending are this lane's additions to the
            # payload; every pre-existing field is compared against the retained
            # pre-summary implementation below.
            assert all(row.pop("summary_pending") is False for row in actual)
            assert all(isinstance(row.pop("source_revision"), int) for row in actual)
            assert actual == expected
    # Re-running 034 over legacy filled rows must retain their exact contents.
    with app.state.db.transaction() as conn:
        before = [tuple(row) for row in conn.execute("SELECT * FROM project_library_summary ORDER BY project_id")]
        conn.execute("DELETE FROM schema_migrations WHERE version='034_project_library_summary.sql'")
        conn.execute("DELETE FROM schema_migration_journal WHERE version='034_project_library_summary.sql'")
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES('032_project_library_summary.sql','2026-10-01')")
    app.state.db.migrate()
    with app.state.db.connection() as conn:
        assert [tuple(row) for row in conn.execute("SELECT * FROM project_library_summary ORDER BY project_id")] == before


def test_both_character_lists_report_a_comparable_source_revision(tmp_path, monkeypatch):
    """The library card and the optional character list project the same state.

    The builder joins the two payloads, so a slow /api/characters read must be
    able to tell that it is older than the summary already on screen. Both
    endpoints therefore report the durable per-project source version, and that
    version advances when an accepted identity changes.
    """
    from project_store.service import canonical_project_document

    settings = Settings.from_env(ROOT, tmp_path / "source-revision")
    app = create_app(settings=settings)
    project_id = "source-revision-regression"
    # A real canonical project document, so /api/characters builds its row through
    # the same service path it uses for the owner.
    project_json = json.dumps(canonical_project_document(
        project_id=project_id, name="Misty", revision=0, status="draft",
        created_at="2026-09-01", updated_at="2026-09-01",
        catalog_build_id="fixture", pack_locks=[], user_locks=[], event_count=0,
    ), separators=(",", ":"))
    with app.state.db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,
                   target_factory_version,target_candidate_schema_version,target_gm_screen_version,quality_target,
                   project_json,compatibility_projection_status,compile_status,consumer_verification_status)
               VALUES(?,'AI-proposed character','draft',0,'2026-09-01','2026-09-01','f','c','g','rival/boss',
                      ?,'DRAFT','NOT_COMPILED','NOT_RUN')""",
            (project_id, project_json),
        )
        conn.execute(
            "INSERT INTO character_creation_runs(run_id,project_id,starting_revision,execution_mode,idempotency_key,"
            "request_json,status,created_at,updated_at,completed_at,accepted_descriptive_fields_json,owner_descriptive_fields_json) "
            "VALUES('run-revision',?,0,'MANUAL_CHAT','key','{}','IN_PROGRESS','2026-09-01','2026-09-02',NULL,?,'{}')",
            (project_id, json.dumps({"identity": {"name": "Misty"}})),
        )
    monkeypatch.setattr(app.state.character_creation, "recoverable", lambda: [])
    app.state.fill_missing_character_library_summaries()
    library = next(route.endpoint for route in app.routes if route.path == "/api/character-library" and "GET" in route.methods)
    characters = next(route.endpoint for route in app.routes if route.path == "/api/characters" and "GET" in route.methods)

    def versions() -> tuple[int, int]:
        return library()[0]["source_revision"], next(row for row in characters() if row["project_id"] == project_id)["source_revision"]

    before = versions()
    assert all(isinstance(value, int) for value in before)
    assert before[0] == before[1], "both payloads describe the same source version"

    # An accepted identity is a same-second change: the durable counter moves
    # even though the timestamps do not, and both payloads must report it.
    with app.state.db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET accepted_descriptive_fields_json=?,updated_at=? WHERE run_id='run-revision'",
            (json.dumps({"identity": {"name": "Misty Bright"}}), "2026-09-02"),
        )
    after = versions()
    assert after[0] > before[0] and after[1] > before[1]
    assert after[0] == after[1]

    # A cached row is rebuilt when the source version moves, so a read made
    # before an acceptance can never be handed out again afterwards.
    with app.state.db.connection() as conn:
        conn.execute("UPDATE project_library_source_revision SET revision=revision+1 WHERE project_id=?", (project_id,))
    assert versions() == (after[0] + 1, after[1] + 1)
