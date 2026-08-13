from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Database, Settings
from tests.test_cat3_p1r_persistence import _clone_catalog_database


ROOT = Path(__file__).resolve().parents[1]
ATTEMPT_HISTORY_MARKER = "CG1_ATTEMPT_HISTORY_MUST_BE_RETAINED"


def _clone_catalog_environment(catalog_environment: dict, data_dir: Path) -> tuple[Settings, Database]:
    settings = Settings.from_env(ROOT, data_dir)
    db = _clone_catalog_database(catalog_environment["db"], settings)
    return settings, db


def _create_temporary_project_with_attempt(app, *, idempotency_key: str) -> tuple[str, str]:
    created = app.state.character_builder.create_project(
        working_name="REC1-P1CR4 retention proof",
        concept="Attempt history must survive owner discard and restart cleanup.",
        target_cl=1,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={},
    )
    project_id = created["project_id"]
    run = app.state.character_creation.start(
        project_id,
        execution_mode="MANUAL_CHAT",
        idempotency_key=idempotency_key,
    )
    # Public discard/start-over is legal only after the owner has explicitly
    # resolved the active run.  The cancellation itself creates immutable
    # attempt evidence that the retention paths must preserve.
    app.state.character_creation.cancel(run["run_id"])
    return project_id, run["run_id"]


def _assert_retained_rows(
    db: Database,
    project_id: str,
    run_id: str,
    *,
    expected_lifecycle: str = "saved_draft",
) -> None:
    with db.connection() as conn:
        project = conn.execute(
            "SELECT project_id FROM projects WHERE project_id=?",
            (project_id,),
        ).fetchone()
        run = conn.execute(
            "SELECT run_id FROM character_creation_runs WHERE run_id=? AND project_id=?",
            (run_id, project_id),
        ).fetchone()
        attempt = conn.execute(
            "SELECT attempt_id FROM character_creation_attempt_history WHERE run_id=? AND project_id=?",
            (run_id, project_id),
        ).fetchone()
        lifecycle = conn.execute(
            "SELECT persistence_state FROM character_builder_project_lifecycle WHERE project_id=?",
            (project_id,),
        ).fetchone()
    assert project is not None
    assert run is not None
    assert attempt is not None
    assert lifecycle["persistence_state"] == expected_lifecycle


def test_public_discard_retains_temporary_project_run_and_attempt_history(
    catalog_environment,
    tmp_path,
):
    settings, _db = _clone_catalog_environment(catalog_environment, tmp_path / "public-discard")
    app = create_app(settings)
    with TestClient(app) as client:
        project_id, run_id = _create_temporary_project_with_attempt(
            app,
            idempotency_key="retention-public-discard-1",
        )
        token = client.get("/api/session").json()["token"]
        response = client.delete(
            f"/api/character-builder/projects/{project_id}/temporary",
            headers={"x-foundry-token": token},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["discarded"] is True
        assert body["retained"] is True
        assert body["retention"] == "attempt_history"
        _assert_retained_rows(app.state.db, project_id, run_id)


def test_startup_cleanup_retains_temporary_project_run_and_attempt_history(
    catalog_environment,
    tmp_path,
):
    settings, db = _clone_catalog_environment(catalog_environment, tmp_path / "startup-cleanup")
    app = create_app(settings)
    project_id, run_id = _create_temporary_project_with_attempt(
        app,
        idempotency_key="retention-startup-cleanup-1",
    )

    with TestClient(app):
        cleanup = app.state.character_builder_startup_cleanup
        assert project_id in cleanup["retained_history_project_ids"]
        assert project_id not in cleanup["removed_project_ids"]
        _assert_retained_rows(db, project_id, run_id)


@pytest.mark.parametrize("table", ["projects", "character_creation_runs"])
def test_direct_delete_with_attempt_history_fails_closed_and_preserves_rows(
    catalog_environment,
    tmp_path,
    table,
):
    settings, db = _clone_catalog_environment(catalog_environment, tmp_path / f"direct-delete-{table}")
    app = create_app(settings)
    project_id, run_id = _create_temporary_project_with_attempt(
        app,
        idempotency_key=f"retention-direct-delete-{table}",
    )

    with pytest.raises(sqlite3.IntegrityError, match=ATTEMPT_HISTORY_MARKER):
        with db.transaction() as conn:
            if table == "projects":
                conn.execute("DELETE FROM projects WHERE project_id=?", (project_id,))
            else:
                conn.execute("DELETE FROM character_creation_runs WHERE run_id=?", (run_id,))

    _assert_retained_rows(db, project_id, run_id, expected_lifecycle="temporary")
