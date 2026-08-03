from __future__ import annotations

import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from app.core import Database, Settings
from character_builder import CharacterBuilderService
from project_store.service import ProjectStore

SPHERES = [
    "tianxia.sphere.beauty",
    "tianxia.sphere.ash",
    "tianxia.sphere.athletics",
    "tianxia.sphere.blood",
    "tianxia.sphere.dark",
]
FREE_GRANTS = {
    "tianxia.sphere.beauty": "tianxia.talent.beauty.admiring_crowd_method",
    "tianxia.sphere.ash": "tianxia.talent.ash.ash_ward",
    "tianxia.sphere.athletics": "TAL_ATHLETICS_WALL_STUNT",
    "tianxia.sphere.blood": "tianxia.talent.blood.blood_armament",
    "tianxia.sphere.dark": "TAL_DARK_BLACK_LUNG",
}
ORDINARY = [
    "tianxia.talent.ash.burial_ground",
    "TAL_ATHLETICS_AIR_STUNT",
    "tianxia.talent.blood.blood_puppet",
]
SPARROW = "TAL_ATHLETICS_SPARROW_S_PATH"
# Paired Resonance retains a genuinely unresolved acquisition requirement
# ("two non-Qiweaving spheres").  Creeping Lethargy is fully typed after the
# R2 field-boundary repair and therefore must no longer serve as a fail-closed
# fixture.
UNRESOLVED = "TAL_QIWEAVING_PAIRED_RESONANCE"
PRIORITY_TALENTS = [
    "tianxia.talent.beauty.admiring_crowd_method",
    "tianxia.talent.ash.burial_ground",
    "TAL_ATHLETICS_WALL_STUNT",
    "TAL_ATHLETICS_AIR_STUNT",
    SPARROW,
    "tianxia.talent.blood.blood_puppet",
]
PREREQUISITE_CHAIN_TALENT = "TAL_ATHLETICS_AIR_STUNT"
RESTRICTED_TALENT = "tianxia.talent.blood.blood_puppet"


def _clone_catalog_database(source_db: Database, target_settings: Settings) -> Database:
    target_settings.ensure_dirs()
    source = sqlite3.connect(source_db.settings.db_path)
    target = sqlite3.connect(target_settings.db_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    source_security = source_db.settings.data_dir / "security"
    target_security = target_settings.data_dir / "security"
    if source_security.is_dir():
        shutil.copytree(source_security, target_security, dirs_exist_ok=True, copy_function=shutil.copy2)
    cloned = Database(target_settings)
    cloned.migrate()
    return cloned


def _lock_map(wrapper: dict[str, Any]) -> dict[str, Any]:
    return {row["field"]: row["value"] for row in wrapper["project"]["user_locks"]}


def _talent_map(catalog) -> dict[str, dict[str, Any]]:
    return {row["canonical_talent_id"]: row for row in catalog.list_talents()["records"]}


def _disposition(projection: dict[str, Any], talent_id: str) -> dict[str, Any]:
    return next(row for row in projection["talent_dispositions"] if row["canonical_talent_id"] == talent_id)


def _runtime_base_components(catalog) -> list[dict[str, Any]]:
    return [
        component
        for sphere in catalog.list_spheres(include_full=False)["records"]
        for component in sphere["automatic_base_abilities"]
    ]


def run_cat3_p1r_persistence_acceptance(
    source_db: Database,
    *,
    target_settings: Settings,
) -> dict[str, Any]:
    """Execute the CAT3-P1R save/reopen/export/clean-import authority proof."""

    # Clone only the clean catalog/runtime foundation before the source project is
    # created. The target therefore receives the project solely through import.
    target_db = _clone_catalog_database(source_db, target_settings)
    source_builder = CharacterBuilderService(source_db)
    source_catalog = source_builder.canonical_catalog
    target_catalog = CharacterBuilderService(target_db).canonical_catalog

    source_status = source_catalog.status()
    target_status_before = target_catalog.status()
    assert source_status["automatic_base_ability_source_row_count"] == 126
    assert source_status["automatic_base_ability_unique_count"] == 125
    assert target_status_before == source_status

    project_id = str(uuid.uuid4())
    created = source_builder.create_project(
        working_name="CAT3-P1R persistence proof",
        concept="Exact canonical save, reopen, export, clean import, and revalidation proof.",
        target_cl=7,
        power_band="standard",
        source_reference="CAT3-P1R acceptance fixture",
        creation_mode="detailed",
        ability_scores={},
        selections={},
        sphere_priority_ids=SPHERES,
        talent_priority_ids=PRIORITY_TALENTS,
        canonical_sphere_ids=SPHERES,
        sphere_free_talent_grants=FREE_GRANTS,
        ordinary_talent_ids=ORDINARY,
        project_id_override=project_id,
    )
    assert created["project"]["project_id"] == project_id
    source_builder.projects.save_builder_draft(project_id)

    # Save, close, and reopen through a fresh Database/ProjectStore instance.
    reopened_source_store = ProjectStore(Database(source_db.settings))
    reopened_source = reopened_source_store.get_project(project_id)
    source_locks = _lock_map(reopened_source)
    source_plan = source_locks["character_sheet.canonical_grant_plan"]
    source_character_projection = source_locks["character_sheet.canonical_character_projection"]
    source_preferences = source_locks["character_sheet.planning_preferences"]

    assert source_preferences == {
        "sphere_priority_ids": SPHERES,
        "talent_priority_ids": PRIORITY_TALENTS,
    }
    assert source_plan["acquired_canonical_sphere_ids"] == SPHERES
    assert {row["sphere_id"]: row["talent_id"] for row in source_plan["grant_accounting"]["free_sphere_talent_grants"]} == FREE_GRANTS
    assert source_plan["grant_accounting"]["ordinary_talent_ids"] == ORDINARY
    assert source_plan["grant_accounting"]["double_count_detected"] is False
    selected_ids = set(FREE_GRANTS.values()).union(ORDINARY)
    assert source_plan["grant_accounting"]["total_distinct_talent_ids"] == len(selected_ids)

    source_selected_dispositions = {
        row["canonical_talent_id"]: row for row in source_plan["selected_talent_dispositions"]
    }
    prerequisite_disposition = source_selected_dispositions[PREREQUISITE_CHAIN_TALENT]
    prerequisite_results = prerequisite_disposition["prerequisite_evaluation"]["predicate_results"]
    assert any(row["kind"] == "talent" and row["passed"] for row in prerequisite_results)

    restricted_provenance = [
        row for row in source_plan["grant_accounting"]["acquisition_provenance"]
        if row["canonical_content_id"] == RESTRICTED_TALENT
    ]
    assert len(restricted_provenance) == 1
    assert restricted_provenance[0]["source"] == "pending-trusted-initial-finalization"
    assert restricted_provenance[0]["recorded"] is False
    assert restricted_provenance[0]["issuance_route"] == "initial_character_finalization"

    source_unresolved_projection = source_catalog.creator_projection_for_initial_creation(
        target_cl=7,
        acquired_sphere_ids=SPHERES,
        free_talent_grants=FREE_GRANTS,
        ordinary_talent_ids=[*ORDINARY, UNRESOLVED],
    )
    source_unresolved = _disposition(source_unresolved_projection, UNRESOLVED)
    assert source_unresolved_projection["ready"] is False
    assert source_unresolved["disposition"] == "locked_by_unresolved_prerequisite"
    assert any(
        row["kind"] == "unresolved" and not row["passed"]
        for row in source_unresolved["prerequisite_evaluation"]["predicate_results"]
    )

    source_talents = _talent_map(source_catalog)
    exact_authority_snapshot = {
        talent_id: {
            "canonical_talent_id": source_talents[talent_id]["canonical_talent_id"],
            "owning_canonical_sphere_id": source_talents[talent_id]["owning_canonical_sphere_id"],
            "typed_prerequisites": source_talents[talent_id]["typed_prerequisites"],
            "prerequisite_evaluation_status": source_talents[talent_id]["prerequisite_evaluation_status"],
            "creator_selectability_can_be_evaluated_safely": source_talents[talent_id]["creator_selectability_can_be_evaluated_safely"],
            "source_provenance": source_talents[talent_id]["source_provenance"],
        }
        for talent_id in (PREREQUISITE_CHAIN_TALENT, RESTRICTED_TALENT, UNRESOLVED)
    }

    export = reopened_source_store.export_project(project_id, "cat3-p1r-persistence-proof.tianxia-project.zip")
    assert export["exported"] is True
    package = Path(export["path"])
    assert package.is_file()

    imported_store = ProjectStore(target_db)
    imported = imported_store.import_project(package)
    assert imported["imported"] is True
    assert imported["project_id"] == project_id
    assert imported["project_hash"] == export["project_hash"]
    assert imported["state_hash"] == export["state_hash"]
    assert imported["event_count"] == export["event_count"]

    # Close and reopen the clean target after import.
    reopened_target_db = Database(target_settings)
    reopened_target_db.migrate()
    reopened_target_store = ProjectStore(reopened_target_db)
    imported_wrapper = reopened_target_store.get_project(project_id)
    imported_locks = _lock_map(imported_wrapper)
    imported_plan = imported_locks["character_sheet.canonical_grant_plan"]
    imported_character_projection = imported_locks["character_sheet.canonical_character_projection"]
    imported_preferences = imported_locks["character_sheet.planning_preferences"]

    assert imported_preferences == source_preferences
    assert imported_plan == source_plan
    assert imported_character_projection == source_character_projection
    assert imported_wrapper["project"]["content_lock"] == reopened_source["project"]["content_lock"]
    assert reopened_target_store.replay(project_id)["state_hash"] == reopened_source_store.replay(project_id)["state_hash"]

    target_catalog_after = CharacterBuilderService(reopened_target_db).canonical_catalog
    target_status_after = target_catalog_after.status()
    assert target_status_after == source_status
    assert target_status_after["automatic_base_ability_unique_count"] == 125

    target_components = _runtime_base_components(target_catalog_after)
    target_component_ids = [row["runtime_component_id"] for row in target_components]
    assert len(target_components) == 125
    assert len(target_component_ids) == len(set(target_component_ids))
    target_darkness = [
        row for row in target_components
        if row["mapped_canonical_sphere_id"] == "tianxia.sphere.dark" and row["display_name"] == "Darkness"
    ]
    assert len(target_darkness) == 1
    assert target_darkness[0]["runtime_component_id"] == "DARK_BASE_DARKNESS"

    # Unresolved records are deliberately not persisted as selectable planning
    # priorities. Re-evaluate the exact catalog record after import instead.
    assert UNRESOLVED not in imported_preferences["talent_priority_ids"]
    imported_unresolved_id = UNRESOLVED
    target_unresolved_projection = target_catalog_after.creator_projection_for_initial_creation(
        target_cl=7,
        acquired_sphere_ids=imported_plan["acquired_canonical_sphere_ids"],
        free_talent_grants={
            row["sphere_id"]: row["talent_id"]
            for row in imported_plan["grant_accounting"]["free_sphere_talent_grants"]
        },
        ordinary_talent_ids=[*imported_plan["grant_accounting"]["ordinary_talent_ids"], imported_unresolved_id],
    )
    target_unresolved = _disposition(target_unresolved_projection, imported_unresolved_id)
    assert target_unresolved_projection["ready"] is False
    assert target_unresolved == source_unresolved

    target_talents = _talent_map(target_catalog_after)
    imported_authority_snapshot = {
        talent_id: {
            "canonical_talent_id": target_talents[talent_id]["canonical_talent_id"],
            "owning_canonical_sphere_id": target_talents[talent_id]["owning_canonical_sphere_id"],
            "typed_prerequisites": target_talents[talent_id]["typed_prerequisites"],
            "prerequisite_evaluation_status": target_talents[talent_id]["prerequisite_evaluation_status"],
            "creator_selectability_can_be_evaluated_safely": target_talents[talent_id]["creator_selectability_can_be_evaluated_safely"],
            "source_provenance": target_talents[talent_id]["source_provenance"],
        }
        for talent_id in exact_authority_snapshot
    }
    assert imported_authority_snapshot == exact_authority_snapshot

    imported_selected_ids = {
        row["talent_id"] for row in imported_plan["grant_accounting"]["free_sphere_talent_grants"]
    }.union(imported_plan["grant_accounting"]["ordinary_talent_ids"])
    assert imported_selected_ids == selected_ids
    assert imported_plan["grant_accounting"]["total_distinct_talent_ids"] == len(imported_selected_ids)
    assert imported_plan["grant_accounting"]["double_count_detected"] is False

    return {
        "schema": "TianxiaFactory.CAT3P1RCleanExportImportPersistenceAcceptance.v1",
        "status": "PASS",
        "project_id": project_id,
        "export": export,
        "import": imported,
        "source_catalog_status": source_status,
        "target_catalog_status": target_status_after,
        "stable_ids": {
            "sphere_priority_ids": imported_preferences["sphere_priority_ids"],
            "talent_priority_ids": imported_preferences["talent_priority_ids"],
            "acquired_sphere_ids": imported_plan["acquired_canonical_sphere_ids"],
            "selected_talent_ids": sorted(imported_selected_ids),
        },
        "prerequisite_chain": prerequisite_disposition,
        "unresolved_disposition": target_unresolved,
        "restricted_initial_provenance": restricted_provenance[0],
        "automatic_base_components": {
            "source_rows": target_status_after["automatic_base_ability_source_row_count"],
            "unique_runtime_components": len(target_components),
            "darkness_rows": target_darkness,
        },
        "integrity": {
            "project_hash_equal": imported["project_hash"] == export["project_hash"],
            "state_hash_equal": imported["state_hash"] == export["state_hash"],
            "event_count_equal": imported["event_count"] == export["event_count"],
            "content_lock_equal": imported_wrapper["project"]["content_lock"] == reopened_source["project"]["content_lock"],
            "grant_plan_equal": imported_plan == source_plan,
            "character_projection_equal": imported_character_projection == source_character_projection,
            "authority_snapshot_equal": imported_authority_snapshot == exact_authority_snapshot,
            "duplicate_grants": False,
            "silent_prerequisite_loss": False,
        },
    }


def test_cat3_p1r_clean_save_reopen_and_export_import(catalog_environment, tmp_path: Path):
    report = run_cat3_p1r_persistence_acceptance(
        catalog_environment["db"],
        target_settings=Settings.from_env(Path(__file__).resolve().parents[1], tmp_path / "clean-import-target"),
    )
    assert report["status"] == "PASS"
