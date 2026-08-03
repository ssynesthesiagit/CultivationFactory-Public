from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import FoundryError
from character_builder.service import CharacterBuilderService

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "catalog/sphere_talent_authority_v1.json"

TARGET_SPHERES = {
    "Air", "Athletics", "Brute", "Earth", "The Piercing Needle", "Glass", "Metal", "Sand",
    "Spear", "Sword", "Universal Martial", "Water", "Weather", "Wrestling",
}
SUSPICIOUS = {
    "Body Refining", "Qi Cultivation", "Spirit Awakening", "Benefit", "Allies", "Enemies",
    "You", "Focus Talents", "Domain Talents", "Base Sphere Abilities", "Special Attacks", "LIMITS",
}


def _options(catalog_environment):
    options = CharacterBuilderService(catalog_environment["db"]).options()
    categories = {category["slot_id"]: category for category in options["categories"]}
    spheres = {choice["name"]: choice for choice in categories["sphere_priorities"]["choices"]}
    talents = {choice["choice_id"]: choice for choice in categories["advancement_skeleton"]["choices"]}
    return options, categories, spheres, talents


def test_manifest_is_bound_to_pinned_factory_and_classifies_complete_candidate_set():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["authority_archive_sha256"] == "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
    assert manifest["summary"]["source_talent_candidates_examined"] == 3180
    assert len(manifest["records"]) == 3180
    assert manifest["summary"]["genuine_selectable_talents"] == 1748
    assert manifest["summary"]["rejected_non_talent_rows"] > 1600
    assert manifest["summary"]["unresolved_talent_candidates"] > 0


def test_spear_and_all_fourteen_reported_spheres_have_honest_source_dispositions(catalog_environment):
    options, _categories, spheres, talents = _options(catalog_environment)
    index = options["sphere_talent_index"]
    assert TARGET_SPHERES - {"Universal Martial"} <= set(spheres)
    assert "Universal Martial" not in spheres
    assert "Fencing" not in spheres
    for name in sorted(TARGET_SPHERES - {"Universal Martial"}):
        sphere = spheres[name]
        coverage = index["per_sphere_coverage"][sphere["choice_id"]]
        assert coverage["talent_count"] > 0, name
        assert "canonical Talents" in coverage["honest_label"]
    assert index["audit"]["owner_hidden_source_authority_gap_ids"] == []

    spear_ids = index["by_sphere"][spheres["Spear"]["choice_id"]]
    spear_names = {talents[record_id].get("canonical_name") or talents[record_id]["name"] for record_id in spear_ids}
    assert {"Intercepting Thrust", "Spear Guard", "Pinning Strike"} <= spear_names
    assert not {"TAL_SPEAR_KEEP_AWAY", "TAL_SPEAR_SET_CHARGE", "TAL_SPEAR_SWEEP_TRIP"} & set(talents)
    for legacy_id in ("TAL_SPEAR_KEEP_AWAY", "TAL_SPEAR_SET_CHARGE", "TAL_SPEAR_SWEEP_TRIP"):
        assert options["legacy_talent_findings"][legacy_id]["source_role"] == "unresolved_candidate"


def test_non_talent_headings_are_rejected_at_catalog_boundary(catalog_environment):
    options, categories, _spheres, _talents = _options(catalog_environment)
    selectable_names = {
        choice.get("canonical_name") or choice["name"]
        for choice in categories["advancement_skeleton"]["choices"]
    }
    assert not (SUSPICIOUS & selectable_names)
    findings = options["legacy_talent_findings"]
    assert findings["TAL_SPACE_BODY_REFINING"]["source_role"] == "path_expression"
    assert findings["TAL_FLOWERS_ALLIES"]["source_role"] == "structural_label"
    assert findings["TAL_BERSERKER_BENEFIT"]["source_role"] == "variant_expression"


def test_every_emitted_talent_id_is_unique_and_exactly_mapped(catalog_environment):
    options, categories, spheres, talents = _options(catalog_environment)
    index = options["sphere_talent_index"]
    choice_ids = [choice["choice_id"] for choice in categories["advancement_skeleton"]["choices"]]
    assert len(choice_ids) == len(set(choice_ids))
    assert index["audit"]["mapped_talent_count"] == len(choice_ids)
    assert index["audit"]["ambiguous_talent_count"] == 0
    assert index["audit"]["unassigned_talent_count"] == 0
    for talent_id, sphere_ids in index["by_talent"].items():
        assert talent_id in talents
        assert len(sphere_ids) == 1
        sphere_id = sphere_ids[0]
        assert sphere_id in {row["choice_id"] for row in spheres.values()}
        assert talent_id in index["by_sphere"][sphere_id]


def test_legacy_misclassified_selection_is_preserved_for_review_and_not_substituted(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    options = service.options()
    finding = options["legacy_talent_findings"]["TAL_SPACE_BODY_REFINING"]
    assert finding["source_role"] == "path_expression"
    assert "no automatic substitution" in finding["resolution"].casefold()
    with pytest.raises(FoundryError) as exc:
        service._validated_selections({"advancement_skeleton": ["TAL_SPACE_BODY_REFINING"]})
    assert exc.value.code == "CHARACTER_SHEET_LEGACY_NON_TALENT_SELECTION"
    assert exc.value.details["choice_ids"] == ["TAL_SPACE_BODY_REFINING"]


def test_genuine_existing_id_and_background_talent_surface_remain_compatible(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    options, categories, _spheres, talents = _options(catalog_environment)
    assert "TAL_VOID_HOLLOW_TOUCH" in talents
    normalized, _ = service._validated_selections({"advancement_skeleton": ["TAL_VOID_HOLLOW_TOUCH"]})
    assert normalized["advancement_skeleton"] == ["TAL_VOID_HOLLOW_TOUCH"]
    background_talents = categories["background_talent_choice"]["choices"]
    assert background_talents
    assert all(choice["content_type"] == "background_talent" for choice in background_talents)
    assert not ({choice["choice_id"] for choice in background_talents} & set(talents))


def test_owner_facing_copy_reports_two_direction_coverage_without_false_all_mapped_claim():
    javascript = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "mapped Talents" not in javascript
    assert "verified Spheres" not in javascript
    assert "source-authorized Talent" in javascript
    assert "Canonical catalog authority" in javascript
    assert "Unavailable zero-talent Spheres remain visible in the list with an exact reason but cannot be added." in javascript
    assert 'choice.unavailable_reason || "not creator-ready"' in javascript
    assert "No source-authorized Talent is available for this Sphere." in javascript
    assert "Granted automatically; cannot be removed" in javascript
    assert "One free talent per acquired Sphere" in javascript
    assert "Planning preference only — no Sphere acquisition or free grant." in javascript
