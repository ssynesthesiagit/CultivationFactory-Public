from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ai_provider.secrets import InMemorySecretStore
from ai_provider.service import (
    AIProviderService,
    BUILD_DEBRIEF_RESPONSE_SCHEMA,
    BUILD_DEBRIEF_SCHEMA_NAME,
)
from app.core import FoundryError, canonical_json
from factory_authoring.command5_profile import GM_SCREEN_TAB_CONTRACT, CharacterGMCommand5Profile
from gm2_contract.adapter import _migrate_fire
from portable_character.service import _project_model_overlay


def _command4_workspace(root: Path) -> None:
    files = {
        "Training_Sources.json": {"training_sources": []},
        "Composite_Playbooks.json": {"playbooks": []},
        "Dao_I_Ching_GM_Authoring.json": {
            "classification": "OWNER_RATIFIED_GM_AUTHORING",
            "dao": {"mechanical_effects": []},
            "i_ching": {"mechanical_effects": []},
        },
        "Descriptive_AI_Behavior.json": {
            "not_executable_controller_policy": True,
            "controller_policy_registered": False,
        },
    }
    for name, value in files.items():
        path = root / "Command_4" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(value), encoding="utf-8")


def _sheet_response(
    *,
    with_advanced: bool,
    current_cl: int = 5,
    advancement_levels: list[dict] | None = None,
    immortal_none_state: dict | None = None,
) -> dict:
    snapshot = {
        "identity": {"character_id": "c1", "display_name": "Cinder", "concept": "A test character."},
        "current_cl": current_cl,
        "ability_scores_and_statistics": {"primary_resource": None},
        "advancement_history": {"levels": deepcopy(advancement_levels or [])},
        "background_and_origin": {"background_id": "background.test"},
        "path_and_subpath": {"path_id": "path.test", "subpath_id": "subpath.test"},
        "spheres_and_talents": {
            "sphere_ids": ["sphere.test"],
            "talent_ids": ["talent.test"],
            "cultivation_insight_record_ids": ["insight.test"],
            "cultivation_insight_occurrences": [{"occurrence_id": "occurrence.test", "record_id": "insight.test"}],
        },
        "selected_record_sections": {},
        "owner_facing_action_feature_index": [],
        "section_provenance": {},
        "explicit_none_systems": {
            "manuals": {"state": "none", "source_backed": True},
            "forged_techniques": {"state": "none", "source_backed": True},
            "immortal_arts": deepcopy(immortal_none_state or {"state": "not_projected", "source_backed": False}),
            "foundation": {"state": "none", "source_backed": True},
            "method": {"state": "none", "source_backed": True},
            "equipment": {"state": "none", "source_backed": True},
        },
    }
    if with_advanced:
        snapshot["advanced_systems"] = {
            "recorded_arts": {"entries": [{"record_id": "manual.test", "display_name": "Recorded Test Art"}]},
            "forged_techniques": {"entries": [{"record_id": "forged.test", "display_name": "Forged Test Technique"}]},
            "immortal_arts": {"entries": [{"record_id": "immortal.test", "display_name": "Immortal Test Art"}]},
        }
    return {"owner_character_sheet": snapshot, "sheet_artifact": {"sha256": "s" * 64}}


def _command5_models(
    tmp_path: Path,
    *,
    with_advanced: bool,
    current_cl: int = 5,
    advancement_levels: list[dict] | None = None,
    immortal_none_state: dict | None = None,
):
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    profile = CharacterGMCommand5Profile.__new__(CharacterGMCommand5Profile)
    return profile._models(
        project={"project_id": "project.test", "revision": 1},
        sheet_response=_sheet_response(
            with_advanced=with_advanced,
            current_cl=current_cl,
            advancement_levels=advancement_levels,
            immortal_none_state=immortal_none_state,
        ),
        workspace_root=workspace,
        workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
        profile={"profile_version": "test"},
        profile_contract_sha="p" * 64,
        command4={"status": "PASS"},
    )


def test_command5_publishes_ordered_tabs_and_source_backed_advanced_arrays(tmp_path: Path) -> None:
    gm_model, view, tabs = _command5_models(tmp_path, with_advanced=True, current_cl=15)
    expected_ids = [tab_id for tab_id, _label in GM_SCREEN_TAB_CONTRACT]
    assert [row["tab_id"] for row in tabs["rows"]] == expected_ids
    assert tabs["required_tabs"] == expected_ids
    by_id = {row["tab_id"]: row["value"] for row in tabs["rows"]}
    assert by_id["insights"]["cultivation_insight_record_ids"] == ["insight.test"]
    assert by_id["dao-i-ching"]["dao"] == {"mechanical_effects": []}
    assert gm_model["recorded_arts"] == [{"record_id": "manual.test", "display_name": "Recorded Test Art"}]
    assert gm_model["forged_techniques"] == [{"record_id": "forged.test", "display_name": "Forged Test Technique"}]
    assert gm_model["immortal_arts"] == [{"record_id": "immortal.test", "display_name": "Immortal Test Art"}]
    assert view["paths_subpaths"] == gm_model["paths_subpaths"]
    assert view["insights"] == gm_model["insights"]
    assert view["spirit_companions"] == gm_model["spirit_companions"]
    assert view["immortal_arts"] == gm_model["immortal_arts"]
    assert view["immortal_arts_none_state"]["state"] == "not_applicable"


def test_command5_preserves_explicit_none_state_for_unprojected_advanced_arrays(tmp_path: Path) -> None:
    gm_model, _view, tabs = _command5_models(tmp_path, with_advanced=False)
    assert gm_model["recorded_arts"] == []
    assert gm_model["forged_techniques"] == []
    assert gm_model["immortal_arts"] == []
    assert gm_model["recorded_arts_none_state"]["state"] == "none"
    assert gm_model["forged_techniques_none_state"]["state"] == "none"
    assert gm_model["immortal_arts_none_state"] == {
        "state": "locked_by_minimum_cl",
        "source_backed": True,
        "minimum_cl": 15,
        "current_cl": 5,
    }
    by_id = {row["tab_id"]: row["value"] for row in tabs["rows"]}
    assert by_id["insights"] != by_id["paths-subpaths"]


def test_command5_locks_source_immortal_arts_below_minimum_cl(tmp_path: Path) -> None:
    gm_model, view, tabs = _command5_models(tmp_path, with_advanced=True, current_cl=14)
    assert gm_model["immortal_arts"] == []
    assert gm_model["immortal_arts_none_state"] == {
        "state": "locked_by_minimum_cl",
        "source_backed": True,
        "minimum_cl": 15,
        "current_cl": 14,
    }
    assert view["immortal_arts"] == []
    assert view["immortal_arts_none_state"]["state"] == "locked_by_minimum_cl"
    by_id = {row["tab_id"]: row["value"] for row in tabs["rows"]}
    assert by_id["immortal-arts"] == []


def test_command5_does_not_treat_planned_cl_as_attained_for_immortal_arts(tmp_path: Path) -> None:
    gm_model, _view, _tabs = _command5_models(
        tmp_path,
        with_advanced=True,
        current_cl=14,
        advancement_levels=[{"cl": 15, "status": "planned"}],
    )
    assert gm_model["immortal_arts"] == []
    assert gm_model["immortal_arts_none_state"] == {
        "state": "locked_by_minimum_cl",
        "source_backed": True,
        "minimum_cl": 15,
        "current_cl": 14,
    }


def test_command5_normalizes_stale_immortal_lock_at_unlock_cl(tmp_path: Path) -> None:
    gm_model, view, _tabs = _command5_models(
        tmp_path,
        with_advanced=False,
        current_cl=15,
        immortal_none_state={
            "state": "locked_by_minimum_cl",
            "source_backed": True,
            "minimum_cl": 15,
            "current_cl": 14,
        },
    )
    expected = {"state": "none", "source_backed": True, "minimum_cl": 15, "current_cl": 15}
    assert gm_model["immortal_arts"] == []
    assert gm_model["immortal_arts_none_state"] == expected
    assert view["immortal_arts_none_state"] == expected


def test_command5_dao_sidecar_keeps_consumer_root_keys_and_authored_rows(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    profile = CharacterGMCommand5Profile.__new__(CharacterGMCommand5Profile)

    class _ProjectionStub:
        def artifact(self, _project_id: str, name: str) -> Path:
            path = tmp_path / name
            path.write_text("{}", encoding="utf-8")
            return path

    profile.projections = _ProjectionStub()
    profile._validate_models = lambda _gm_model, _view, _tabs: {"valid": True}
    surfaces = profile._surfaces(
        project={"project_id": "project.test", "revision": 1},
        sheet_response=_sheet_response(with_advanced=False),
        workspace_root=workspace,
        workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
        profile={"profile_version": "test"},
        profile_contract_sha="p" * 64,
        command4={"status": "PASS"},
    )
    sidecar = surfaces["Dao_IChing_Combat_Profile.json"]
    assert sidecar["dao"]["mechanical_effects"] == []
    assert sidecar["i_ching"]["mechanical_effects"] == []
    assert sidecar["dao_i_ching"]["dao"] == sidecar["dao"]
    assert sidecar["execution_authority"] is False


# Required keys of the pinned vendor view schema HF05ZVK_R1H_Phase2I_HF2/04_SCHEMAS/gm_character_view_model.schema.json
# (frozen with the bundled Factory archive). Every finalize validates the view against it in _validate_models.
PINNED_VIEW_REQUIRED = (
    "schema_version", "identity", "core_stats", "leveling_ledger", "background_origin", "spheres_talents", "actions",
    "composites", "forged_techniques", "preserved_forged_expressions", "emergency_technique_seeds", "martial_manuals",
    "foundation", "method", "dao_i_ching", "equipment_resources_states", "diagnostics", "validation",
)


def command5_view(tmp_path: Path) -> dict:
    """The GM view model _surfaces() hands to _validate_models."""
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    profile = CharacterGMCommand5Profile.__new__(CharacterGMCommand5Profile)

    class _ProjectionStub:
        def artifact(self, _project_id: str, name: str) -> Path:
            path = tmp_path / name
            path.write_text("{}", encoding="utf-8")
            return path

    seen = {}
    profile.projections = _ProjectionStub()
    profile._validate_models = lambda _gm_model, view, _tabs: seen.setdefault("view", view) and {"valid": True}
    profile._surfaces(
        project={"project_id": "project.test", "revision": 1},
        sheet_response=_sheet_response(with_advanced=False),
        workspace_root=workspace,
        workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
        profile={"profile_version": "test"},
        profile_contract_sha="p" * 64,
        command4={"status": "PASS"},
    )
    return seen["view"]


def test_command5_view_has_every_key_the_pinned_view_schema_requires(tmp_path: Path) -> None:
    # 2026-10-17: composite playbooks were removed and the view dropped "composites", so every finalize stopped at
    # CHARACTER_GM_COMMAND5_AUDIT_FAILED (GM_VIEW_MODEL_PINNED_SCHEMA_ERROR). Other tests stub _validate_models.
    view = command5_view(tmp_path)
    assert [key for key in PINNED_VIEW_REQUIRED if key not in view] == []
    assert view["composites"] == []


def _candidate_model() -> dict:
    return {
        "identity": {"display_name": "Cinder", "concept": "Candidate"},
        "cultivation": {
            "cultivation_level": 10,
            "paths": [{"path_id": "tianxia.path.qi_cultivation", "attainment_level": 10, "advancement_state": "advancing", "primary": True}],
            "resources": [{"stable_id": "qi", "current": 2, "maximum": 10}],
        },
        "methods": [],
    }


def test_non_sphere_empty_path_overlay_preserves_candidate_and_positive_overlay_wins() -> None:
    candidate = _candidate_model()
    blank_state = {
        "primary_method_id": None,
        "target_cl": 10,
        "readiness": "READY",
        "paths": [
            {"path_id": "tianxia.path.body_refining", "attainment": 0},
            {"path_id": "tianxia.path.qi_cultivation", "attainment": 0},
            {"path_id": "tianxia.path.spirit_awakening", "attainment": 0},
        ],
        "active_path_ids": [],
    }
    preserved = _project_model_overlay(deepcopy(candidate), {}, blank_state, candidate_sha256="c" * 64)
    assert preserved["cultivation"]["cultivation_level"] == 10
    assert preserved["cultivation"]["paths"] == candidate["cultivation"]["paths"]

    positive_state = deepcopy(blank_state)
    positive_state["paths"][1] = {"path_id": "tianxia.path.qi_cultivation", "attainment": 3, "primary": True}
    projected = _project_model_overlay(deepcopy(candidate), {}, positive_state, candidate_sha256="c" * 64)
    assert projected["cultivation"]["cultivation_level"] == 3
    assert next(row for row in projected["cultivation"]["paths"] if row["path_id"] == "tianxia.path.qi_cultivation")["attainment_level"] == 3


def test_non_sphere_active_zero_path_overlay_merges_only_explicit_marker() -> None:
    candidate = _candidate_model()
    candidate["cultivation"]["paths"].append({"path_id": "tianxia.path.body_refining", "attainment_level": 6, "advancement_state": "advancing", "primary": False})
    state = {
        "primary_method_id": None,
        "target_cl": 10,
        "readiness": {"status": "READY"},
        "paths": [
            {"path_id": "tianxia.path.qi_cultivation", "attainment": 0, "primary": True},
            {"path_id": "tianxia.path.body_refining", "attainment": 0},
        ],
        "active_path_ids": ["tianxia.path.qi_cultivation"],
    }
    projected = _project_model_overlay(deepcopy(candidate), {}, state, candidate_sha256="c" * 64)
    assert projected["cultivation"]["cultivation_level"] == 10
    projected_by_id = {row["path_id"]: row for row in projected["cultivation"]["paths"]}
    candidate_by_id = {row["path_id"]: row for row in candidate["cultivation"]["paths"]}
    assert projected_by_id["tianxia.path.body_refining"] == candidate_by_id["tianxia.path.body_refining"]
    assert projected_by_id["tianxia.path.qi_cultivation"]["active"] is True
    assert projected_by_id["tianxia.path.qi_cultivation"]["attainment_level"] == candidate_by_id["tianxia.path.qi_cultivation"]["attainment_level"]


def _fire_selected(model: dict) -> dict:
    return {
        "model": model,
        "path": "Tianxia_GM_Character_Model_v1.json",
        "model_sha256": "m" * 64,
        "manifest": {},
        "profile": "fire_qi_c2c1_v1",
        "runtime_package": False,
    }


def _fire_model() -> dict:
    return {
        "schema_version": "Tianxia_GM_Character_Model_v1",
        "metadata": {"project_id": "project.fire"},
        "identity": {
            "display_name": "Cinder",
            "cultivation_level": 15,
            "path": "Body Refining",
            "key_ability": "CON",
            "path_id": "tianxia.path.body_refining",
        },
        "stats": {
            "abilities": [],
            "skills": [],
            "hit_points": {"build_state_current": 155, "maximum": 155},
            "armor_class": {"value": 12},
            "speed": {"walking_ft": 30},
            "primary_resource": {
                "name": "Stamina",
                "build_state_current": 1,
                "maximum": 45,
                "definitions": [{"resource_id": "tianxia.resource.stamina", "name": "Stamina", "current": 1, "max": 45}],
            },
        },
        "paths_subpaths_insights": {"path": {"display_name": "Body Refining", "key_ability": "CON"}},
        "spheres_talents": {
            "sphere_record_ids": [],
            "learned_talent_record_ids": [],
            "automatic_sphere_component_receipts": [{
                "parent_sphere_id": "tianxia.sphere.body_refining",
                "components": [{"component_id": "BODY_BASE_TEST", "display_name": "Body Base Test"}],
            }],
        },
        "actions": [],
        "method": {"record_id": "METHOD-081", "display_name": "Outer Court Twin-Current Primer", "state": "acquired", "status": "acquired"},
        "foundation": {"record_id": "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR", "display_name": "Empty Bowl Soul Anchor", "state": "acquired", "status": "acquired"},
        "recorded_arts": [],
        "forged_techniques": [],
        "equipment_resources_states": {
            "equipment": {"state": "none", "source_backed": True},
            "states": {"status": "PENDING_COMBAT_EXECUTION", "typed_definitions": []},
        },
        "spirit_companions": {"state": "none", "entries": []},
    }


def test_fire_migration_preserves_authoritative_method_foundation_resource_and_typed_none() -> None:
    model = _fire_model()
    migrated, _mappings, _omissions = _migrate_fire(_fire_selected(model), "p" * 64)

    assert migrated["methods"][0]["stable_id"] == "METHOD-081"
    assert migrated["cultivation"]["primary_method"]["state"] == "present"
    assert migrated["field_states"]["current_primary_method"]["state"] == "present"
    assert migrated["cultivation"]["foundation"]["state"] == "present"
    assert migrated["cultivation"]["foundation"]["value"] == "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR"
    assert migrated["cultivation"]["foundation_expressions"][0]["name"] == "Empty Bowl Soul Anchor"
    assert migrated["equipment"] == [] and migrated["states"] == []
    assert migrated["field_states"]["automatic_base_abilities"]["state"] == "present"
    resource = migrated["cultivation"]["resources"][0]
    assert (resource["stable_id"], resource["name"], resource["current"], resource["maximum"]) == (
        "tianxia.resource.stamina", "Stamina", 1, 45
    )

    model["equipment_resources_states"]["equipment"] = [{"record_id": "equipment.real", "display_name": "Real Equipment"}]
    model["equipment_resources_states"]["states"] = {"status": "active", "typed_definitions": [{"record_id": "state.real", "display_name": "Real State"}]}
    migrated_with_rows, _mappings, _omissions = _migrate_fire(_fire_selected(model), "p" * 64)
    assert [row["stable_id"] for row in migrated_with_rows["equipment"]] == ["equipment.real"]
    assert [row["stable_id"] for row in migrated_with_rows["states"]] == ["state.real"]
    assert migrated_with_rows["field_states"]["automatic_base_abilities"]["state"] == "present"


@pytest.mark.parametrize("reverse_definitions", [False, True])
def test_fire_migration_and_project_overlay_keep_native_pools_separate(reverse_definitions: bool) -> None:
    model = _fire_model()
    definitions = [
        {"resource_id": "tianxia.resource.resonance", "name": "Resonance", "current": 2, "max": 46},
        {"resource_id": "tianxia.resource.stamina", "name": "Stamina", "current": 1, "max": 34},
    ]
    model["stats"]["primary_resource"] = {
        "name": "Resonance", "build_state_current": 2, "maximum": 46,
        "definitions": list(reversed(definitions)) if reverse_definitions else definitions,
    }
    migrated, _, _ = _migrate_fire(_fire_selected(model), "p" * 64)
    state = {
        "readiness": "READY",
        "paths": [
            {"path_id": "tianxia.path.body_refining", "attainment": 20,
             "resource": {"resource_id": "tianxia.resource.stamina", "name": "Stamina", "active": True, "current": None, "maximum": None}},
            {"path_id": "tianxia.path.spirit_awakening", "attainment": 20,
             "resource": {"resource_id": "tianxia.resource.resonance", "name": "Resonance", "active": True, "current": None, "maximum": None}},
        ],
    }
    overlaid = _project_model_overlay(migrated, {}, {"state": state}, candidate_sha256="p" * 64)
    expected = {
        "tianxia.resource.stamina": ("tianxia.path.body_refining", 1, 34),
        "tianxia.resource.resonance": ("tianxia.path.spirit_awakening", 2, 46),
    }
    for result in (migrated, overlaid):
        assert {row["stable_id"]: (row["path_id"], row["current"], row["maximum"])
                for row in result["cultivation"]["resources"]} == expected


def test_command5_master_ledger_drives_method_foundation_into_all_model_rows(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    profile = CharacterGMCommand5Profile.__new__(CharacterGMCommand5Profile)
    master = {
        "foundation": {"record_id": "FOUNDATION_ROOT", "display_name": "Root Foundation", "state": "acquired"},
        "method": {"record_id": "METHOD_ROOT", "display_name": "Root Method", "state": "acquired"},
    }
    gm_model, view, tabs = profile._models(
        project={"project_id": "project.test", "revision": 1},
        sheet_response=_sheet_response(with_advanced=False, current_cl=15),
        workspace_root=workspace,
        workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
        profile={"profile_version": "test"},
        profile_contract_sha="p" * 64,
        command4={"status": "PASS"},
        master=master,
    )
    assert gm_model["foundation"] == master["foundation"]
    assert gm_model["method"] == master["method"]
    assert view["foundation"] == master["foundation"]
    assert view["method"] == master["method"]
    by_tab = {row["tab_id"]: row["value"] for row in tabs["rows"]}
    assert by_tab["foundation"] == master["foundation"]
    assert by_tab["method"] == master["method"]

    explicit_none = {"foundation": {"state": "none", "source_backed": True}, "method": {"state": "none", "source_backed": True}}
    gm_none, _view_none, _tabs_none = profile._models(
        project={"project_id": "project.test", "revision": 1},
        sheet_response=_sheet_response(with_advanced=False, current_cl=15),
        workspace_root=workspace,
        workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
        profile={"profile_version": "test"},
        profile_contract_sha="p" * 64,
        command4={"status": "PASS"},
        master=explicit_none,
    )
    assert gm_none["foundation"] == explicit_none["foundation"]
    assert gm_none["method"] == explicit_none["method"]


def _command5_selected_method_foundation_fixture() -> tuple[dict, dict]:
    sheet_response = _sheet_response(with_advanced=False, current_cl=15)
    snapshot = sheet_response["owner_character_sheet"]
    source = {
        "path": "authority/selected-records.json",
        "anchor": "selected:method-foundation",
        "sha256": "s" * 64,
    }
    snapshot["method"] = {
        "record_id": "METHOD_SELECTED",
        "record_hash": "m" * 64,
        "display_name": "Selected Method",
        "state": "acquired",
        "mechanical_projection": {"source": "owner-sheet"},
        "full_description": "Authenticated selected method rules.",
        "full_description_source": "locked_typed_catalog_record",
        "source": deepcopy(source),
        "source_path": source["path"],
        "source_anchor": source["anchor"],
        "source_hash": source["sha256"],
    }
    snapshot["foundation"] = {
        "record_id": "FOUNDATION_SELECTED",
        "record_hash": "f" * 64,
        "display_name": "Selected Foundation",
        "state": "acquired",
        "mechanical_projection": {"source": "owner-sheet"},
        "full_description": "Authenticated selected foundation rules.",
        "full_description_source": "locked_typed_catalog_record",
        "source": {**source, "anchor": "selected:foundation"},
        "source_path": source["path"],
        "source_anchor": "selected:foundation",
        "source_hash": source["sha256"],
    }
    master = {
        "foundation": {
            "record_id": "FOUNDATION_SELECTED",
            "record_hash": "f" * 64,
            "display_name": "Selected Foundation",
            "state": "acquired",
            "mechanical_projection": {"source": "master-ledger"},
            "mechanics_authority": {"source": "master-ledger"},
        },
        "method": {
            "record_id": "METHOD_SELECTED",
            "record_hash": "m" * 64,
            "display_name": "Selected Method",
            "state": "acquired",
            "mechanical_projection": {"source": "master-ledger"},
            "mechanics_authority": {"source": "master-ledger"},
        },
        "advancement": {"levels": []},
        "features": [],
        "spheres": [],
        "talents": [],
    }
    return sheet_response, master


def test_command5_preserves_master_for_legacy_acquired_rows_without_display_enrichment(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    sheet_response, master = _command5_selected_method_foundation_fixture()
    snapshot = sheet_response["owner_character_sheet"]
    for name in ("method", "foundation"):
        canonical = master[name]
        snapshot[name] = {
            field: deepcopy(canonical[field])
            for field in ("record_id", "record_hash", "display_name", "state", "mechanical_projection")
        }
    profile = CharacterGMCommand5Profile.__new__(CharacterGMCommand5Profile)
    gm_model, view, tabs = profile._models(
        project={"project_id": "project.test", "revision": 1},
        sheet_response=sheet_response,
        workspace_root=workspace,
        workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
        profile={"profile_version": "test"},
        profile_contract_sha="p" * 64,
        command4={"status": "PASS"},
        master=master,
    )
    assert gm_model["method"] == master["method"]
    assert gm_model["foundation"] == master["foundation"]
    assert view["method"] == master["method"]
    assert view["foundation"] == master["foundation"]
    by_tab = {row["tab_id"]: row["value"] for row in tabs["rows"]}
    assert by_tab["method"] == master["method"]
    assert by_tab["foundation"] == master["foundation"]


def test_command5_merges_authenticated_method_foundation_display_into_models_and_sidecars(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    sheet_response, master = _command5_selected_method_foundation_fixture()
    values = {
        "Character_Master_Ledger.json": master,
        "Rules_Selection_Packets.json": {"packets": []},
        "Projection_Provenance_Map.json": {},
        "Projection_Coverage_Report.json": {"required_provenance_complete": True, "unproven_required_nodes": [], "blocked_required_sections": []},
        "Projection_Diagnostics.json": {"valid": True, "diagnostics": []},
    }

    class _ProjectionStub:
        def artifact(self, _project_id: str, name: str) -> Path:
            path = tmp_path / name
            path.write_text(canonical_json(values[name]), encoding="utf-8")
            return path

    profile = CharacterGMCommand5Profile.__new__(CharacterGMCommand5Profile)
    profile.projections = _ProjectionStub()
    profile._validate_models = lambda *_args: {"valid": True}
    surfaces = profile._surfaces(
        project={"project_id": "project.test", "revision": 1},
        sheet_response=sheet_response,
        workspace_root=workspace,
        workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
        profile={"profile_version": "test"},
        profile_contract_sha="p" * 64,
        command4={"status": "PASS"},
    )

    model = surfaces["Tianxia_GM_Character_Model_v1.json"]
    view = surfaces["Tianxia_GM_Character_View_Model_v2.json"]
    assert model["method"]["full_description"] == "Authenticated selected method rules."
    assert model["foundation"]["full_description"] == "Authenticated selected foundation rules."
    assert model["method"]["source"]["anchor"] == "selected:method-foundation"
    assert model["foundation"]["source"]["anchor"] == "selected:foundation"
    assert model["method"]["mechanical_projection"] == {"source": "master-ledger"}
    assert model["method"]["mechanics_authority"] == {"source": "master-ledger"}
    assert view["method"] == model["method"]
    assert view["foundation"] == model["foundation"]
    tab_values = {row["tab_id"]: row["value"] for row in surfaces["GM_Screen_Display_Rows.json"]["rows"]}
    assert tab_values["method"]["full_description"] == "Authenticated selected method rules."
    assert tab_values["foundation"]["full_description"] == "Authenticated selected foundation rules."
    assert surfaces["Cultivation_Method_Profile.json"]["method"] == model["method"]
    assert surfaces["Foundation_Detail_Ledger.json"]["foundation"] == model["foundation"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("record_hash", "x" * 64),
        ("display_name", "Relabeled Method"),
        ("source", {"path": "other.json", "anchor": "other", "sha256": "x" * 64}),
    ],
)
def test_command5_rejects_method_display_identity_drift(tmp_path: Path, field: str, value: object) -> None:
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    sheet_response, master = _command5_selected_method_foundation_fixture()
    master["method"][field] = value
    profile = CharacterGMCommand5Profile.__new__(CharacterGMCommand5Profile)

    with pytest.raises(FoundryError) as exc_info:
        profile._models(
            project={"project_id": "project.test", "revision": 1},
            sheet_response=sheet_response,
            workspace_root=workspace,
            workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
            profile={"profile_version": "test"},
            profile_contract_sha="p" * 64,
            command4={"status": "PASS"},
            master=master,
        )
    assert exc_info.value.code == "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID"


@pytest.mark.parametrize(
    ("target", "operation"),
    [
        ("master", "missing"),
        ("master", "none"),
        ("snapshot", "missing"),
        ("snapshot", "none"),
    ],
)
def test_command5_requires_nonblank_hash_for_display_merge(tmp_path: Path, target: str, operation: str) -> None:
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    sheet_response, master = _command5_selected_method_foundation_fixture()
    row = master["method"] if target == "master" else sheet_response["owner_character_sheet"]["method"]
    if operation == "missing":
        row.pop("record_hash", None)
    else:
        row["record_hash"] = None
    profile = CharacterGMCommand5Profile.__new__(CharacterGMCommand5Profile)

    with pytest.raises(FoundryError) as exc_info:
        profile._models(
            project={"project_id": "project.test", "revision": 1},
            sheet_response=sheet_response,
            workspace_root=workspace,
            workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
            profile={"profile_version": "test"},
            profile_contract_sha="p" * 64,
            command4={"status": "PASS"},
            master=master,
        )
    assert exc_info.value.code == "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID"


@pytest.mark.parametrize(
    ("master_flag", "snapshot_flag"),
    [(True, False), (False, True)],
)
def test_command5_rejects_conflicting_display_only_authority_flags(
    tmp_path: Path,
    master_flag: bool,
    snapshot_flag: bool,
) -> None:
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    sheet_response, master = _command5_selected_method_foundation_fixture()
    master["method"]["display_only_not_execution_authority"] = master_flag
    sheet_response["owner_character_sheet"]["method"]["display_only_not_execution_authority"] = snapshot_flag
    profile = CharacterGMCommand5Profile.__new__(CharacterGMCommand5Profile)

    with pytest.raises(FoundryError) as exc_info:
        profile._models(
            project={"project_id": "project.test", "revision": 1},
            sheet_response=sheet_response,
            workspace_root=workspace,
            workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
            profile={"profile_version": "test"},
            profile_contract_sha="p" * 64,
            command4={"status": "PASS"},
            master=master,
        )
    assert exc_info.value.code == "CHARACTER_GM_SELECTED_RECORD_DISPLAY_INVALID"


@pytest.mark.parametrize("snapshot_flag", [True, False])
def test_command5_does_not_infer_authority_from_snapshot_when_master_flag_is_missing(
    tmp_path: Path,
    snapshot_flag: bool,
) -> None:
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    sheet_response, master = _command5_selected_method_foundation_fixture()
    master["method"].pop("display_only_not_execution_authority", None)
    sheet_response["owner_character_sheet"]["method"]["display_only_not_execution_authority"] = snapshot_flag
    profile = CharacterGMCommand5Profile.__new__(CharacterGMCommand5Profile)
    gm_model, _view, _tabs = profile._models(
        project={"project_id": "project.test", "revision": 1},
        sheet_response=sheet_response,
        workspace_root=workspace,
        workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
        profile={"profile_version": "test"},
        profile_contract_sha="p" * 64,
        command4={"status": "PASS"},
        master=master,
    )
    if snapshot_flag:
        assert gm_model["method"]["display_only_not_execution_authority"] is True
    else:
        assert "display_only_not_execution_authority" not in gm_model["method"]


def test_command5_emits_master_method_and_foundation_sidecars(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _command4_workspace(workspace)
    master = {
        "foundation": {"record_id": "FOUNDATION_ROOT", "display_name": "Root Foundation", "state": "acquired"},
        "method": {"record_id": "METHOD_ROOT", "display_name": "Root Method", "state": "acquired"},
        "advancement": {"levels": []},
        "features": [],
        "spheres": [],
        "talents": [],
    }
    values = {
        "Character_Master_Ledger.json": master,
        "Rules_Selection_Packets.json": {"packets": []},
        "Projection_Provenance_Map.json": {},
        "Projection_Coverage_Report.json": {"required_provenance_complete": True, "unproven_required_nodes": [], "blocked_required_sections": []},
        "Projection_Diagnostics.json": {"valid": True, "diagnostics": []},
    }

    class _ProjectionStub:
        def artifact(self, _project_id: str, name: str) -> Path:
            path = tmp_path / name
            path.write_text(canonical_json(values[name]), encoding="utf-8")
            return path

    profile = CharacterGMCommand5Profile.__new__(CharacterGMCommand5Profile)
    profile.projections = _ProjectionStub()
    profile._validate_models = lambda *_args: {"valid": True}
    surfaces = profile._surfaces(
        project={"project_id": "project.test", "revision": 1},
        sheet_response=_sheet_response(with_advanced=False, current_cl=15),
        workspace_root=workspace,
        workspace_status={"workspace_id": "workspace.test", "workspace_sha256": "w" * 64},
        profile={"profile_version": "test"},
        profile_contract_sha="p" * 64,
        command4={"status": "PASS"},
    )
    assert surfaces["Foundation_Detail_Ledger.json"]["foundation"] == master["foundation"]
    assert surfaces["Cultivation_Method_Profile.json"]["method"] == master["method"]
    tab_values = {row["tab_id"]: row["value"] for row in surfaces["GM_Screen_Display_Rows.json"]["rows"]}
    assert tab_values["foundation"] == master["foundation"]
    assert tab_values["method"] == master["method"]


def test_project_overlay_does_not_erase_candidate_foundation_without_explicit_authority() -> None:
    candidate = _candidate_model()
    candidate["cultivation"]["foundation"] = {"state": "present", "value": {"stable_id": "FOUNDATION_ROOT", "name": "Root Foundation"}}
    blank_state = {
        "primary_method_id": None,
        "readiness": "READY",
        "paths": [{"path_id": "tianxia.path.body_refining", "attainment": 0}],
    }
    preserved = _project_model_overlay(deepcopy(candidate), {}, blank_state, candidate_sha256="c" * 64)
    assert preserved["cultivation"]["foundation"] == candidate["cultivation"]["foundation"]

    explicit_none = deepcopy(blank_state)
    explicit_none["foundation_state"] = "none"
    erased = _project_model_overlay(deepcopy(candidate), {}, explicit_none, candidate_sha256="c" * 64)
    assert erased["cultivation"]["foundation"]["state"] == "explicit_none"

    selected = deepcopy(blank_state)
    selected["foundation_id"] = "FOUNDATION_SELECTED"
    projected = _project_model_overlay(deepcopy(candidate), {}, selected, candidate_sha256="c" * 64)
    assert projected["cultivation"]["foundation"]["value"]["stable_id"] == "FOUNDATION_SELECTED"


def _configure_local(service: AIProviderService) -> None:
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="gemma-3-12b-it",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )


def _valid_debrief() -> dict:
    return {
        "friction_redundancy": ["The progression choices were easy to compare."],
        "choice_bias_flavor_context": ["The flavor cues made the tradeoffs clear."],
        "helpful_deterministic_tools": ["The frozen legality summary was useful."],
        "creativity_within_rules": ["The bounded options left room for a distinct concept."],
        "modular_future_content": ["New content can be added through the sealed catalog."],
        "summary": "A concise provider-facing debrief.",
    }


def test_build_debrief_uses_one_strict_local_call_and_safe_receipt(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    _configure_local(service)
    observed: list[dict] = []

    def provider_call(**kwargs):
        observed.append(json.loads(kwargs["request_bytes"]))
        body = {"choices": [{"message": {"content": json.dumps(_valid_debrief())}, "finish_reason": "stop"}]}
        return 200, json.dumps(body).encode("utf-8")

    monkeypatch.setattr(service, "_provider_call", provider_call)
    receipt = service.build_debrief(prompt_text="Summarize the completed build for the owner.")
    assert len(observed) == 1
    assert receipt["value"] == _valid_debrief()
    request = observed[0]
    assert request["chat_template_kwargs"] == {"enable_thinking": False}
    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": BUILD_DEBRIEF_SCHEMA_NAME, "strict": True, "schema": BUILD_DEBRIEF_RESPONSE_SCHEMA},
    }
    assert request["max_tokens"] == 768
    assert request["messages"][0]["content"].find("reasoning_content") >= 0
    assert BUILD_DEBRIEF_RESPONSE_SCHEMA["additionalProperties"] is False
    assert set(BUILD_DEBRIEF_RESPONSE_SCHEMA["required"]) == set(_valid_debrief())


def test_build_debrief_rejects_empty_visible_content_even_with_reasoning(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    _configure_local(service)
    calls = 0

    def provider_call(**kwargs):
        nonlocal calls
        calls += 1
        body = {
            "choices": [{
                "message": {"content": "", "reasoning_content": json.dumps(_valid_debrief())},
                "finish_reason": "stop",
            }]
        }
        return 200, json.dumps(body).encode("utf-8")

    monkeypatch.setattr(service, "_provider_call", provider_call)
    with pytest.raises(FoundryError) as error:
        service.build_debrief(prompt_text="Summarize the completed build for the owner.")
    assert error.value.code == "AI_PROVIDER_RESPONSE_CONTRACT_INVALID"
    assert calls == 1
