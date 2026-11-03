"""Migration 030 guards: locked records stored once, read back unchanged.

The view must present exactly the shape the previous table did, because about
thirty call sites across the catalogue, projector, migration, non-sphere and
project-store modules select ``record_json`` from it by name.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import Database, Settings, sha256_text

APP_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def database(tmp_path: Path) -> Database:
    # ``conftest`` rebinds ``Settings.from_env`` to require both roots.
    database = Database(Settings.from_env(APP_ROOT, tmp_path))
    database.migrate()
    return database


def _seed_project(conn, project_id: str = "project-1") -> str:
    conn.execute(
        """INSERT INTO projects(
             project_id,working_name,status,revision,created_at,updated_at,
             target_factory_version,target_candidate_schema_version,target_gm_screen_version,
             quality_target,project_json,compatibility_projection_status,compile_status,
             consumer_verification_status)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            project_id, "Probe", "draft", 1, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
            "test", "test", "test", "rival/boss",
            json.dumps({"project_id": project_id}), "pending", "pending", "pending",
        ),
    )
    return project_id


def _seed_catalog_record(conn, record_id: str, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True)
    record_hash = sha256_text(body)
    conn.execute(
        """INSERT OR IGNORE INTO content_packs(
             pack_id,version,pack_hash,lifecycle_state,authority,manifest_json,installed_at)
           VALUES(?,?,?,?,?,?,?)""",
        ("pack.probe", "1.0", sha256_text("pack"), "installed", "owner", "{}", "2026-01-01T00:00:00Z"),
    )
    conn.execute(
        """INSERT INTO catalog_records(
             record_id,content_type,display_name,pack_id,pack_version,authority,publication_state,
             source_path,source_anchor,source_hash,record_hash,data_json)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            record_id, "talent", "Probe Talent", "pack.probe", "1.0", "owner", "published",
            "path.md", "anchor", sha256_text("source"), record_hash, body,
        ),
    )
    return record_hash


def _insert_locked(conn, project_id: str, record_id: str, record_hash: str, body: str, *, pack="pack.probe"):
    conn.execute(
        """INSERT INTO project_locked_records(
             project_id,record_id,pack_id,pack_version,record_hash,record_json)
           VALUES(?,?,?,?,?,?)""",
        (project_id, record_id, pack, "1.0", record_hash, body),
    )


def test_the_view_replaces_the_table_and_stores_content_once(database: Database) -> None:
    with database.transaction() as conn:
        kind = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='project_locked_records'"
        ).fetchone()[0]
        assert kind == "view"
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='project_locked_record_refs' AND type='table'"
        ).fetchone()[0] == 1

        project_id = _seed_project(conn)
        payload = {"record_id": "TAL-1", "text": "A" * 4000}
        record_hash = _seed_catalog_record(conn, "TAL-1", payload)
        body = json.dumps(payload, sort_keys=True)
        _insert_locked(conn, project_id, "TAL-1", record_hash, body)

        row = conn.execute(
            "SELECT project_id,record_id,pack_id,pack_version,record_hash,record_json"
            " FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, "TAL-1"),
        ).fetchone()
        assert row["record_json"] == body
        assert row["record_hash"] == record_hash
        assert row["pack_id"] == "pack.probe"

        # The catalogue already holds those bytes, so nothing was duplicated.
        assert conn.execute("SELECT COUNT(*) FROM locked_record_blobs").fetchone()[0] == 0


def test_content_without_a_catalogue_row_falls_back_to_a_blob(database: Database) -> None:
    with database.transaction() as conn:
        project_id = _seed_project(conn)
        body = json.dumps({"record_id": "METHOD-081", "text": "orphan"}, sort_keys=True)
        record_hash = sha256_text(body)
        _insert_locked(conn, project_id, "METHOD-081", record_hash, body, pack="tianxia.non_sphere.authority")

        assert conn.execute("SELECT COUNT(*) FROM locked_record_blobs").fetchone()[0] == 1
        assert conn.execute(
            "SELECT record_json FROM project_locked_records WHERE record_id='METHOD-081'"
        ).fetchone()[0] == body


def test_two_projects_locking_the_same_record_store_one_copy(database: Database) -> None:
    with database.transaction() as conn:
        payload = {"record_id": "TAL-9", "text": "B" * 8000}
        record_hash = _seed_catalog_record(conn, "TAL-9", payload)
        body = json.dumps(payload, sort_keys=True)
        for project_id in ("p-a", "p-b", "p-c"):
            _seed_project(conn, project_id)
            _insert_locked(conn, project_id, "TAL-9", record_hash, body)

        assert conn.execute("SELECT COUNT(*) FROM project_locked_record_refs").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM locked_record_blobs").fetchone()[0] == 0
        bodies = [
            r[0] for r in conn.execute(
                "SELECT record_json FROM project_locked_records ORDER BY project_id"
            )
        ]
        assert bodies == [body, body, body]


def test_bytes_that_disagree_with_their_hash_are_kept_verbatim(database: Database) -> None:
    """Deduplication must not launder a mismatched write into the catalogue copy.

    ``project_lock_proof`` detects a forged locked record by noticing that its
    stored bytes do not hash to its recorded ``record_hash``. If the view
    silently answered with the catalogue's copy instead, the forgery would
    become invisible, so a row whose content disagrees with its hash keeps its
    own bytes.
    """

    with database.transaction() as conn:
        project_id = _seed_project(conn)
        genuine = {"record_id": "TAL-7", "display_name": "Genuine"}
        record_hash = _seed_catalog_record(conn, "TAL-7", genuine)

        forged = json.dumps({"record_id": "TAL-7", "display_name": "Forged"}, sort_keys=True)
        _insert_locked(conn, project_id, "TAL-7", record_hash, forged)

        stored = conn.execute(
            "SELECT record_json FROM project_locked_records WHERE record_id='TAL-7'"
        ).fetchone()[0]
        assert stored == forged
        assert json.loads(stored)["display_name"] == "Forged"
        assert conn.execute(
            "SELECT record_json_override IS NOT NULL FROM project_locked_record_refs"
            " WHERE record_id='TAL-7'"
        ).fetchone()[0] == 1

        # The catalogue copy is untouched, so genuine readers still see it.
        assert json.loads(
            conn.execute("SELECT data_json FROM catalog_records WHERE record_id='TAL-7'").fetchone()[0]
        )["display_name"] == "Genuine"


def test_matching_content_stores_no_override(database: Database) -> None:
    with database.transaction() as conn:
        project_id = _seed_project(conn)
        payload = {"record_id": "TAL-8", "display_name": "Matching"}
        record_hash = _seed_catalog_record(conn, "TAL-8", payload)
        _insert_locked(conn, project_id, "TAL-8", record_hash, json.dumps(payload, sort_keys=True))

        assert conn.execute(
            "SELECT COUNT(*) FROM project_locked_record_refs WHERE record_json_override IS NOT NULL"
        ).fetchone()[0] == 0


def test_rebinding_a_record_to_different_bytes_is_refused(database: Database) -> None:
    import sqlite3

    with database.transaction() as conn:
        project_id = _seed_project(conn)
        first = {"record_id": "TAL-2", "text": "original"}
        first_hash = _seed_catalog_record(conn, "TAL-2", first)
        _insert_locked(conn, project_id, "TAL-2", first_hash, json.dumps(first, sort_keys=True))

        second_body = json.dumps({"record_id": "TAL-2", "text": "tampered"}, sort_keys=True)
        with pytest.raises(sqlite3.IntegrityError, match="HF2_PROJECT_LOCKED_RECORD_IMMUTABLE"):
            _insert_locked(conn, project_id, "TAL-2", sha256_text(second_body), second_body)


def test_reinserting_the_identical_binding_is_idempotent(database: Database) -> None:
    with database.transaction() as conn:
        project_id = _seed_project(conn)
        payload = {"record_id": "TAL-3", "text": "same"}
        record_hash = _seed_catalog_record(conn, "TAL-3", payload)
        body = json.dumps(payload, sort_keys=True)
        _insert_locked(conn, project_id, "TAL-3", record_hash, body)
        _insert_locked(conn, project_id, "TAL-3", record_hash, body)

        assert conn.execute("SELECT COUNT(*) FROM project_locked_record_refs").fetchone()[0] == 1


def test_updating_through_the_view_is_refused(database: Database) -> None:
    import sqlite3

    with database.transaction() as conn:
        project_id = _seed_project(conn)
        payload = {"record_id": "TAL-4", "text": "fixed"}
        record_hash = _seed_catalog_record(conn, "TAL-4", payload)
        _insert_locked(conn, project_id, "TAL-4", record_hash, json.dumps(payload, sort_keys=True))

        with pytest.raises(sqlite3.IntegrityError, match="HF2_PROJECT_LOCKED_RECORD_IMMUTABLE"):
            conn.execute("UPDATE project_locked_records SET record_json='{}' WHERE record_id='TAL-4'")


def test_deleting_through_the_view_without_authorization_is_refused(database: Database) -> None:
    import sqlite3

    with database.transaction() as conn:
        project_id = _seed_project(conn)
        payload = {"record_id": "TAL-5", "text": "kept"}
        record_hash = _seed_catalog_record(conn, "TAL-5", payload)
        _insert_locked(conn, project_id, "TAL-5", record_hash, json.dumps(payload, sort_keys=True))

        with pytest.raises(sqlite3.IntegrityError, match="HF2_PROJECT_LOCKED_RECORD_IMMUTABLE"):
            conn.execute("DELETE FROM project_locked_records WHERE record_id='TAL-5'")
        assert conn.execute("SELECT COUNT(*) FROM project_locked_record_refs").fetchone()[0] == 1


def test_deleting_a_project_cascades_to_its_references(database: Database) -> None:
    with database.transaction() as conn:
        project_id = _seed_project(conn)
        payload = {"record_id": "TAL-6", "text": "cascade"}
        record_hash = _seed_catalog_record(conn, "TAL-6", payload)
        _insert_locked(conn, project_id, "TAL-6", record_hash, json.dumps(payload, sort_keys=True))
        assert conn.execute("SELECT COUNT(*) FROM project_locked_record_refs").fetchone()[0] == 1

        conn.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
        assert conn.execute("SELECT COUNT(*) FROM project_locked_record_refs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM project_locked_records").fetchone()[0] == 0
