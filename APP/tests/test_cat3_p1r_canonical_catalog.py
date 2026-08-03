from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from app.core import FoundryError
from canonical_catalog import CanonicalCatalogAuthorityService
from catalog_authority.cat3.compiler import build

ROOT = Path(__file__).resolve().parents[1]


def _service() -> CanonicalCatalogAuthorityService:
    return CanonicalCatalogAuthorityService(ROOT)


def _talent(sphere: str, name: str) -> dict:
    return next(
        row for row in _service().list_talents(sphere_id=sphere)["records"]
        if row["display_name"] == name
    )


def test_two_run_compiler_is_byte_deterministic(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    build(ROOT, first)
    build(ROOT, second)
    first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    second_files = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    assert first_files == second_files
    assert all((first / path).read_bytes() == (second / path).read_bytes() for path in first_files)


def test_structural_and_inline_boundary_regressions():
    service = _service()
    all_rows = service.list_talents()["records"]
    keys = {(row["owning_canonical_sphere_name"], row["display_name"]) for row in all_rows}
    false_rows = {
        ("Beauty", "Cultivation Insights"), ("Equipment", "Armor Traditions"),
        ("Source", "Source Traditions"), ("Weapons", "Weapon Catalogue"),
        ("Weapons", "Path Expression Notes"), ("Weapons", "Character Sheet Notes"),
    }
    assert not (false_rows & keys)
    fixtures = {
        ("Athletics", "Flowing Pursuit"), ("Barrage", "Needle-Rain Burst"),
        ("Barrage", "Heaven-Splitting Line"), ("Beastmastery", "Beastback Relay"),
        ("Blood", "Heartblood Rebirth"), ("Dreams", "Symbolic Shelter"),
        ("Protection", "Community"),
    }
    assert fixtures <= keys
    assert not any(re.search(r"(?m)^#{1,6}\s|\s#{1,6}\s", row["full_description"]) for row in all_rows)


def test_realm_word_and_cl7_typing():
    fixtures = {
        ("tianxia.sphere.equipment", "Black Armor Legion Scripture"): (5, "Foundation"),
        ("tianxia.sphere.source", "Source-Heaven Scripture"): (5, "Foundation"),
        ("tianxia.sphere.source", "Source-Heaven Sealing Scripture"): (10, "Core Formation"),
        ("tianxia.sphere.equipment", "Ancestral Battle Dress Scripture"): (15, "Nascent Soul"),
        ("tianxia.sphere.ice", "The World Becomes a Single Crystal"): (15, "Nascent Soul"),
        ("tianxia.sphere.athletics", "Flowing Pursuit"): (7, "Foundation"),
    }
    for (sphere_id, name), expected in fixtures.items():
        row = _talent(sphere_id, name)
        assert (row["minimum_cl"], row["realm_band"]) == expected


def test_false_forbidden_prose_does_not_classify_access():
    fixtures = [
        ("tianxia.sphere.harvesting_gathering", "Formation-Ward Harvest"),
        ("tianxia.sphere.hunger", "Hunger-Sense Meridian"),
        ("tianxia.sphere.sect_stewardship", "Inner Archive Index"),
        ("tianxia.sphere.talismans", "Heavenly Seal"),
        ("tianxia.sphere.unmaking", "Devouring Dregs"),
        ("tianxia.sphere.spear", "Spear Pressure"),
    ]
    assert all(_talent(sphere, name)["access_category"] == "Open" for sphere, name in fixtures)


def test_every_prerequisite_clause_is_typed_or_explicitly_unresolved():
    for row in _service().list_talents()["records"]:
        if not row["raw_prerequisite_text"]:
            continue
        assert row["prerequisite_clauses"]
        predicates = {predicate["predicate_id"]: predicate for predicate in row["typed_prerequisites"]}
        for clause in row["prerequisite_clauses"]:
            assert clause["alternatives"]
            for alternative in clause["alternatives"]:
                assert alternative["predicate_ids"]
                assert all(predicate_id in predicates for predicate_id in alternative["predicate_ids"])
        unresolved = any(p["kind"] == "unresolved" and p["scope"] == "acquisition" for p in predicates.values())
        assert row["creator_selectability_can_be_evaluated_safely"] is (not unresolved)


def test_prerequisite_talent_chain_and_unresolved_fail_closed():
    service = _service()
    rows = service.list_talents()["records"]
    chained = next(
        row for row in rows
        if row["creator_selectability_can_be_evaluated_safely"]
        and any(p["kind"] == "talent" and p["scope"] == "acquisition" for p in row["typed_prerequisites"])
        and row["free_sphere_talent_eligible"]
    )
    prerequisite = next(p for p in chained["typed_prerequisites"] if p["kind"] == "talent" and p["scope"] == "acquisition")
    sphere_id = chained["owning_canonical_sphere_id"]
    without = service.creator_projection(target_cl=20, acquired_sphere_ids=[sphere_id])
    without_row = next(row for row in without["talent_dispositions"] if row["canonical_talent_id"] == chained["canonical_talent_id"])
    assert not without_row["selectable_now"]
    with_chain = service.creator_projection(target_cl=20, acquired_sphere_ids=[sphere_id], existing_talent_ids=[prerequisite["target_id"]])
    with_row = next(row for row in with_chain["talent_dispositions"] if row["canonical_talent_id"] == chained["canonical_talent_id"])
    assert with_row["selectable_now"]

    unresolved = next(row for row in rows if row["prerequisite_evaluation_status"] == "UNRESOLVED_FAIL_CLOSED")
    projection = service.creator_projection(target_cl=20, acquired_sphere_ids=[unresolved["owning_canonical_sphere_id"]])
    disposition = next(row for row in projection["talent_dispositions"] if row["canonical_talent_id"] == unresolved["canonical_talent_id"])
    assert not disposition["selectable_now"]
    assert disposition["disposition"] == "locked_by_unresolved_prerequisite"
    assert "Unresolved exact authority phrase" in disposition["owner_reason"]


def test_dark_base_source_rows_preserved_but_runtime_unique():
    service = _service()
    diagnostics = service.diagnostics()["automatic_base_abilities"]
    assert diagnostics["source_row_count"] == 126
    assert diagnostics["unique_component_count"] == 125
    dark = service.get_sphere("Dark")["automatic_base_abilities"]
    assert [row["base_ability_id"] for row in dark].count("DARK_BASE_DARKNESS") == 1
    assert diagnostics["aliases"][0]["legacy_id"] == "TAL_DARK_DARKNESS"


def test_legacy_space_path_expression_is_review_compatible_not_selectable():
    service = _service()
    with pytest.raises(FoundryError) as exc:
        service.get_talent("TAL_SPACE_BODY_REFINING")
    assert exc.value.code == "CANONICAL_LEGACY_NON_TALENT"
    assert exc.value.details["finding"]["source_role"] == "path_expression"


def test_restricted_initial_creation_priority_surface():
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "Restricted initial-creation priority" in script
    assert "post-creation mutation still requires exact evidence" in script
    assert 'if (restricted || talent.planning_priority_available === false)' not in script
