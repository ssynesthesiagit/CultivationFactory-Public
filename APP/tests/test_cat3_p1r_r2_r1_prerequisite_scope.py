from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from canonical_catalog import CanonicalCatalogAuthorityService
from catalog_authority.cat3.compiler import _LEGACY_BROAD_USE_CUE_RE, normalize


ROOT = Path(__file__).resolve().parents[1]


def _talent(service: CanonicalCatalogAuthorityService, talent_id: str) -> dict[str, Any]:
    return next(
        row for row in service.list_talents()["records"]
        if row["canonical_talent_id"] == talent_id
    )


def _disposition(projection: dict[str, Any], talent_id: str) -> dict[str, Any]:
    return next(
        row for row in projection["talent_dispositions"]
        if row["canonical_talent_id"] == talent_id
    )


def _project(
    service: CanonicalCatalogAuthorityService,
    talent_id: str,
    *,
    target_cl: int,
    acquired_sphere_ids: Iterable[str] | None = None,
    existing_talent_ids: Iterable[str] = (),
    structural_authority_ids: Iterable[str] = (),
) -> dict[str, Any]:
    talent = _talent(service, talent_id)
    spheres = list(acquired_sphere_ids or [talent["owning_canonical_sphere_id"]])
    projection = service.creator_projection_for_initial_creation(
        target_cl=target_cl,
        acquired_sphere_ids=spheres,
        existing_talent_ids=list(existing_talent_ids),
        structural_authority_ids=list(structural_authority_ids),
    )
    return _disposition(projection, talent_id)


def _missing_reasons(disposition: dict[str, Any]) -> list[str]:
    return [row["owner_reason"] for row in disposition["prerequisite_evaluation"]["blocking_failures"]]


def test_air_stunt_and_sparrows_path_exact_acquisition_chain():
    service = CanonicalCatalogAuthorityService(ROOT)

    air_missing = _project(service, "TAL_ATHLETICS_AIR_STUNT", target_cl=5)
    assert air_missing["selectable_now"] is False
    assert air_missing["disposition"] == "locked_by_prerequisite_talent"
    assert "Requires prerequisite Talent Wall Stunt." in _missing_reasons(air_missing)

    air_ready = _project(
        service,
        "TAL_ATHLETICS_AIR_STUNT",
        target_cl=5,
        existing_talent_ids=["TAL_ATHLETICS_WALL_STUNT"],
    )
    assert air_ready["selectable_now"] is True

    sparrow_missing = _project(service, "TAL_ATHLETICS_SPARROW_S_PATH", target_cl=7)
    assert sparrow_missing["selectable_now"] is False
    reasons = _missing_reasons(sparrow_missing)
    assert "Requires prerequisite Talent Air Stunt." in reasons
    assert "Requires prerequisite Talent Wall Stunt." in reasons

    sparrow_one_missing = _project(
        service,
        "TAL_ATHLETICS_SPARROW_S_PATH",
        target_cl=7,
        existing_talent_ids=["TAL_ATHLETICS_WALL_STUNT"],
    )
    assert sparrow_one_missing["selectable_now"] is False
    assert "Requires prerequisite Talent Air Stunt." in _missing_reasons(sparrow_one_missing)

    sparrow_ready = _project(
        service,
        "TAL_ATHLETICS_SPARROW_S_PATH",
        target_cl=7,
        existing_talent_ids=["TAL_ATHLETICS_AIR_STUNT", "TAL_ATHLETICS_WALL_STUNT"],
    )
    assert sparrow_ready["selectable_now"] is True


def test_earth_shattering_slam_requires_berserker_shatter_earth_and_living_weapon():
    service = CanonicalCatalogAuthorityService(ROOT)
    talent_id = "TAL_WRESTLING_EARTH_SHATTERING_SLAM"

    missing = _project(service, talent_id, target_cl=5)
    assert missing["selectable_now"] is False
    reasons = _missing_reasons(missing)
    assert "Requires the exact Berserker Sphere." in reasons
    assert "Requires prerequisite Talent Shatter Earth." in reasons
    assert "Requires prerequisite Talent Living Weapon." in reasons

    missing_talents = _project(
        service,
        talent_id,
        target_cl=5,
        acquired_sphere_ids=["tianxia.sphere.wrestling", "tianxia.sphere.berserker"],
    )
    assert missing_talents["selectable_now"] is False
    assert "Requires prerequisite Talent Shatter Earth." in _missing_reasons(missing_talents)
    assert "Requires prerequisite Talent Living Weapon." in _missing_reasons(missing_talents)

    ready = _project(
        service,
        talent_id,
        target_cl=5,
        acquired_sphere_ids=["tianxia.sphere.wrestling", "tianxia.sphere.berserker"],
        existing_talent_ids=["TAL_BERSERKER_SHATTER_EARTH", "TAL_WRESTLING_LIVING_WEAPON"],
    )
    assert ready["selectable_now"] is True


def test_cyclone_cut_and_true_name_keep_acquisition_and_use_authority_separate():
    service = CanonicalCatalogAuthorityService(ROOT)

    cyclone_id = "TAL_DUAL_WIELDING_CYCLONE_CUT"
    cyclone = _talent(service, cyclone_id)
    prerequisite = next(row for row in cyclone["prerequisite_clauses"] if row["label"] == "Prerequisite")
    requirement = next(row for row in cyclone["prerequisite_clauses"] if row["label"] == "Requirement")
    assert prerequisite["scope"] == "acquisition"
    assert requirement["scope"] == "use_condition"

    structural_id = "tianxia.structural.dual_wielding.talent_category.dual_wielding"
    cyclone_missing = _project(service, cyclone_id, target_cl=5)
    assert cyclone_missing["selectable_now"] is False
    assert "Requires exact structural authority Dual Wielding." in _missing_reasons(cyclone_missing)
    cyclone_ready = _project(
        service,
        cyclone_id,
        target_cl=5,
        structural_authority_ids=[structural_id],
    )
    assert cyclone_ready["selectable_now"] is True
    assert any(
        row["scope"] == "use_condition"
        and row["resolution_status"] == "unresolved"
        and row["passed"]
        for row in cyclone_ready["prerequisite_evaluation"]["predicate_results"]
    )

    true_name_id = "tianxia.talent.ink.true_name_calligraphy"
    true_name = _talent(service, true_name_id)
    prerequisite_clauses = [row for row in true_name["prerequisite_clauses"] if row["label"] == "Prerequisite"]
    assert any(row["scope"] == "acquisition" and "Immortal Scripture" in row["body"] for row in prerequisite_clauses)
    assert any(
        row["scope"] == "use_condition"
        and row["scope_basis"] == "exact_true_name_discovery_subclause"
        for row in prerequisite_clauses
    )
    assert all(
        row["scope"] == "use_condition"
        for row in true_name["prerequisite_clauses"]
        if row["label"] == "Requirement"
    )

    true_name_low = _project(
        service,
        true_name_id,
        target_cl=16,
        existing_talent_ids=["tianxia.talent.ink.immortal_scripture"],
    )
    assert true_name_low["selectable_now"] is False
    assert "Requires Cultivation Level 17+." in _missing_reasons(true_name_low)

    true_name_missing_scripture = _project(service, true_name_id, target_cl=17)
    assert true_name_missing_scripture["selectable_now"] is False
    assert "Requires prerequisite Talent Immortal Scripture." in _missing_reasons(true_name_missing_scripture)

    true_name_ready = _project(
        service,
        true_name_id,
        target_cl=17,
        existing_talent_ids=["tianxia.talent.ink.immortal_scripture"],
    )
    assert true_name_ready["selectable_now"] is True
    assert any(
        row["scope"] == "use_condition" and row["resolution_status"] == "unresolved"
        for row in true_name_ready["prerequisite_evaluation"]["predicate_results"]
    )


def test_representative_death_equipment_axes_shield_and_force_chains():
    service = CanonicalCatalogAuthorityService(ROOT)
    cases = [
        ("TAL_DEATH_DEATHLESS_GUARD", 5, "TAL_DEATH_CORPSE_SERVANT"),
        ("tianxia.talent.equipment.breath_aligned_armor", 5, "tianxia.talent.equipment.armor_training"),
        ("TAL_AXES_SHIELD_WALL_SPLITTER", 5, "TAL_AXES_SHIELD_CATCHING_BEARD"),
        ("TAL_SHIELD_PERFECT_REDIRECTION", 7, "TAL_SHIELD_REDIRECTING_SHIELD"),
        ("TAL_FORCE_RAMPART_OF_STILL_AIR", 10, "TAL_FORCE_FORCE_WALL"),
    ]
    for talent_id, target_cl, prerequisite_id in cases:
        missing = _project(service, talent_id, target_cl=target_cl)
        assert missing["selectable_now"] is False, talent_id
        assert any(prerequisite_id == row.get("target_id") for row in missing["prerequisite_evaluation"]["blocking_failures"]), talent_id
        ready = _project(
            service,
            talent_id,
            target_cl=target_cl,
            existing_talent_ids=[prerequisite_id],
        )
        assert ready["selectable_now"] is True, talent_id


def test_all_47_flagged_prerequisite_fields_have_individual_exact_scope_decisions():
    service = CanonicalCatalogAuthorityService(ROOT)
    fields: dict[str, list[dict[str, Any]]] = {}
    talents_by_field: dict[str, str] = {}
    for talent in service.list_talents()["records"]:
        for clause in talent["prerequisite_clauses"]:
            if "prerequisite" not in normalize(clause.get("source_field_label") or clause["label"]):
                continue
            source_field_raw = clause.get("source_field_raw_text") or clause["raw_text"]
            if not _LEGACY_BROAD_USE_CUE_RE.search(source_field_raw):
                continue
            field_id = clause.get("source_field_id") or clause["clause_id"]
            fields.setdefault(field_id, []).append(clause)
            talents_by_field[field_id] = talent["canonical_talent_id"]

    assert len(fields) == 47
    allowed_use_bases = {
        "exact_target_state_prerequisite",
        "exact_true_name_discovery_subclause",
        "exact_timing_and_wielding_subclause",
    }
    decisions = {"acquisition": 0, "use": 0, "mixed": 0}
    for field_id, clauses in fields.items():
        scopes = {row["scope"] for row in clauses}
        if scopes == {"acquisition"}:
            decisions["acquisition"] += 1
        elif scopes == {"use_condition"}:
            decisions["use"] += 1
        else:
            decisions["mixed"] += 1
        for clause in clauses:
            if clause["scope"] == "use_condition":
                assert clause["scope_basis"] in allowed_use_bases, (talents_by_field[field_id], clause)
            else:
                assert clause["scope_basis"] == "explicit_prerequisite_label", (talents_by_field[field_id], clause)

    assert decisions == {"acquisition": 44, "use": 1, "mixed": 2}


def test_unresolved_acquisition_authority_is_always_fail_closed_and_use_conditions_never_block():
    service = CanonicalCatalogAuthorityService(ROOT)
    for talent in service.list_talents()["records"]:
        unresolved_acquisition = [
            row for row in talent["typed_prerequisites"]
            if row["kind"] == "unresolved" and row["scope"] == "acquisition"
        ]
        if unresolved_acquisition:
            assert talent["creator_selectability_can_be_evaluated_safely"] is False
            assert talent["prerequisite_evaluation_status"] == "UNRESOLVED_FAIL_CLOSED"

    meridian = _project(
        service,
        "tianxia.talent.chains.meridian_chain_lock",
        target_cl=10,
    )
    assert meridian["selectable_now"] is True
    assert not meridian["prerequisite_evaluation"]["blocking_failures"]
    assert any(
        row["kind"] == "unresolved" and row["scope"] == "use_condition" and row["passed"]
        for row in meridian["prerequisite_evaluation"]["predicate_results"]
    )

    for talent_id in (
        "TAL_BEASTMASTERY_SHARED_GUARD",
        "tianxia.talent.the_hidden_eye.detect_surface_thoughts",
        "TAL_IRON_FIST_MEDICINE_OF_THE_CLOSED_GATE",
    ):
        talent = _talent(service, talent_id)
        assert talent["creator_selectability_can_be_evaluated_safely"] is False
        assert talent["prerequisite_evaluation_status"] == "UNRESOLVED_FAIL_CLOSED"


def test_heart_of_the_spear_mixed_field_is_partitioned_without_weakening_acquisition():
    service = CanonicalCatalogAuthorityService(ROOT)
    talent_id = "TAL_SPEAR_HEART_OF_THE_SPEAR"
    talent = _talent(service, talent_id)
    clauses = [row for row in talent["prerequisite_clauses"] if row["label"] == "Prerequisite"]
    assert len(clauses) == 2
    assert {row["scope"] for row in clauses} == {"acquisition", "use_condition"}
    acquisition = next(row for row in clauses if row["scope"] == "acquisition")
    execution = next(row for row in clauses if row["scope"] == "use_condition")
    assert acquisition["body"] == "CL 5+, Spear Heart"
    assert execution["scope_basis"] == "exact_timing_and_wielding_subclause"

    missing = _project(service, talent_id, target_cl=5)
    assert missing["selectable_now"] is False
    assert "Requires exact structural authority Spear-Heart." in _missing_reasons(missing)

    ready = _project(
        service,
        talent_id,
        target_cl=5,
        structural_authority_ids=["tianxia.structural.spear.spear_heart"],
    )
    assert ready["selectable_now"] is True
