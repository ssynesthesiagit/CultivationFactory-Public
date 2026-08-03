from __future__ import annotations

import io
import json
import zipfile

import pytest

from app.core import FoundryError
from character_builder.service import CharacterBuilderService
from project_store.service import ProjectStore


def _categories(options):
    return {row["slot_id"]: row for row in options["categories"]}


def test_w5_p1r_owner_sphere_surface_is_complete_and_truthful(catalog_environment):
    builder = CharacterBuilderService(catalog_environment["db"])
    options = builder.options()
    categories = _categories(options)
    spheres = categories["sphere_priorities"]["choices"]
    talents = categories["advancement_skeleton"]["choices"]
    by_name = {row.get("canonical_name") or row["name"]: row for row in spheres}

    assert options["schema_version"] == "TianxiaFoundry.CharacterSheetOptions.v3"
    canonical_status = builder.canonical_catalog.status()
    diagnostics = builder.canonical_catalog.diagnostics()
    expected_counts = {
        "canonical_spheres": canonical_status["canonical_sphere_count"],
        "canonical_talents": canonical_status["canonical_talent_count"],
        "automatic_base_components": canonical_status["automatic_base_ability_unique_count"],
        "zero_talent_spheres": 0,
        "quarantined_records": diagnostics["quarantined"]["count"],
    }
    assert options["owner_surface_counts"] == expected_counts
    assert len(spheres) == len({row["choice_id"] for row in spheres}) == expected_counts["canonical_spheres"]
    assert len(talents) == len({row["choice_id"] for row in talents}) == expected_counts["canonical_talents"]
    assert sum(len(row.get("automatic_base_abilities") or []) for row in spheres) == expected_counts["automatic_base_components"]

    assert all(row["creator_ready"] for row in spheres)

    assert by_name["Ice"]["selectable_talent_count"] == 32
    assert by_name["Ash"]["selectable_talent_count"] == 24
    assert by_name["The Piercing Needle"]["selectable_talent_count"] == 39
    assert "Fencing" in by_name["The Piercing Needle"].get("aliases", [])

    for talent in talents:
        assert talent["owning_canonical_sphere_id"]
        assert talent["owning_canonical_sphere_name"]
        assert talent["mapping_status"] == "mapped"
        assert isinstance(talent["planning_priority_available"], bool)
        assert talent["full_description"]


def test_w5_p1r_planning_preferences_never_become_canonical_grants(catalog_environment):
    db = catalog_environment["db"]
    service = CharacterBuilderService(db)
    options = service.options()
    categories = _categories(options)
    ice = next(row for row in categories["sphere_priorities"]["choices"] if row["name"] == "Ice")
    ice_talents = [
        row for row in categories["advancement_skeleton"]["choices"]
        if row["owning_canonical_sphere_id"] == ice["choice_id"] and row["planning_priority_available"]
    ][:3]
    assert len(ice_talents) == 3

    created = service.create_project(
        working_name="W5-P1R planning preference regression",
        concept="An ice cultivator whose future direction is preferred, not pre-acquired.",
        target_cl=1,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={},
        sphere_priority_ids=[ice["choice_id"]],
        talent_priority_ids=[row["choice_id"] for row in ice_talents],
    )
    sheet = created["character_sheet"]
    assert sheet["planning_preferences"] == {
        "sphere_priority_ids": [ice["choice_id"]],
        "talent_priority_ids": [row["choice_id"] for row in ice_talents],
    }
    assert sheet["canonical_grant_plan"]["acquired_canonical_sphere_ids"] == []
    assert sheet["canonical_character_projection"]["automatic_base_abilities"] == []
    assert sheet["canonical_character_projection"]["free_sphere_talent_grants"] == []
    assert sheet["canonical_character_projection"]["ordinary_talent_ids"] == []

    store = ProjectStore(db)
    lifecycle = store.save_builder_draft(created["project_id"])
    assert lifecycle["persistence_state"] == "saved_draft"
    reopened = store.get_project(created["project_id"])["project"]
    locks = {row["field"]: row["value"] for row in reopened["user_locks"]}
    assert locks["character_sheet.planning_preferences"] == sheet["planning_preferences"]
    assert locks["character_sheet.canonical_grant_plan"]["acquired_canonical_sphere_ids"] == []

    beauty = next(row for row in categories["sphere_priorities"]["choices"] if row["name"] == "Beauty")
    assert beauty["creator_ready"] is True
    beauty_talents = [
        row for row in categories["advancement_skeleton"]["choices"]
        if row["owning_canonical_sphere_id"] == beauty["choice_id"]
    ]
    assert beauty["selectable_talent_count"] == len(beauty_talents)
    assert all(row["name"] != "Cultivation Insights" for row in beauty_talents)


def test_w5_p1r_manual_complete_response_file_parser_is_bounded():
    from character_creation.service import CharacterCreationExecutionService

    complete = json.dumps({"schema": "TianxiaFoundry.CharacterCreationPlan.v2"}).encode("utf-8")
    text, receipt = CharacterCreationExecutionService._manual_response_text("complete.json", complete)
    assert json.loads(text)["schema"] == "TianxiaFoundry.CharacterCreationPlan.v2"
    assert receipt["uploaded_filename"] == "complete.json"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("complete-response.json", complete)
    text, receipt = CharacterCreationExecutionService._manual_response_text("complete.zip", buffer.getvalue())
    assert json.loads(text)["schema"] == "TianxiaFoundry.CharacterCreationPlan.v2"
    assert receipt["response_member"] == "complete-response.json"

    with pytest.raises(FoundryError) as traversal:
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("../response.json", complete)
        CharacterCreationExecutionService._manual_response_text("bad.zip", bad.getvalue())
    assert traversal.value.code == "CG1_MANUAL_RESPONSE_ZIP_PATH_INVALID"


def test_w5_p1r_legacy_stage1_response_is_not_a_complete_cg1_plan():
    from character_creation.service import CharacterCreationExecutionService

    service = object.__new__(CharacterCreationExecutionService)
    legacy_stage1 = json.dumps({
        "schema": "TianxiaFoundry.AIClipboard.Stage1.v2",
        "prompt_id": "owner-stage1-negative-regression",
        "concept": "Blueprint intent only",
    })
    with pytest.raises(FoundryError) as rejected:
        service._parse_plan(legacy_stage1)
    assert rejected.value.code == "CG1_PLAN_SCHEMA_INVALID"
    assert "TianxiaFoundry.CharacterCreationPlan.v2" in rejected.value.message
