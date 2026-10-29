"""Start Over: owner input is decided by the lock source, not a field list.

Review STARTOVERKEEP1F2R2 and STARTOVERKEEP1F3R. The builder marks each lock it
writes from a default or a computed value (source BUILDER_DEFAULT_LOCK_SOURCE).
Start Over keeps a temporary character when any other lock holds content, when a
build run or brief edit exists, or when a locked record has no seal row.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from app.core import Database, Settings
from character_builder.service import CharacterBuilderService
from character_creation.custom_training_source_authority import (
    CUSTOM_TRAINING_SOURCE_PACK_ID,
    CUSTOM_TRAINING_SOURCE_PACK_VERSION,
)
from project_store.service import BUILDER_DEFAULT_LOCK_SOURCE, ProjectStore

ROOT = Path(__file__).resolve().parents[1]

# The guided wizard's own defaults (guidedLevel 15, guidedPower rival/boss,
# creationMode quick). A character made with only these values has no owner input.
WIZARD_DEFAULTS = dict(target_cl=15, power_band="rival/boss", creation_mode="quick")


def _clone_catalog_db(catalog_environment: dict, data_dir: Path) -> tuple[Settings, Database]:
    settings = Settings.from_env(ROOT, data_dir)
    settings.ensure_dirs()
    source = sqlite3.connect(catalog_environment["settings"].db_path)
    target = sqlite3.connect(settings.db_path)
    source.backup(target)
    target.close()
    source.close()
    source_security = catalog_environment["settings"].data_dir / "security"
    target_security = settings.data_dir / "security"
    if source_security.is_dir():
        shutil.copytree(source_security, target_security, dirs_exist_ok=True, copy_function=shutil.copy2)
    db = Database(settings)
    db.migrate()
    return settings, db


def _create(db: Database, *, name: str = "", concept: str = "", source: str | None = None, ability_scores=None, generation_route: str = "player", **overrides):
    fields = {**WIZARD_DEFAULTS, **overrides}
    return CharacterBuilderService(db).create_project(
        working_name=name,
        concept=concept,
        source_reference=source,
        ability_scores=ability_scores or {},
        selections={},
        generation_route=generation_route,
        **fields,
    )


def _project_exists(db: Database, project_id: str) -> bool:
    with db.connection() as conn:
        return conn.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone() is not None


def _user_locks(db: Database, project_id: str) -> list[dict]:
    with db.connection() as conn:
        row = conn.execute("SELECT project_json FROM projects WHERE project_id=?", (project_id,)).fetchone()
    return json.loads(row["project_json"])["user_locks"]


def test_typed_source_alone_keeps_the_temporary_character(catalog_environment, tmp_path):
    """Finding 1: a typed source with no name, concept, choices or runs is owner input."""
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "typed source only")
    store = ProjectStore(db)
    project_id = _create(db, source="Ledger of the Tessel Coast")["project_id"]

    result = store.discard_temporary_project(project_id, reason="starting_over")

    assert result["retention"] == "owner_input"
    assert _project_exists(db, project_id)
    assert store.builder_lifecycle(project_id)["persistence_state"] == "saved_draft"


def test_explicit_default_source_alone_is_still_deleted(catalog_environment, tmp_path):
    """The form default "Original character" is a builder default, not owner input."""
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "default source only")
    store = ProjectStore(db)
    project_id = _create(db, source="Original character")["project_id"]

    store.discard_temporary_project(project_id, reason="starting_over")

    assert not _project_exists(db, project_id)


def test_fixed_ability_scores_alone_keep_the_temporary_character(catalog_environment, tmp_path):
    """Owner-fixed ability scores are owner input even with a blank name and concept."""
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "fixed scores only")
    store = ProjectStore(db)
    project_id = _create(db, ability_scores={"STR": 15})["project_id"]

    result = store.discard_temporary_project(project_id, reason="starting_over")

    assert result["retention"] == "owner_input"
    assert _project_exists(db, project_id)


def test_blank_builder_character_marks_every_builder_written_lock(catalog_environment, tmp_path):
    """Finding 2 (F2R2): the builder marks each default it writes; a blank wizard
    character has no unmarked lock that holds content, so no field list is needed."""
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "blank markers")
    project_id = _create(db)["project_id"]
    by_field = {lock["field"]: lock for lock in _user_locks(db, project_id)}

    for field in ("target_cl", "power_band", "character_sheet.creation_mode", "source_reference", "character_sheet.canonical_grant_plan"):
        assert by_field[field].get("source") == BUILDER_DEFAULT_LOCK_SOURCE, field
    unmarked_with_content = [
        lock["field"]
        for lock in by_field.values()
        if lock.get("source") != BUILDER_DEFAULT_LOCK_SOURCE and ProjectStore._has_content(lock.get("value"))
    ]
    assert unmarked_with_content == []


def test_wizard_sequence_blank_character_is_deleted(catalog_environment, tmp_path):
    """Finding 2 (F3R) and finding 1 (F3R): the sequence the wizard actually runs.

    app.js creates the character, then unconditionally calls the normal
    first-cycle catalog lock, then Start Over discards it. The lock the server
    writes in that second step is builder-computed, so the blank character is
    still not owner input and must be deleted.
    """
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "wizard blank")
    store = ProjectStore(db)
    service = CharacterBuilderService(db)
    project_id = _create(db, generation_route="ai_bootstrap")["project_id"]
    first_cycle = service.commit_normal_first_cycle_catalog_choices(project_id)
    assert first_cycle["grant_plan"]["ready"] is True

    commit_lock = next(
        lock for lock in _user_locks(db, project_id)
        if lock["field"] == "character_creation.committed_catalog_choice_plan"
    )
    assert commit_lock["source"] == BUILDER_DEFAULT_LOCK_SOURCE

    store.discard_temporary_project(project_id, reason="owner_abandoned_or_started_over")

    assert not _project_exists(db, project_id)


def test_non_default_level_power_band_or_mode_alone_keeps_the_temporary_character(catalog_environment, tmp_path):
    """Finding 3 (F3R): a deliberately chosen level, power band or manual mode is owner input."""
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "chosen fields")
    store = ProjectStore(db)
    for label, overrides in (
        ("level", dict(target_cl=10)),
        ("power band", dict(power_band="heroic")),
        ("manual mode", dict(creation_mode="detailed")),
    ):
        project_id = _create(db, **overrides)["project_id"]

        result = store.discard_temporary_project(project_id, reason="starting_over")

        assert result["retention"] == "owner_input", label
        assert _project_exists(db, project_id), label


def test_owner_typed_lock_decision_reads_the_marker_only():
    """The decision uses the lock's source, not its field name."""
    assert ProjectStore._owner_typed_lock({"field": "character_sheet.future_default", "value": "x"}) is True
    assert ProjectStore._owner_typed_lock(
        {"field": "character_sheet.future_default", "value": "x", "source": BUILDER_DEFAULT_LOCK_SOURCE}
    ) is False
    assert ProjectStore._owner_typed_lock({"field": "concept", "value": ""}) is False


def test_owner_acquisition_commit_lock_stays_owner_input():
    """A commit that records owner-chosen acquisitions keeps its server source and counts."""
    assert ProjectStore._owner_typed_lock({
        "field": "character_creation.committed_catalog_choice_plan",
        "value": {"ready": True},
        "source": "server-validated-canonical-choice-commit",
    }) is True


def test_custom_source_record_without_a_seal_row_is_owner_input(catalog_environment, tmp_path):
    """Owner-authored records are locked after creation with no seal row, so they count.

    Guard for the corrected _has_owner_input docstring: the records predicate is
    live, not dead code.
    """
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "custom source record")
    store = ProjectStore(db)
    project_id = _create(db)["project_id"]
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
            (project_id, "custom.source.test", CUSTOM_TRAINING_SOURCE_PACK_ID, CUSTOM_TRAINING_SOURCE_PACK_VERSION, "0" * 64, "{}"),
        )

    result = store.discard_temporary_project(project_id, reason="starting_over")

    assert result["retention"] == "owner_input"
    assert _project_exists(db, project_id)


def test_cancelled_build_run_alone_keeps_the_temporary_character(catalog_environment, tmp_path):
    """A build run is owner input, so a cancelled run keeps the character as a draft."""
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "cancelled run")
    store = ProjectStore(db)
    project_id = _create(db)["project_id"]
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO character_creation_runs(run_id,project_id,starting_revision,execution_mode,idempotency_key,
               request_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            ("run.cancelled.test", project_id, 1, "MANUAL_CHAT", "idem.cancelled.test", "{}", "CANCELLED",
             "2026-10-24T00:00:00Z", "2026-10-24T00:00:00Z"),
        )

    result = store.discard_temporary_project(project_id, reason="starting_over")

    assert result["retention"] == "owner_input"
    assert _project_exists(db, project_id)


def test_start_over_tells_the_owner_when_a_character_is_kept():
    """The client reads retention from the discard response and says so, instead of looking like nothing happened."""
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'discard?.retention === "owner_input"' in app_js
    assert "kept as a Saved Draft under Character Sheets" in app_js


def test_gm_card_calls_a_start_over_kept_character_saved():
    """Owner-input drafts kept by Start Over show the same Saved timestamp as a manual save."""
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert '"owner_discard_retained_owner_input"' in app_js

def test_explicit_sphere_grant_with_blank_name_and_concept_is_kept(catalog_environment, tmp_path):
    """STARTOVERKEEP1F4R finding 1: an acquisition the owner chose at creation is
    owner input even with a blank name and concept. The grant plan and its origin
    must not be builder defaults, or Start Over deletes the chosen Sphere."""
    from canonical_catalog import CanonicalCatalogAuthorityService

    sphere = "tianxia.sphere.source"
    service = CanonicalCatalogAuthorityService(ROOT)
    projection = service.creator_projection(target_cl=1, acquired_sphere_ids=[sphere])
    talent = next(
        row["canonical_talent_id"] for row in projection["talent_dispositions"]
        if row["owning_canonical_sphere_id"] == sphere and row["selectable_now"]
    )
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "explicit sphere grant")
    store = ProjectStore(db)
    project_id = CharacterBuilderService(db).create_project(
        working_name="", concept="", target_cl=1, power_band="standard",
        source_reference=None, creation_mode="quick", ability_scores={}, selections={},
        sphere_priority_ids=[sphere], talent_priority_ids=[talent],
        canonical_sphere_ids=[sphere], sphere_free_talent_grants={sphere: talent},
        ordinary_talent_ids=[],
    )["project"]["project_id"]
    by_field = {lock["field"]: lock for lock in _user_locks(db, project_id)}
    assert by_field["character_sheet.canonical_grant_plan"].get("source") != BUILDER_DEFAULT_LOCK_SOURCE

    result = store.discard_temporary_project(project_id, reason="starting_over")

    assert result["retention"] == "owner_input"
    assert _project_exists(db, project_id)

