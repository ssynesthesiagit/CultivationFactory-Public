"""Source Training acquisition contracts; these do not claim combat delivery."""
from hashlib import sha256
import json
from pathlib import Path

from app.core import Database
from canonical_catalog import CanonicalCatalogAuthorityService
from character_builder.service import CharacterBuilderService
from project_store.service import ProjectStore


ROOT = Path(__file__).resolve().parents[1]
SPHERE = "tianxia.sphere.source"
COMPONENTS = {
    "SOURCE_BASE_SOURCE_TRAINING", "SOURCE_BASE_SOURCE_READING",
    "SOURCE_BASE_SOURCE_PULSE", "SOURCE_BASE_SOURCE_SEAL",
}


def _catalog():
    return CanonicalCatalogAuthorityService(ROOT)


def _free_talent(service):
    projection = service.creator_projection(target_cl=1, acquired_sphere_ids=[SPHERE])
    return next(row["canonical_talent_id"] for row in projection["talent_dispositions"]
                if row["owning_canonical_sphere_id"] == SPHERE and row["selectable_now"])


def _check_plan(plan, talent):
    accounting = plan["grant_accounting"]
    assert {row["base_ability_id"] for row in accounting["automatic_base_abilities"]} == COMPONENTS
    assert accounting["automatic_base_abilities_counted_as_talent_choices"] == 0
    assert accounting["free_sphere_talent_grant_count"] == 1
    assert accounting["ordinary_talent_cost_count"] == 0
    assert accounting["total_distinct_talent_ids"] == 1
    assert accounting["free_sphere_talent_grants"] == [{
        "sphere_id": SPHERE, "talent_id": talent,
        "ordinary_slot_cost": 0, "training_slot_cost": 0,
    }]


def test_source_training_source_hash_and_surrounding_package():
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    assert sha256(rules["SOURCE_BASE_SOURCE_TRAINING"].encode()).hexdigest() == (
        "16c451520adae60673456fb6a374080a349a4ab571c24beb201c259838a8bef3")
    authority = json.loads((ROOT / "catalog_authority/cat3/generated/catalog_authority.v1.json").read_text())
    sphere = next(row for row in authority["spheres"] if row["canonical_sphere_id"] == SPHERE)
    assert sha256(sphere["full_exact_source_text"].encode()).hexdigest() == sphere["source_provenance"]["source_context_sha256"]
    assert {row["runtime_component_id"] for row in sphere["resolved_automatic_base_abilities"]} == COMPONENTS


def test_source_training_requires_owner_choice_and_grants_once():
    service = _catalog()
    missing = service.creator_projection(target_cl=1, acquired_sphere_ids=[SPHERE])
    assert not missing["ready"]
    assert any(row["code"] == "FREE_SPHERE_TALENT_REQUIRED" for row in missing["validation_errors"])
    wrong = service.creator_projection(target_cl=1, acquired_sphere_ids=[SPHERE],
        free_talent_grants={SPHERE: "TAL_ATHLETICS_WALL_STUNT"})
    assert not wrong["ready"]
    assert any(row["code"] == "FREE_SPHERE_TALENT_WRONG_SPHERE" for row in wrong["validation_errors"])
    talent = _free_talent(service)
    plan = service.validate_grant_plan(target_cl=1, acquired_sphere_ids=[SPHERE, SPHERE],
                                     free_talent_grants={SPHERE: talent}, ordinary_talent_ids=[])
    _check_plan(plan, talent)
    other = service.creator_projection(target_cl=1, acquired_sphere_ids=[])
    assert not COMPONENTS.intersection(row["base_ability_id"] for row in other["grant_accounting"]["automatic_base_abilities"])


def test_source_training_native_builder_draft_cold_reopen(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    talent = _free_talent(builder.canonical_catalog)
    created = builder.create_project(
        working_name="Source Training contract", concept="A novice Source cultivator.",
        target_cl=1, power_band="standard", source_reference="Source Training rules",
        creation_mode="detailed", ability_scores={}, selections={},
        sphere_priority_ids=[SPHERE], talent_priority_ids=[talent],
        canonical_sphere_ids=[SPHERE], sphere_free_talent_grants={SPHERE: talent},
        ordinary_talent_ids=[],
    )
    project_id = created["project"]["project_id"]
    builder.projects.save_builder_draft(project_id)
    reopened = ProjectStore(Database(db.settings)).get_project(project_id)
    locks = {row["field"]: row["value"] for row in reopened["project"]["user_locks"]}
    _check_plan(locks["character_sheet.canonical_grant_plan"], talent)
