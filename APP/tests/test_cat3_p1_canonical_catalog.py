from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import FoundryError
from canonical_catalog import CanonicalCatalogAuthorityService
from catalog_authority.cat3.validate import validate
from non_sphere_authority.service import NonSphereAuthorityService
from tests.test_ns1r_non_sphere_authority import BODY, insert_project


ROOT = Path(__file__).resolve().parents[1]


def test_generated_authority_acceptance():
    report = validate(ROOT)
    assert report["counts"]["canonical_spheres"] == 85
    assert report["counts"]["canonical_talents"] > 1748
    assert report["counts"]["quarantined_records"] >= 6
    assert report["counts"]["automatic_base_ability_unique_components"] == 125
    assert len(report["formerly_empty_spheres_restored"]) == 25


def test_runtime_uses_derived_counts_aliases_and_migrations():
    service = CanonicalCatalogAuthorityService(ROOT)
    status = service.status()
    assert status["ready"]
    assert status["canonical_talent_count"] == service.list_talents()["count"]
    assert service.resolve_sphere_id("Fencing") == "tianxia.sphere.the_piercing_needle"
    assert service.resolve_sphere_id("Harvesting and Gathering") == "tianxia.sphere.harvesting_gathering"
    authority = json.loads((ROOT / "catalog_authority/cat3/generated/catalog_authority.v1.json").read_text(encoding="utf-8"))
    for migration in authority["stable_id_migrations"]:
        if migration.get("record_type") == "talent":
            assert service.resolve_talent_id(migration["legacy_id"]) == migration["canonical_id"]


@pytest.mark.parametrize("target_cl", [1, 3, 5, 7, 9, 10, 14, 15, 17, 20])
def test_target_cl_boundary_evaluator(target_cl):
    service = CanonicalCatalogAuthorityService(ROOT)
    projection = service.creator_projection(target_cl=target_cl)
    for row in projection["talent_dispositions"]:
        assert row["disposition"] in {"locked_by_sphere", "locked_by_minimum_cl", "locked_by_prerequisite", "locked_by_prerequisite_talent", "locked_by_unresolved_prerequisite"}
    expected = "Immortal" if target_cl >= 20 else "Nascent Soul" if target_cl >= 15 else "Core Formation" if target_cl >= 10 else "Foundation" if target_cl >= 5 else "Mortal"
    assert projection["target_realm_band"] == expected


def test_immortal_heading_does_not_match_mortal_substring():
    service = CanonicalCatalogAuthorityService(ROOT)
    beauty = next(
        row for row in service.list_talents(sphere_id="tianxia.sphere.beauty")["records"]
        if row["display_name"] == "Beauty Beyond Form"
    )
    assert beauty["minimum_cl"] == 20
    assert beauty["realm_band"] == "Immortal"
    low = service.creator_projection(
        target_cl=19,
        acquired_sphere_ids=["tianxia.sphere.beauty"],
    )
    high = service.creator_projection(
        target_cl=20,
        acquired_sphere_ids=["tianxia.sphere.beauty"],
    )
    low_row = next(row for row in low["talent_dispositions"] if row["canonical_talent_id"] == beauty["canonical_talent_id"])
    high_row = next(row for row in high["talent_dispositions"] if row["canonical_talent_id"] == beauty["canonical_talent_id"])
    assert low_row["disposition"] == "locked_by_minimum_cl"
    assert not low_row["selectable_now"]
    assert high_row["disposition"] == "selectable_now"
    assert high_row["selectable_now"]


def test_cl_gate_and_restricted_selection_records_provenance():
    service = CanonicalCatalogAuthorityService(ROOT)
    restricted = next(row for row in service.list_talents()["records"] if row["acquisition_provenance_required"] and row["creator_selectability_can_be_evaluated_safely"] and all(p["kind"] in {"minimum_cl", "owning_sphere", "acquisition_provenance", "realm"} for p in row["typed_prerequisites"]))
    sphere_id = restricted["owning_canonical_sphere_id"]
    low = service.creator_projection(
        target_cl=max(1, restricted["minimum_cl"] - 1),
        acquired_sphere_ids=[sphere_id],
        free_talent_grants={sphere_id: next(
            row["canonical_talent_id"] for row in service.list_talents(sphere_id=sphere_id)["records"]
            if row["free_sphere_talent_eligible"] and row["minimum_cl"] <= max(1, restricted["minimum_cl"] - 1)
        )},
        ordinary_talent_ids=[restricted["canonical_talent_id"]],
    )
    if restricted["minimum_cl"] > 1:
        assert not low["ready"]
    public_high = service.creator_projection(
        target_cl=restricted["minimum_cl"],
        acquired_sphere_ids=[sphere_id],
        free_talent_grants={sphere_id: next(
            row["canonical_talent_id"] for row in service.list_talents(sphere_id=sphere_id)["records"]
            if row["free_sphere_talent_eligible"] and row["minimum_cl"] <= restricted["minimum_cl"]
        )},
        ordinary_talent_ids=[restricted["canonical_talent_id"]],
    )
    assert not public_high["ready"]
    high = service.creator_projection_for_initial_creation(
        target_cl=restricted["minimum_cl"],
        acquired_sphere_ids=[sphere_id],
        free_talent_grants={sphere_id: next(
            row["canonical_talent_id"] for row in service.list_talents(sphere_id=sphere_id)["records"]
            if row["free_sphere_talent_eligible"] and row["minimum_cl"] <= restricted["minimum_cl"]
        )},
        ordinary_talent_ids=[restricted["canonical_talent_id"]],
    )
    assert high["ready"]
    selected = next(row for row in high["talent_dispositions"] if row["canonical_talent_id"] == restricted["canonical_talent_id"])
    assert selected["acquisition_provenance"]["recorded"] is False
    assert selected["acquisition_provenance"]["source"] == "pending-trusted-initial-finalization"
    assert selected["acquisition_provenance"]["access_category"] == restricted["access_category"]


def test_heaven_thunder_is_body_subpath_at_cl3_without_access_row(fresh_db):
    insert_project(fresh_db, "cat3-heaven-thunder", target_cl=3)
    service = NonSphereAuthorityService(fresh_db)
    choice = service.subpaths["tianxia.subpath.body.heaven_thunder_drum_body"]
    assert choice["option_type"] == "subpath"
    assert choice["owning_path_id"] == BODY
    assert choice["access"]["canonical_category"] == "Restricted Scripture"
    with pytest.raises(FoundryError):
        service.initialize_for_project(
            "cat3-heaven-thunder", target_cl=2, path_ids=[BODY],
            path_attainment_by_id={BODY: 2}, subpath_ids=[choice["canonical_id"]],
        )
    state = service.initialize_for_project(
        "cat3-heaven-thunder", target_cl=3, path_ids=[BODY],
        path_attainment_by_id={BODY: 3}, subpath_ids=[choice["canonical_id"]],
    )
    body = next(row for row in state["paths"] if row["path_id"] == BODY)
    provenance = body["subpath_or_tradition_acquisition_provenance"]
    assert provenance["content_type"] == "Body Refining Subpath"
    assert provenance["access_category"] == "Restricted Scripture"
    assert provenance["recorded"]
