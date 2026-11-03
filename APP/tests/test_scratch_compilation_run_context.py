"""Retry compilation enters its phase only in the disposable database copy."""

from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings, canonical_json
from catalog_choice_authority import DELEGATED_FINAL_CATALOG_GRANT_FIELD
from character_creation.service import CharacterCreationExecutionService
from non_sphere_authority.service import (
    NonSphereAuthorityService,
    _server_initial_catalog_finalization_context,
    _TRUSTED_INITIAL_CATALOG_FINALIZATION,
)


@pytest.fixture
def copied_run(tmp_path):
    root = Path(__file__).resolve().parents[1]
    live = Database(Settings.from_env(root, tmp_path / "live"))
    scratch_root = tmp_path / "disposable"
    scratch = Database(Settings.from_env(root, scratch_root / "data"))
    request = {
        "project_revision": 4,
        "content_lock_hash": "c" * 64,
        "typed_choice_snapshot": {
            "canonical_project_id": "project",
            "project_revision": 4,
            "content_lock_hash": "c" * 64,
            "snapshot_sha256": "s" * 64,
        },
    }
    plan = {
        "schema": "TianxiaFactory.CanonicalGrantPlan.v1",
        "selected_talent_dispositions": [{
            "canonical_talent_id": "talent",
            "acquisition_provenance_required": True,
            "acquisition_provenance": {
                "source": "pending-trusted-initial-finalization",
                "recorded": False,
                "predicate_ids": ["predicate"],
            },
        }],
    }
    project = {"content_lock": {"lock_hash": "c" * 64}, "user_locks": [{
        "field": DELEGATED_FINAL_CATALOG_GRANT_FIELD, "value": plan,
    }]}
    with live.connection() as conn:
        conn.execute("CREATE TABLE projects(project_id TEXT PRIMARY KEY, revision INTEGER, project_json TEXT)")
        conn.executescript((root / "migrations/021_cg1_character_creation_runs.sql").read_text())
        conn.execute("INSERT INTO projects VALUES(?,?,?)", ("project", 4, canonical_json(project)))
        conn.execute(
            """INSERT INTO character_creation_runs
            (run_id,project_id,starting_revision,execution_mode,idempotency_key,request_json,
             status,created_at,updated_at,blockers_json)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("run", "project", 4, "STANDARD_API", "key", canonical_json(request),
             "NEEDS_REVIEW", "original", "original", '[{"code":"historical_failure"}]'),
        )
        with scratch.connection() as target:
            conn.backup(target)
    service = object.__new__(CharacterCreationExecutionService)
    service.db = live
    run = {"run_id": "run", "project_id": "project", "starting_revision": 4, "request": request}
    return service, run, scratch, scratch_root


def _row(db):
    with db.connection() as conn:
        return dict(conn.execute("SELECT * FROM character_creation_runs").fetchone())


def _validate(db, run, **overrides):
    context = _server_initial_catalog_finalization_context(
        run_id="run", project_id="project", starting_revision=4,
        content_lock_hash="c" * 64, typed_choice_snapshot_sha256="s" * 64,
        phase="scratch_compile", _authority=_TRUSTED_INITIAL_CATALOG_FINALIZATION,
        **overrides,
    )
    authority = object.__new__(NonSphereAuthorityService)
    with db.connection() as conn:
        authority._validate_initial_catalog_finalization_context(
            conn, run["project_id"], {"canonical_content_id": "talent", "binding_id": "predicate"}, context,
        )


@pytest.mark.parametrize("status", ["PREPARING_REQUEST", "WAITING_FOR_RESPONSE", "READY_FOR_REVIEW", "NEEDS_REVIEW"])
def test_retry_enters_scratch_phase_without_changing_live_or_evidence(copied_run, status):
    service, run, scratch, root = copied_run
    with scratch.connection() as conn:
        conn.execute("UPDATE character_creation_runs SET status=?", (status,))
    before_live, before_scratch = _row(service.db), _row(scratch)
    if status in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}:
        with pytest.raises(FoundryError, match="exact active clean revision-bound"):
            _validate(scratch, run)
    service._prepare_scratch_compilation_run(run, scratch, scratch_root=root)
    assert _row(service.db) == before_live
    assert _row(scratch) == {**before_scratch, "status": "PREPARING_REQUEST"}
    _validate(scratch, run)
    with pytest.raises(FoundryError, match="exact active clean revision-bound"):
        _validate(scratch, run, candidate_identity="unreviewed-candidate")


@pytest.mark.parametrize("column,value", [
    ("status", "CLEAN_AND_FINALIZED"), ("status", "REVISED"), ("status", "CANCELLED"),
    ("owner_decision", "approved"), ("completed_at", "completed"),
    ("starting_revision", 5), ("request_json", "{}"), ("project_id", "another"),
])
def test_invalid_copied_run_is_rejected_without_mutation(copied_run, column, value):
    service, run, scratch, root = copied_run
    with scratch.connection() as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(f"UPDATE character_creation_runs SET {column}=?", (value,))
    before = _row(scratch)
    with pytest.raises(FoundryError) as error:
        service._prepare_scratch_compilation_run(run, scratch, scratch_root=root)
    assert error.value.code == "CG1_SCRATCH_RUN_CONTEXT_INVALID"
    assert _row(scratch) == before


@pytest.mark.parametrize("alias", ["direct", "symlink", "hardlink", "outside"])
def test_live_database_and_nonisolated_paths_are_rejected(copied_run, alias):
    service, run, scratch, root = copied_run
    before = _row(service.db)
    if alias == "direct":
        scratch = service.db
    elif alias in {"symlink", "hardlink"}:
        scratch.settings.db_path.unlink()
        if alias == "symlink":
            scratch.settings.db_path.symlink_to(service.db.settings.db_path)
        else:
            scratch.settings.db_path.hardlink_to(service.db.settings.db_path)
    else:
        root = root / "unrelated"
    with pytest.raises(FoundryError) as error:
        service._prepare_scratch_compilation_run(run, scratch, scratch_root=root)
    assert error.value.code == "CG1_SCRATCH_RUN_CONTEXT_INVALID"
    assert _row(service.db) == before


@pytest.mark.parametrize("decision", ["ACCEPT_DESCRIPTIVE_FIELDS", "REPLACE_RESPONSE", "APPLY_DECISION"])
def test_active_owner_decisions_keep_the_copied_run_compilable(copied_run, decision):
    # Regression: an owner accepted the proposed name and concept while the
    # run sat at NEEDS_REVIEW; every later local rebuild was refused with
    # CG1_SCRATCH_RUN_CONTEXT_INVALID because any recorded decision was
    # treated as terminal.
    service, run, scratch, root = copied_run
    with scratch.connection() as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("UPDATE character_creation_runs SET owner_decision=?", (decision,))
    service._prepare_scratch_compilation_run(run, scratch, scratch_root=root)
    assert _row(scratch)["status"] == "PREPARING_REQUEST"



def test_saved_identity_wording_keeps_the_finalization_context_valid(copied_run):
    """Saving identity wording is a descriptive owner decision, not a mechanical one."""
    service, run, scratch, root = copied_run
    service._prepare_scratch_compilation_run(run, scratch, scratch_root=root)
    with scratch.connection() as conn:
        conn.execute("UPDATE character_creation_runs SET owner_decision='ACCEPT_DESCRIPTIVE_FIELDS'")
    _validate(scratch, run)
    with scratch.connection() as conn:
        conn.execute("UPDATE character_creation_runs SET owner_decision='REPLACE_RESPONSE'")
    with pytest.raises(FoundryError, match="exact active clean revision-bound"):
        _validate(scratch, run)
