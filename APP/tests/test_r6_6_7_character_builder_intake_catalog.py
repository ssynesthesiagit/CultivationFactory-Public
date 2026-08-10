from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Database, FoundryError, Settings, canonical_json, sha256_json
from character_builder.service import CharacterBuilderService
from contracts.canonical import canonical_project_hash
from project_store.service import ProjectStore
from stage1.service import Stage1ClipboardService

ROOT = Path(__file__).resolve().parents[1]
CORE_PACK_ID = "tianxia.core.factory.hf05zvk.r1h.phase2i.hf2"


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


def _create_guided(service: CharacterBuilderService, *, name: str = "Temporary Character", selections=None):
    return service.create_project(
        working_name=name,
        concept="Focused R6.6.7 regression character",
        target_cl=5,
        power_band="rival/boss",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections=selections or {},
    )


def _project_exists(db: Database, project_id: str) -> bool:
    with db.connection() as conn:
        return conn.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone() is not None


def test_fixture_project_id_override_is_exact_canonical_and_ordinary_ids_remain_random(catalog_environment, tmp_path):
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "fixture identity")
    service = CharacterBuilderService(db)
    fixture_id = "40ea751e-7913-557f-b403-a3ec3cd7c004"
    kwargs = {
        "working_name": "Bounded fixture identity",
        "concept": "Fixture identity validation",
        "target_cl": 5,
        "power_band": "rival/boss",
        "source_reference": None,
        "creation_mode": "detailed",
        "ability_scores": {},
        "selections": {},
    }

    fixture = service.create_project(**kwargs, project_id_override=fixture_id)
    ordinary = service.create_project(**{**kwargs, "working_name": "Ordinary random identity"})

    assert fixture["project_id"] == fixture_id
    assert ordinary["project_id"] != fixture_id
    assert str(uuid.UUID(ordinary["project_id"])) == ordinary["project_id"]
    with pytest.raises(FoundryError) as raised:
        service.create_project(
            **{**kwargs, "working_name": "Noncanonical fixture identity"},
            project_id_override=fixture_id.upper(),
        )
    assert raised.value.code == "PROJECT_ID_OVERRIDE_INVALID"



def _clone_project_row(db: Database, source_project_id: str, *, working_name: str) -> str:
    project_id = str(uuid.uuid4())
    with db.transaction() as conn:
        source = conn.execute("SELECT * FROM projects WHERE project_id=?", (source_project_id,)).fetchone()
        assert source is not None
        data = dict(source)
        data["project_id"] = project_id
        data["working_name"] = working_name
        columns = list(data)
        conn.execute(
            f"INSERT INTO projects({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
            tuple(data[column] for column in columns),
        )
    return project_id


def test_more_than_eight_talent_priorities_round_trip_without_new_cap(catalog_environment, tmp_path):
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "unlimited talents")
    service = CharacterBuilderService(db)
    options = service.options()
    categories = {row["slot_id"]: row for row in options["categories"]}
    talent_choices = categories["advancement_skeleton"]["choices"]
    legal_by_sphere: dict[str, list[dict]] = {}
    for row in talent_choices:
        if row["planning_priority_available"]:
            legal_by_sphere.setdefault(row["owning_canonical_sphere_id"], []).append(row)
    sphere_id, legal_choices = next(
        (sphere_id, rows) for sphere_id, rows in legal_by_sphere.items() if len(rows) >= 12
    )
    talents = [row["choice_id"] for row in legal_choices[:12]]
    legacy_non_talent_id = "TAL_SPACE_BODY_REFINING"
    assert len(talents) == 12
    assert categories["advancement_skeleton"]["max"] is None
    # Independent category limits remain unchanged.
    assert categories["sphere_priorities"]["max"] is None
    assert categories["insight_priorities"]["max"] == 8
    assert categories["item_priorities"]["max"] == 8

    with db.connection() as conn:
        projects_before_rejection = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    with pytest.raises(FoundryError) as rejected:
        _create_guided(
            service,
            selections={
                "sphere_priorities": [sphere_id],
                "advancement_skeleton": [legacy_non_talent_id],
            },
        )
    assert rejected.value.code == "CHARACTER_PLANNING_TALENT_NOT_AVAILABLE"
    assert rejected.value.details["talents"][0]["talent_id"] == legacy_non_talent_id
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == projects_before_rejection

    created = _create_guided(
        service,
        selections={"sphere_priorities": [sphere_id], "advancement_skeleton": talents},
    )
    assert created["character_sheet"]["planning_preferences"] == {
        "sphere_priority_ids": [sphere_id],
        "talent_priority_ids": talents,
    }
    assert "advancement_skeleton" not in created["character_sheet"]["locked_choices"]
    saved = ProjectStore(db).get_project(created["project_id"])
    locks = {row["field"]: row["value"] for row in saved["project"]["user_locks"]}
    assert locks["character_sheet.planning_preferences"] == created["character_sheet"]["planning_preferences"]
    assert "advancement_skeleton" not in locks["character_sheet.locked_choices"]

    prompt = Stage1ClipboardService(db).generate_prompt(created["project_id"])
    slot = next(row for row in prompt["envelope"]["decision_slots"] if row["slot_id"] == "advancement_skeleton")
    assert slot["max_selections"] is None
    assert "required_choice_ids" not in slot
    assert [row["choice_id"] for row in slot["choices"][:len(talents)]] == talents
    assert len(slot["choices"]) > 8
    assert '"max_selections":null' in prompt["prompt_text"]

    decisions = []
    for decision_slot in prompt["envelope"]["decision_slots"]:
        required = decision_slot.get("required_choice_ids") or []
        if decision_slot["coverage_state"] == "blocked_missing_authority":
            decisions.append({
                "slot_id": decision_slot["slot_id"],
                "state": "blocked_missing_authority",
                "choice_ids": [],
                "reason_code": decision_slot["blocked_reason_code"],
                "reason": decision_slot["blocked_reason"],
            })
        elif required:
            decisions.append({"slot_id": decision_slot["slot_id"], "state": "selected", "choice_ids": required})
        elif decision_slot["allow_none"]:
            decisions.append({
                "slot_id": decision_slot["slot_id"],
                "state": "explicit_none",
                "choice_ids": [],
                "reason_code": "legal_none",
                "reason": "Left open for later Factory completion.",
            })
        else:
            decisions.append({
                "slot_id": decision_slot["slot_id"],
                "state": "selected",
                "choice_ids": [decision_slot["choices"][0]["choice_id"]],
            })
    diagnostics = Stage1ClipboardService._decision_diagnostics({"decisions": decisions}, prompt["envelope"])
    assert "SLOT_CARDINALITY_INVALID" not in {row["code"] for row in diagnostics}


def test_no_talent_priority_cap_text_or_schema_limit_remains():
    app_js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    index_html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    combined = app_js + "\n" + index_html
    assert "Talent priorities can lock up to 8 choices" not in combined
    assert "lock up to 8" not in combined.casefold()
    assert "choose any number of valid priorities" in app_js

    for name in (
        "Stage1_Clipboard_Response.schema.json",
        "Stage1_Clipboard_Response_v2.schema.json",
    ):
        schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
        payload_properties = schema["properties"]["response_payload"]["properties"]
        collection = payload_properties.get("decisions") or payload_properties["selections"]
        choice_ids = collection["items"]["properties"]["choice_ids"]
        assert "maxItems" not in choice_ids


def test_new_pack_lock_selects_only_current_core_2_9_3(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    actual = service._resolved_pack_locks({})
    actual_core = [row for row in actual if row["pack_id"] == CORE_PACK_ID]
    assert actual_core == [{"pack_id": CORE_PACK_ID, "version": "2.9.3"}]

    service.packs.list = lambda: [
        {"pack_id": CORE_PACK_ID, "version": "2.9.2", "authority": "canonical", "selectable": False, "record_count": 5000, "lifecycle_state": "superseded", "manifest": {"dependencies": []}},
        {"pack_id": CORE_PACK_ID, "version": "2.9.3", "authority": "canonical", "selectable": False, "record_count": 5008, "lifecycle_state": "published", "manifest": {"dependencies": []}},
    ]
    assert service._resolved_pack_locks({}) == [{"pack_id": CORE_PACK_ID, "version": "2.9.3"}]


def test_existing_2_9_2_locked_project_remains_readable(catalog_environment, tmp_path):
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "historical lock")
    created = _create_guided(CharacterBuilderService(db), name="Historical 2.9.2 Project")
    project_id = created["project_id"]
    project = deepcopy(created["project"])
    core_pack = next(row for row in project["content_lock"]["packs"] if row["pack_id"] == CORE_PACK_ID)
    core_pack["version"] = "2.9.2"
    project["content_lock"]["packs"].sort(key=lambda row: (row["pack_id"], row["version"]))
    project["content_lock"]["lock_hash"] = sha256_json({
        "catalog_build_id": project["content_lock"]["catalog_build_id"],
        "packs": project["content_lock"]["packs"],
    })
    with db.transaction() as conn:
        conn.execute(
            "UPDATE project_content_locks SET version='2.9.2' WHERE project_id=? AND pack_id=?",
            (project_id, CORE_PACK_ID),
        )
        conn.execute(
            "UPDATE projects SET project_json=?,canonical_project_hash=? WHERE project_id=?",
            (canonical_json(project), canonical_project_hash(project), project_id),
        )
    reopened = ProjectStore(db).get_project(project_id)
    locked = next(row for row in reopened["content_locks"] if row["pack_id"] == CORE_PACK_ID)
    assert locked["version"] == "2.9.2"
    assert next(row for row in reopened["project"]["content_lock"]["packs"] if row["pack_id"] == CORE_PACK_ID)["version"] == "2.9.2"


def test_authority_gap_spheres_hidden_by_disposition_not_name(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    options = service.options()
    sphere_category = next(row for row in options["categories"] if row["slot_id"] == "sphere_priorities")
    selectable_ids = {row["choice_id"] for row in sphere_category["choices"]}
    audit = options["sphere_talent_index"]["audit"]

    # CAT2 replaces the owner-facing raw projection with exactly 85 canonical
    # Spheres, so no raw authority-gap label may remain in the ordinary choice
    # set. The raw catalog itself remains preserved for diagnostics/provenance.
    assert audit["sphere_count"] == 85
    assert audit["owner_hidden_source_authority_gap_count"] == 0
    assert audit["owner_hidden_source_authority_gap_ids"] == []
    assert len(selectable_ids) == 85
    assert "tianxia.sphere.harvesting_gathering" in selectable_ids
    assert "tianxia.sphere.the_piercing_needle" in selectable_ids

    with catalog_environment["db"].connection() as conn:
        retained_count = conn.execute(
            """SELECT COUNT(*) FROM catalog_records
               WHERE json_extract(data_json, '$.compatibility.factory.raw_projection.raw_record.authority_coverage.disposition')='source_authority_gap'"""
        ).fetchone()[0]
    assert retained_count == 0
    builder_source = (ROOT / "character_builder/service.py").read_text(encoding="utf-8")
    for unresolved_name in ("Universal Martial", "Chains / Meridian", "Pressure Points / Meridian"):
        assert unresolved_name not in builder_source


def test_temporary_project_cleanup_is_explicit_project_scoped_and_repeat_safe(catalog_environment, tmp_path):
    _settings, db = _clone_catalog_db(catalog_environment, tmp_path / "lifecycle direct")
    service = CharacterBuilderService(db)
    store = ProjectStore(db)
    with db.connection() as conn:
        baseline_temporary_ids = [
            row["project_id"]
            for row in conn.execute(
                "SELECT project_id FROM character_builder_project_lifecycle WHERE persistence_state = 'temporary' ORDER BY project_id"
            ).fetchall()
        ]
    current = _create_guided(service, name="Current Temporary")
    other_id = _clone_project_row(db, current["project_id"], working_name="Other Temporary")
    saved_id = _clone_project_row(db, current["project_id"], working_name="Saved Draft")
    completed_id = _clone_project_row(db, current["project_id"], working_name="Completed Character")
    legacy_id = _clone_project_row(db, current["project_id"], working_name="Legacy Existing")
    with db.transaction() as conn:
        store._set_builder_lifecycle(conn, other_id, "temporary", source="test_fixture")
        store._set_builder_lifecycle(conn, saved_id, "saved_draft", source="owner_save_draft")
        store._set_builder_lifecycle(conn, completed_id, "completed", source="character_build_completed")

    result = store.discard_temporary_project(current["project_id"], reason="starting_over")
    assert result["discarded"] is True
    assert not _project_exists(db, current["project_id"])
    for project_id in (other_id, saved_id, completed_id, legacy_id):
        assert _project_exists(db, project_id)

    cleanup = store.cleanup_temporary_projects(reason="simulated_restart")
    assert cleanup["removed_project_ids"] == sorted(baseline_temporary_ids + [other_id])
    assert store.cleanup_temporary_projects(reason="repeat")["removed_count"] == 0
    for project_id in (saved_id, completed_id, legacy_id):
        assert _project_exists(db, project_id)
    assert store.builder_lifecycle(saved_id)["persistence_state"] == "saved_draft"
    assert store.builder_lifecycle(completed_id)["persistence_state"] == "completed"
    assert store.builder_lifecycle(legacy_id)["persistence_state"] == "legacy_persistent"

def test_normal_shutdown_removes_only_unsaved_temporary_character(catalog_environment, tmp_path):
    settings, db = _clone_catalog_db(catalog_environment, tmp_path / "shutdown cleanup")
    with TestClient(create_app(settings)) as client:
        token = client.get("/api/session").json()["token"]
        response = client.post(
            "/api/character-builder/projects",
            headers={"x-foundry-token": token},
            json={"working_name": "Shutdown Temporary", "concept": "Temporary lifecycle test"},
        )
        assert response.status_code == 200, response.text
        project_id = response.json()["project_id"]
        assert response.json()["builder_lifecycle"]["persistence_state"] == "temporary"
        assert _project_exists(db, project_id)
    assert not _project_exists(db, project_id)


def test_startup_cleans_crash_left_temporary_but_saved_and_completed_survive(catalog_environment, tmp_path):
    settings, db = _clone_catalog_db(catalog_environment, tmp_path / "startup cleanup")
    service = CharacterBuilderService(db)
    store = ProjectStore(db)
    abandoned = _create_guided(service, name="Crash Left Temporary")
    saved_id = _clone_project_row(db, abandoned["project_id"], working_name="Saved Before Crash")
    completed_id = _clone_project_row(db, abandoned["project_id"], working_name="Completed Before Crash")
    with db.transaction() as conn:
        store._set_builder_lifecycle(conn, saved_id, "saved_draft", source="owner_save_draft")
        store._set_builder_lifecycle(conn, completed_id, "completed", source="character_build_completed")

    with TestClient(create_app(settings)) as client:
        assert not _project_exists(db, abandoned["project_id"])
        assert _project_exists(db, saved_id)
        assert _project_exists(db, completed_id)
        cleanup = client.app.state.character_builder_startup_cleanup
        assert abandoned["project_id"] in cleanup["removed_project_ids"]
    assert not _project_exists(db, abandoned["project_id"])
    assert _project_exists(db, saved_id)
    assert _project_exists(db, completed_id)

def test_save_draft_action_prevents_normal_shutdown_cleanup(catalog_environment, tmp_path):
    settings, db = _clone_catalog_db(catalog_environment, tmp_path / "save draft shutdown")
    with TestClient(create_app(settings)) as client:
        token = client.get("/api/session").json()["token"]
        created = client.post(
            "/api/character-builder/projects",
            headers={"x-foundry-token": token},
            json={"working_name": "Explicit Saved Draft", "concept": "Save Draft lifecycle test"},
        )
        assert created.status_code == 200, created.text
        project_id = created.json()["project_id"]
        saved = client.post(
            f"/api/character-builder/projects/{project_id}/save-draft",
            headers={"x-foundry-token": token},
            json={},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["persistence_state"] == "saved_draft"
    assert _project_exists(db, project_id)
    assert ProjectStore(db).builder_lifecycle(project_id)["display_label"] == "Saved Draft"
