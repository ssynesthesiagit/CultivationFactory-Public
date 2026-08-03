from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Database, FoundryError, Settings, canonical_json
from canonical_catalog import CanonicalCatalogAuthorityService
from character_builder.service import CharacterBuilderService

ROOT = Path(__file__).resolve().parents[1]


def _service() -> CanonicalCatalogAuthorityService:
    return CanonicalCatalogAuthorityService(ROOT)


@pytest.fixture(scope="session")
def cat2_bootstrapped_environment():
    value = os.environ.get("CAT2_BOOTSTRAPPED_DATA_ROOT")
    if not value:
        pytest.skip("CAT2_BOOTSTRAPPED_DATA_ROOT is required for database-backed CAT2 integration tests.")
    data = Path(value).resolve()
    settings = Settings.from_env(ROOT, data)
    db = Database(settings)
    db.migrate()
    return {"settings": settings, "db": db}


def _first_legal_pair(service: CanonicalCatalogAuthorityService, sphere_id: str, target_cl: int = 20) -> tuple[str, str]:
    projection = service.creator_projection(target_cl=target_cl, acquired_sphere_ids=[sphere_id])
    legal = [
        row["canonical_talent_id"] for row in projection["talent_dispositions"]
        if row["owning_canonical_sphere_id"] == sphere_id and row["selectable_now"]
    ]
    assert len(legal) >= 2
    return legal[0], legal[1]


def test_cat2_exact_authority_counts_and_descriptions():
    service = _service()
    status = service.status()
    assert status["ready"] is True
    assert status["status"] == "CAT3_P1R_CANONICAL_CATALOG_SOURCE_READY_FOR_INDEPENDENT_REVIEW"
    assert status["canonical_sphere_count"] == 85
    assert status["canonical_talent_count"] == 2985
    assert status["canonical_membership_count"] == status["canonical_talent_count"]
    assert status["background_only_route_count"] == 77
    assert status["quarantined_count"] == 7
    assert status["automatic_base_ability_source_row_count"] == 126
    assert status["automatic_base_ability_unique_count"] == 125
    talents = service.list_talents()["records"]
    assert len(talents) == status["canonical_talent_count"]
    talent_names = {row["display_name"] for row in talents}
    child_names = {
        "Perfect Temper",
        "Reforging of Broken Fate",
        "Birth-Cry of the Item Spirit",
        "Sever the False Shape",
    }
    assert child_names.isdisjoint(talent_names)
    parent = next(row for row in talents if row["display_name"] == "The First Hammer That Named Iron")
    assert {row["display_name"] for row in parent["child_options"]} == child_names
    assert all(row["short_description"].strip() for row in talents)
    assert all(row["full_description"].strip() for row in talents)
    assert all(set(("short_description", "full_description", "source_reference", "acquisition_route")).issubset(row) for row in talents)


def test_cat2_aliases_fencing_harvesting_and_unique_memberships():
    service = _service()
    assert service.resolve_sphere_id("Fencing") == "tianxia.sphere.the_piercing_needle"
    assert service.resolve_sphere_id("Harvesting") == "tianxia.sphere.harvesting_gathering"
    assert service.resolve_sphere_id("Harvesting-Gathering") == "tianxia.sphere.harvesting_gathering"
    assert service.resolve_sphere_id("Harvesting and Gathering") == "tianxia.sphere.harvesting_gathering"
    spheres = service.list_spheres()["records"]
    assert len(spheres) == 85
    assert not any(row["display_name"] == "Fencing" for row in spheres)
    assert sum(row["canonical_sphere_id"] == "tianxia.sphere.harvesting_gathering" for row in spheres) == 1
    fencing = service.list_talents(sphere_id="Fencing")["records"]
    assert fencing
    assert {row["owning_canonical_sphere_id"] for row in fencing} == {"tianxia.sphere.the_piercing_needle"}
    assert len({row["canonical_talent_id"] for row in fencing}) == len(fencing)


def test_cat2_quarantine_and_background_routes_remain_separate():
    diagnostics = _service().diagnostics()
    assert len(diagnostics["background_only_routes"]) == 77
    assert diagnostics["quarantined"]["count"] == 7
    assert diagnostics["quarantined"]["label"] == "Exact authority decision required — not currently selectable"
    canonical_ids = {row["canonical_talent_id"] for row in _service().list_talents()["records"]}
    quarantined_ids = {str(row.get("candidate_record_id") or "") for row in diagnostics["quarantined"]["decision_packets"]}
    assert not (canonical_ids & quarantined_ids)


def test_cat2_automatic_base_abilities_and_free_grant_accounting():
    service = _service()
    base = service.diagnostics()["automatic_base_abilities"]["records"]
    sphere_id = next(row["owning_canonical_sphere_id"] for row in base if len(service.list_talents(sphere_id=row["owning_canonical_sphere_id"])["records"]) >= 2)
    free_id, ordinary_id = _first_legal_pair(service, sphere_id)
    projection = service.validate_grant_plan(
        target_cl=20,
        acquired_sphere_ids=[sphere_id],
        free_talent_grants={sphere_id: free_id},
        ordinary_talent_ids=[ordinary_id],
    )
    accounting = projection["grant_accounting"]
    assert accounting["automatic_base_ability_count"] > 0
    assert accounting["automatic_base_abilities_counted_as_talent_choices"] == 0
    assert accounting["free_sphere_talent_grant_count"] == 1
    assert accounting["ordinary_talent_count"] == accounting["ordinary_talent_cost_count"] == 1
    assert accounting["total_distinct_talent_ids"] == 2
    assert all(row["automatic_grant"] and not row["owner_removable"] for row in accounting["automatic_base_abilities"])
    assert all(not row["counts_as_talent_choice"] and not row["counts_as_advancement_talent"] and not row["counts_as_training_talent"] for row in accounting["automatic_base_abilities"])


def test_cat2_double_count_and_missing_free_slot_fail_closed():
    service = _service()
    sphere_id = "tianxia.sphere.air"
    free_id, ordinary_id = _first_legal_pair(service, sphere_id)
    with pytest.raises(FoundryError) as exc:
        service.creator_projection(target_cl=20, acquired_sphere_ids=[sphere_id], free_talent_grants={sphere_id: free_id}, ordinary_talent_ids=[free_id])
    assert exc.value.code == "TALENT_ACQUISITION_ROUTE_DOUBLE_COUNT"
    with pytest.raises(FoundryError) as exc:
        service.creator_projection(target_cl=20, acquired_sphere_ids=[sphere_id], free_talent_grants={sphere_id: free_id}, ordinary_talent_ids=[ordinary_id, ordinary_id])
    assert exc.value.code == "ORDINARY_TALENT_DUPLICATE_SELECTION"
    blocked = service.creator_projection(target_cl=20, acquired_sphere_ids=[sphere_id])
    assert blocked["ready"] is False
    assert blocked["validation_errors"][0]["code"] == "FREE_SPHERE_TALENT_REQUIRED"



def test_cat2_repeated_sphere_inputs_do_not_double_count_automatic_grants():
    service = _service()
    sphere_id = "tianxia.sphere.air"
    free_id, ordinary_id = _first_legal_pair(service, sphere_id)
    plan = service.validate_grant_plan(
        target_cl=20,
        acquired_sphere_ids=[sphere_id, "Air", sphere_id],
        free_talent_grants={sphere_id: free_id},
        ordinary_talent_ids=[ordinary_id],
    )
    accounting = plan["grant_accounting"]
    assert plan["acquired_canonical_sphere_ids"] == [sphere_id]
    automatic_ids = [row["base_ability_id"] for row in accounting["automatic_base_abilities"]]
    assert len(automatic_ids) == len(set(automatic_ids))
    assert accounting["free_sphere_talent_grant_count"] == 1
    assert accounting["ordinary_talent_count"] == 1
    assert accounting["ordinary_talent_cost_count"] == 1
    assert accounting["total_distinct_talent_ids"] == 2


def test_cat2_stage1_api_returns_compact_response_and_preserves_sealed_envelope(cat2_bootstrapped_environment):
    builder = CharacterBuilderService(cat2_bootstrapped_environment["db"])
    sphere_id = "tianxia.sphere.air"
    free_id, ordinary_id = _first_legal_pair(builder.canonical_catalog, sphere_id)
    created = builder.create_project(
        working_name="CAT2 Stage 1 compact response",
        concept="Test-only exact prompt transport fixture",
        target_cl=20,
        power_band="standard",
        source_reference="noncanonical test fixture",
        creation_mode="detailed",
        ability_scores={},
        selections={"sphere_priorities": [sphere_id], "advancement_skeleton": [ordinary_id]},
        canonical_sphere_ids=[sphere_id],
        sphere_free_talent_grants={sphere_id: free_id},
        ordinary_talent_ids=[ordinary_id],
    )
    app = create_app(cat2_bootstrapped_environment["settings"])
    endpoint = {route.path: route.endpoint for route in app.routes if hasattr(route, "endpoint")}
    compact = endpoint["/api/projects/{project_id}/stage1/prompt"](created["project_id"])
    assert "envelope" not in compact
    assert compact["deterministic"] is True
    assert compact["prompt_text"].count("PROMPT_ENVELOPE\n") == 1
    sealed = endpoint["/api/stage1/prompts/{prompt_id}"](compact["prompt_id"])
    assert sealed["prompt_sha256"] == compact["prompt_sha256"]
    assert sealed["prompt_text"] == compact["prompt_text"]
    assert canonical_json(sealed["envelope"]) in compact["prompt_text"]


def test_cat2_prerequisite_invalidation_is_deterministic():
    service = _service()
    gated = next(
        row for row in service.list_talents()["records"]
        if isinstance(row.get("minimum_cl"), int) and row["minimum_cl"] > 1 and row["creator_selectability_can_be_evaluated_safely"]
        and row["selection_disposition"] != "RESTRICTED_CONTENT"
    )
    sphere_id = gated["owning_canonical_sphere_id"]
    high = service.creator_projection(target_cl=gated["minimum_cl"], acquired_sphere_ids=[sphere_id])
    high_row = next(row for row in high["talent_dispositions"] if row["canonical_talent_id"] == gated["canonical_talent_id"])
    low = service.creator_projection(target_cl=gated["minimum_cl"] - 1, acquired_sphere_ids=[sphere_id])
    low_row = next(row for row in low["talent_dispositions"] if row["canonical_talent_id"] == gated["canonical_talent_id"])
    assert high_row["selectable_now"] is True
    assert low_row["selectable_now"] is False
    assert low_row["disposition"] == "locked_by_minimum_cl"
    assert "Requires Cultivation Level" in low_row["owner_reason"]
    assert service.creator_projection(target_cl=gated["minimum_cl"] - 1, acquired_sphere_ids=[sphere_id])["projection_sha256"] == low["projection_sha256"]


def test_cat2_character_builder_options_use_exact_canonical_projection(cat2_bootstrapped_environment):
    service = CharacterBuilderService(cat2_bootstrapped_environment["db"])
    options = service.options()
    canonical_count = options["canonical_catalog_authority"]["canonical_talent_count"]
    categories = {row["slot_id"]: row for row in options["categories"]}
    assert len(categories["sphere_priorities"]["choices"]) == 85
    assert len(categories["advancement_skeleton"]["choices"]) == canonical_count
    assert options["sphere_talent_index"]["audit"]["mapped_talent_count"] == canonical_count
    assert options["sphere_talent_index"]["unassigned_talent_ids"] == []
    assert options["canonical_catalog_authority"]["ready"] is True
    assert len(options["background_only_routes"]) == 77
    assert options["quarantined_authority_records"]["count"] == 7


def test_cat2_project_save_reopen_preserves_grant_routes(cat2_bootstrapped_environment):
    service = CharacterBuilderService(cat2_bootstrapped_environment["db"])
    sphere_id = "tianxia.sphere.air"
    free_id, ordinary_id = _first_legal_pair(service.canonical_catalog, sphere_id)
    created = service.create_project(
        working_name="CAT2 grant persistence",
        concept="Test-only canonical accounting fixture",
        target_cl=20,
        power_band="standard",
        source_reference="noncanonical test fixture",
        creation_mode="detailed",
        ability_scores={},
        selections={"sphere_priorities": [sphere_id], "advancement_skeleton": [ordinary_id]},
        canonical_sphere_ids=[sphere_id],
        sphere_free_talent_grants={sphere_id: free_id},
        ordinary_talent_ids=[ordinary_id],
    )
    project = service.projects.get_project(created["project_id"])
    locks = {row["field"]: row["value"] for row in project["project"]["user_locks"]}
    plan = locks["character_sheet.canonical_grant_plan"]
    projection = locks["character_sheet.canonical_character_projection"]
    assert plan["grant_accounting"]["free_sphere_talent_grants"][0]["talent_id"] == free_id
    assert plan["grant_accounting"]["ordinary_talent_ids"] == [ordinary_id]
    assert projection["cost_accounting"] == {"automatic_base_ability_cost": 0, "free_sphere_talent_grant_cost": 0, "ordinary_talent_cost": 1}
    assert projection["projection_sha256"] == created["character_sheet"]["canonical_character_projection"]["projection_sha256"]


def test_cat2_api_defaults_canonical_and_raw_is_explicit(cat2_bootstrapped_environment):
    app = create_app(cat2_bootstrapped_environment["settings"])
    endpoint = {route.path: route.endpoint for route in app.routes if hasattr(route, "endpoint")}
    canonical = endpoint["/api/catalog/records"](q=None, content_type=None, authority=None, publication_state=None, pack_id=None, pack_version=None, minimum_cl_lte=None, include_test=False, projection="canonical", limit=100, offset=0)
    assert canonical["projection"] == "canonical_owner_facing"
    assert canonical["count"] == 85
    assert len(canonical["records"]) == 85
    talents = endpoint["/api/catalog/records"](q=None, content_type="talent", authority=None, publication_state=None, pack_id=None, pack_version=None, minimum_cl_lte=None, include_test=False, projection="canonical", limit=2000, offset=0)
    assert talents["count"] == endpoint["/api/catalog/canonical/status"]()["canonical_talent_count"]
    raw = endpoint["/api/catalog/records"](q=None, content_type=None, authority=None, publication_state=None, pack_id=None, pack_version=None, minimum_cl_lte=None, include_test=False, projection="raw", limit=1, offset=0)
    assert "projection" not in raw or raw.get("projection") != "canonical_owner_facing"
    status = endpoint["/api/catalog/canonical/status"]()
    assert status["canonical_sphere_count"] == 85
    health = endpoint["/api/health"]()
    assert health["canonical_catalog_ready"] is True


def test_cat2_readiness_fails_character_creation_closed_when_authority_missing(cat2_bootstrapped_environment, tmp_path: Path):
    isolated_root = tmp_path / "isolated_missing_authority_root"
    shutil.copytree(ROOT / "catalog_authority", isolated_root / "catalog_authority")
    (isolated_root / "BundledContent").mkdir(parents=True)
    shutil.copy2(ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip", isolated_root / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip")
    (isolated_root / "catalog_authority" / "cat3" / "generated" / "catalog_authority.v1.json").unlink()
    status = CanonicalCatalogAuthorityService(isolated_root).status()
    assert status["ready"] is False
    assert status["error"]["code"] == "CANONICAL_CATALOG_AUTHORITY_MISSING"
    app = create_app(cat2_bootstrapped_environment["settings"])
    app.state.product_readiness.settings = Settings.from_env(isolated_root, cat2_bootstrapped_environment["settings"].data_dir)
    report = app.state.product_readiness.report()
    assert report["canonical_catalog_authority"]["ready"] is False
    assert report["character_creation"]["ready"] is False
    assert report["portable_import"]["ready"] is True
    assert report["process"]["live"] is True


def test_cat2_ui_exposes_full_descriptions_and_planning_only_routes():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "Full description and exact authority" in script
    assert "Prioritize Talent" in script
    assert "This records planning direction only" in script
    assert "sphere_priority_ids" in script
    assert "talent_priority_ids" in script
    assert "Canonical catalog authority" in script
    assert "Browse Rules" in html
    assert "Use Free Grant" not in script
    assert "Add Ordinary" not in script


def test_cat2_source_description_parser_preserves_inline_authority_text():
    row = _service().get_talent("TAL_ATHLETICS_RAPID_MOTION")
    assert row["full_description"] == "Technique Dash as a Bonus Action."
    assert row["short_description"] == row["full_description"]
