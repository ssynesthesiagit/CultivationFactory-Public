from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from app.core import FoundryError
from character_builder import CharacterBuilderService


ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "catalog_authority" / "cat3" / "generated"
SOURCE = ROOT / "catalog_authority" / "cat3" / "source"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _generated() -> dict:
    return _json(GENERATED / "catalog_authority.v1.json")


def _sphere_by_name(authority: dict) -> dict[str, dict]:
    return {row["display_name"]: row for row in authority["spheres"]}


def test_rec1_p1b_insight_authority_accounting_and_runtime_boundary(catalog_environment):
    authority = _generated()
    audit = authority["insight_authority_audit"]
    r2 = _json(SOURCE / "Tianxia_Central_Cultivation_Insights_AI_Reference_R5_Legacy_Restored.json")
    rows = {row["canonical_insight_id"]: row for row in authority["insights"]}

    assert len(rows) == 547
    assert sum(row["selectable"] is True for row in authority["insights"]) == 542
    assert sum(len(row.get("source_occurrences") or []) for row in authority["insights"]) == 550
    assert authority["counts"]["selectable_insight_source_occurrences"] == 545
    assert authority["counts"]["insight_unique_source_catalog_ids"] == 547
    assert audit["current_selectable_count"] == 451
    assert audit["preserved_selectable_count"] == 451
    assert audit["restored_selectable_count"] == 91
    assert audit["retained_nonselectable_count"] == 5
    assert audit["selectable_canonical_count"] == 542
    assert audit["selectable_source_occurrence_count"] == 545
    assert audit["total_source_occurrence_count"] == 550
    assert audit["unique_source_catalog_id_count"] == 547
    assert audit["sphere_facet_membership_count"] == 325
    assert audit["type_counts"] == {
        "Companion": 3,
        "General Cultivation": 23,
        "Metatechnique": 7,
        "Narrative / Secret": 6,
        "Path": 172,
        "Sphere": 324,
        "Technique-Forging": 7,
    }
    assert audit["duplicate_occurrence_groups"] == {
        "insight.jade-inscription-master": [
            "qi-path.qi-cultivation.jade-inscription-master",
            "sphere-compendium.talismans.jade-inscription-master",
        ],
        "insight.seal-breaker": [
            "qi-path.qi-cultivation.seal-breaker",
            "sphere-compendium.talismans.seal-breaker",
        ],
        "insight.talisman-savant": [
            "qi-path.qi-cultivation.talisman-savant",
            "sphere-compendium.talismans.talisman-savant",
        ],
    }
    assert audit["name_collision_records"] == {
        "formation breaker": [
            "insight.formation-breaker-destruction",
            "insight.formation-breaker-lightning",
        ],
    }
    assert audit["changed_mechanic_coexistence_count"] == 38
    assert audit["old_carried_forward_count"] == 13
    assert audit["formal_superseded_source_occurrence_count"] == 3
    assert audit["canonical_ids_superseded_by_different_id"] == 0

    r2_selectable = {
        row["canonical_id"] for row in r2["records"] if row.get("selectable") is True
    }
    assert set(audit["selectable_canonical_ids"]) == r2_selectable
    assert set(audit["restored_selectable_ids"]) == (
        set(audit["selectable_canonical_ids"]) - set(audit["current_selectable_ids"])
    )
    assert set(audit["retained_nonselectable_ids"]) == {
        row["canonical_id"] for row in r2["records"] if row.get("selectable") is not True
    }

    dual = rows["insight.legacy-dual-cultivation"]
    assert dual["prerequisites"] == []
    assert dual["raw_source_record"]["compiled_prerequisite_ledger"]["source_terms_preserved"]
    assert all(row["source_occurrences"] for row in authority["insights"])

    builder = CharacterBuilderService(catalog_environment["db"])
    options = builder.options()
    ordinary = next(row for row in options["categories"] if row["slot_id"] == "insight_priorities")
    ordinary_choices = ordinary["choices"]
    assert len(ordinary_choices) == 542
    assert {row["choice_id"] for row in ordinary_choices} == set(audit["selectable_canonical_ids"])
    assert all(row["content_type"] != "origin_insight" for row in ordinary_choices)
    assert all(
        (row.get("insight_authority") or {}).get("authority_type") != "Background-Origin"
        for row in ordinary_choices
    )
    assert Counter(
        row["insight_authority"]["authority_type"] for row in ordinary_choices
    ) == Counter(audit["type_counts"])

    origin = next(row for row in options["categories"] if row["slot_id"] == "origin_insight_choice")
    assert len(origin["choices"]) == 50
    assert all(row["content_type"] == "origin_insight" for row in origin["choices"])
    assert all(
        row["insight_authority"]["preference_only"] is True
        and row["insight_authority"]["classification_code"] == "EXPLICIT_BACKGROUND_ORIGIN_INSIGHT_AUTHORITY"
        for row in origin["choices"]
    )
    assert all(row.get("ns1r_exact_origin_insight_authority") for row in origin["choices"])

    expanded = next(row for row in ordinary_choices if row["choice_id"] == "insight.expanded-dantian")
    assert expanded["insight_authority"]["source_reference"]["source_record_sha256"] == rows[
        "insight.expanded-dantian"
    ]["source_provenance"]["source_record_sha256"]
    for nonselectable_id in audit["retained_nonselectable_ids"]:
        with pytest.raises(FoundryError) as exc:
            builder._validated_selections({"insight_priorities": [nonselectable_id]})
        assert exc.value.code == "CHARACTER_SHEET_CHOICE_UNAVAILABLE"


def test_rec1_p1b_sphere_matrix_projects_exact_source_packages(catalog_environment):
    authority = _generated()
    matrix = authority["sphere_base_ability_authority_matrix"]
    spheres = _sphere_by_name(authority)
    matrix_spheres = {row["display_name"]: row for row in matrix["spheres"]}

    assert len(spheres) == 85
    assert len(matrix_spheres) == 85
    assert matrix["source_component_count"] == 291
    assert matrix["resolved_unique_component_count"] == 291
    assert matrix["classification_counts"] == {
        "PRESENT_AND_RENDERABLE": 1,
        "SOURCE_AMBIGUOUS_OWNER_ADJUDICATION_REQUIRED": 1,
        "SOURCE_HAS_BASE_ABILITY_PROJECTION_MISSING": 83,
    }
    assert matrix["current_projection_state_counts"] == {
        "EMPTY": 44,
        "PRESENT_COMPLETE": 1,
        "PRESENT_INCOMPLETE": 40,
    }

    all_component_ids = []
    with (SOURCE / "SPHERE_BASE_ABILITY_MATRIX.csv").open(encoding="utf-8", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    assert len(source_rows) == 85
    for source_row in source_rows:
        sphere_name = source_row["sphere_name"]
        sphere = spheres[sphere_name]
        matrix_row = matrix_spheres[sphere_name]
        package = sphere["resolved_automatic_base_abilities"]
        expected_player = {
            item["component_name"]: item["exact_source_excerpt"]
            for item in json.loads(source_row["source_component_player_text_json"])
        }
        expected_fields = {
            item["component_name"]: item["structured_fields"]
            for item in json.loads(source_row["source_component_player_text_json"])
        }
        actual = {item["source_component_name"]: item for item in package}
        assert len(package) == int(source_row["source_component_count"])
        assert len(package) == matrix_row["resolved_component_count"]
        assert set(actual) == set(expected_player)
        for component_name, exact_text in expected_player.items():
            component = actual[component_name]
            assert component["player_rules_text"] == exact_text
            assert component["full_description"] == exact_text
            assert component["effect"] == exact_text
            assert component["source_component_structured_fields"] == expected_fields[component_name]
            assert component["automatic_grant"] is True
            assert component["owner_removable"] is False
            assert component["counts_as_talent_choice"] is False
            assert component["counts_as_advancement_talent"] is False
            assert component["counts_as_training_talent"] is False
            all_component_ids.append(component["runtime_component_id"])

    assert len(all_component_ids) == 291
    assert len(set(all_component_ids)) == 291
    retribution = matrix_spheres["Retribution"]
    assert retribution["current_projection_state"] == "EMPTY"
    assert retribution["package_resolution"] == "owner_ruling_resolved"
    assert retribution["source_component_names"] == ["Martial Focus", "Counterstrike"]
    assert retribution["owner_ruling"]["statement"].startswith(
        "The owner-facing automatic Retribution package grants Martial Focus and Counterstrike"
    )
    assert retribution["owner_ruling"]["source_basis"]["source_section"].endswith(
        "CORE RETRIBUTION RULES"
    )
    assert matrix_spheres["Karma"]["current_projection_state"] == "PRESENT_COMPLETE"

    catalog = CharacterBuilderService(catalog_environment["db"]).canonical_catalog
    assert catalog.list_spheres()["count"] == 85
    air = catalog.get_sphere("Air")
    assert len(air["automatic_base_abilities"]) == 3
    assert {row["source_component_name"] for row in air["automatic_base_abilities"]} == {
        "Wind-Hand Training", "Gather Current", "Wind Lash",
    }
