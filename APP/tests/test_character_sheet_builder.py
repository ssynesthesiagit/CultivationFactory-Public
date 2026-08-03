from __future__ import annotations

import pytest

from app.core import FoundryError
from character_builder.service import CharacterBuilderService
from non_sphere_authority import NonSphereAuthorityService
from stage1.service import Stage1ClipboardService


def test_partial_point_buy_leaves_legal_budget_for_factory():
    result = CharacterBuilderService.validate_point_buy({"STR": 15, "CON": 14, "WIS": 12})
    assert result["points_spent"] == 20
    assert result["points_remaining"] == 7
    assert result["fixed_scores"] == {"STR": 15, "CON": 14, "WIS": 12}
    assert set(result["auto_abilities"]) == {"DEX", "INT", "CHA"}
    assert result["completion"] == "factory_to_complete"


def test_complete_point_buy_must_use_exactly_27_points():
    with pytest.raises(FoundryError) as exc:
        CharacterBuilderService.validate_point_buy({
            "STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10,
        })
    assert exc.value.code == "CHARACTER_SHEET_POINT_BUY_INCOMPLETE"

    result = CharacterBuilderService.validate_point_buy({
        "STR": 15, "DEX": 14, "CON": 13, "INT": 12, "WIS": 10, "CHA": 8,
    })
    assert result["points_spent"] == 27
    assert result["auto_abilities"] == []
    assert result["completion"] == "owner_complete"


def test_character_sheet_options_are_catalog_backed(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    result = service.options()
    categories = {category["slot_id"]: category for category in result["categories"]}

    assert result["schema_version"] == "TianxiaFoundry.CharacterSheetOptions.v3"
    assert result["point_buy"]["budget"] == 27
    assert set(result["point_buy"]["abilities"]) == {"STR", "DEX", "CON", "INT", "WIS", "CHA"}
    assert categories["path_choice"]["status"] == "offered"
    assert categories["path_choice"]["choices"]
    for slot_id in ("subpath_choice", "sphere_priorities", "advancement_skeleton", "insight_priorities"):
        assert categories[slot_id]["status"] == "offered"
        assert categories[slot_id]["choices"]
        assert categories[slot_id]["selection_semantics"] == "blueprint_intent_only"
    assert categories["item_priorities"]["status"] == "offered"
    assert categories["item_priorities"]["choices"]
    expected_background_counts = {
        "background_choice": 31,
        "background_sphere_choice": 30,
        "background_talent_choice": 77,
        "origin_insight_choice": 50,
    }
    for slot_id, expected_count in expected_background_counts.items():
        assert categories[slot_id]["status"] == "offered"
        assert len(categories[slot_id]["choices"]) == expected_count
        assert categories[slot_id]["selection_semantics"] == "strict_authority"
    for choice in categories["path_choice"]["choices"]:
        assert choice["choice_id"]
        assert choice["pack_id"]
        assert choice["pack_version"]


def test_background_sheet_choices_must_belong_together(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    categories = {category["slot_id"]: category for category in service.options()["categories"]}
    background = categories["background_choice"]["choices"][0]
    related = set(background["related_choice_ids"])
    talent = next(choice for choice in categories["background_talent_choice"]["choices"] if choice["choice_id"] in related)
    sphere = next(
        choice for choice in categories["background_sphere_choice"]["choices"]
        if choice["choice_id"] in related and choice["choice_id"] in set(talent["related_choice_ids"])
    )
    origin = next(choice for choice in categories["origin_insight_choice"]["choices"] if choice["choice_id"] in related)
    selected = {
        "background_choice": [background["choice_id"]],
        "background_sphere_choice": [sphere["choice_id"]],
        "background_talent_choice": [talent["choice_id"]],
        "origin_insight_choice": [origin["choice_id"]],
    }
    normalized, _records = service._validated_selections(selected)
    assert normalized == selected

    incompatible = next(choice for choice in categories["origin_insight_choice"]["choices"] if choice["choice_id"] not in related)
    with pytest.raises(FoundryError) as exc:
        service._validated_selections({
            "background_choice": [background["choice_id"]],
            "origin_insight_choice": [incompatible["choice_id"]],
        })
    assert exc.value.code == "CHARACTER_SHEET_BACKGROUND_CHOICE_MISMATCH"


def test_background_sheet_projection_excludes_cross_route_sphere_talent_pairs(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    categories = {category["slot_id"]: category for category in service.options()["categories"]}
    background = next(
        choice for choice in categories["background_choice"]["choices"]
        if len(choice.get("ns1r_exact_route_authority", {}).get("route_options", [])) > 1
    )
    routes = background["ns1r_exact_route_authority"]["route_options"]
    first = routes[0]
    crossed = next(
        route for route in routes
        if route["background_sphere_choice_id"] != first["background_sphere_choice_id"]
    )
    selected_sphere = next(
        choice for choice in categories["background_sphere_choice"]["choices"]
        if choice["choice_id"] == first["background_sphere_choice_id"]
    )
    exact_talent_ids = {
        route["background_talent_choice_id"]
        for route in routes
        if route["background_sphere_choice_id"] == first["background_sphere_choice_id"]
    }
    # A broad Background membership can see the other route's Talent, but the
    # exact route projection exposed to the UI cannot.
    assert crossed["background_talent_choice_id"] in set(background["related_choice_ids"])
    assert crossed["background_talent_choice_id"] not in exact_talent_ids
    assert selected_sphere["choice_id"] == first["background_sphere_choice_id"]


def test_detailed_sheet_creates_project_and_binds_owner_locks(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    options = service.options()
    categories = {category["slot_id"]: category for category in options["categories"]}
    path_id = categories["path_choice"]["choices"][0]["choice_id"]

    created = service.create_project(
        working_name="Sheet Lock Test",
        concept="A precise cultivator used to verify owner-locked character choices.",
        target_cl=15,
        power_band="heroic",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={"STR": 15, "CON": 14, "WIS": 12},
        selections={"path_choice": [path_id]},
    )
    project = created["project"]
    locks = {lock["field"]: lock["value"] for lock in project["user_locks"]}
    assert locks["character_sheet.creation_mode"] == "detailed"
    assert locks["character_sheet.locked_choices"] == {"path_choice": [path_id]}
    assert locks["preferred_record_ids"] == [path_id]
    assert created["character_sheet"]["ability_point_buy"]["points_remaining"] == 7

    prompt = Stage1ClipboardService(catalog_environment["db"]).generate_prompt(project["project_id"])
    slots = {slot["slot_id"]: slot for slot in prompt["envelope"]["decision_slots"]}
    assert slots["path_choice"]["required_choice_ids"] == [path_id]

    decisions = []
    for slot in prompt["envelope"]["decision_slots"]:
        if slot["coverage_state"] == "blocked_missing_authority":
            decisions.append({
                "slot_id": slot["slot_id"],
                "state": "blocked_missing_authority",
                "choice_ids": [],
                "reason_code": slot["blocked_reason_code"],
                "reason": slot["blocked_reason"],
            })
        elif slot["slot_id"] == "path_choice":
            decisions.append({"slot_id": slot["slot_id"], "state": "selected", "choice_ids": []})
        elif slot["allow_none"]:
            decisions.append({
                "slot_id": slot["slot_id"],
                "state": "explicit_none",
                "choice_ids": [],
                "reason_code": "legal_none",
                "reason": "Left open for later Factory completion.",
            })
        else:
            decisions.append({"slot_id": slot["slot_id"], "state": "selected", "choice_ids": [slot["choices"][0]["choice_id"]]})
    diagnostics = Stage1ClipboardService._decision_diagnostics({"decisions": decisions}, prompt["envelope"] )
    assert "OWNER_LOCKED_CHOICE_OMITTED" in {diagnostic["code"] for diagnostic in diagnostics}


def test_character_sheet_options_dedupe_and_sphere_talent_mapping(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    result = service.options()
    categories = {category["slot_id"]: category for category in result["categories"]}

    for category in result["categories"]:
        choice_ids = [choice["choice_id"] for choice in category["choices"]]
        assert len(choice_ids) == len(set(choice_ids)), category["slot_id"]

    sphere_choices = categories["sphere_priorities"]["choices"]
    talent_choices = categories["advancement_skeleton"]["choices"]
    canonical_count = result["canonical_catalog_authority"]["canonical_talent_count"]
    assert sum(choice["choice_id"] == "tianxia.sphere.harvesting_gathering" for choice in sphere_choices) == 1
    assert len(sphere_choices) == 85
    assert len(talent_choices) == canonical_count

    index = result["sphere_talent_index"]
    assert index["schema"] == "TianxiaFoundry.CanonicalSphereTalentIndex.v1"
    audit = index["audit"]
    assert audit["sphere_count"] == 85
    assert audit["catalog_sphere_candidate_count"] == 85
    assert audit["owner_hidden_source_authority_gap_count"] == 0
    assert audit["owner_hidden_source_authority_gap_ids"] == []
    assert audit["talent_count"] == canonical_count
    assert audit["mapped_talent_count"] == canonical_count
    assert audit["ambiguous_talent_count"] == 0
    assert audit["unassigned_talent_count"] == 0
    assert audit["multi_sphere_talent_count"] == 0
    assert index["unassigned_talent_ids"] == []
    by_talent_choice = {choice["choice_id"]: choice for choice in talent_choices}
    for sphere in sphere_choices:
        assert set(sphere["related_choice_ids"]) == set(index["by_sphere"][sphere["choice_id"]])
        for talent_id in sphere["related_choice_ids"]:
            assert sphere["choice_id"] in by_talent_choice[talent_id]["sphere_choice_ids"]
    assert all(choice["mapping_status"] == "mapped" for choice in talent_choices)


def test_structural_same_name_rows_are_not_selectable_talents(catalog_environment):
    options = CharacterBuilderService(catalog_environment["db"]).options()
    talents = next(category for category in options["categories"] if category["slot_id"] == "advancement_skeleton")["choices"]
    names = {choice.get("canonical_name") or choice["name"] for choice in talents}
    assert "Allies" not in names
    assert "Enemies" not in names
    assert "Benefit" not in names
    assert "Body Refining" not in names
    findings = options["legacy_talent_findings"]
    assert findings["TAL_FLOWERS_ALLIES"]["source_role"] == "structural_label"
    assert findings["TAL_SPACE_BODY_REFINING"]["source_role"] == "path_expression"


def test_flat_multi_sphere_talent_selection_is_stored_once(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    options = service.options()
    categories = {category["slot_id"]: category for category in options["categories"]}
    sphere_ids = [choice["choice_id"] for choice in categories["sphere_priorities"]["choices"][:2]]
    talent_id = categories["advancement_skeleton"]["choices"][0]["choice_id"]
    normalized, _records = service._validated_selections({
        "sphere_priorities": sphere_ids,
        "advancement_skeleton": [talent_id, talent_id],
    })
    assert normalized["advancement_skeleton"] == [talent_id]


def test_restricted_method_builder_creation_requires_exact_access(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    categories = {category["slot_id"]: category for category in service.options()["categories"]}
    method = next(choice for choice in categories["method_choice"]["choices"] if choice["choice_id"] == "METHOD-002")
    path_id = method["related_choice_ids"][0]
    selections = {"path_choice": [path_id], "method_choice": ["METHOD-002"]}
    kwargs = {
        "working_name": "Restricted Method Builder Gate",
        "concept": "Authority enforcement regression",
        "target_cl": 1,
        "power_band": "rival/boss",
        "source_reference": None,
        "creation_mode": "detailed",
        "ability_scores": {},
        "selections": selections,
    }
    with pytest.raises(FoundryError) as exc:
        service.create_project(**kwargs)
    assert exc.value.code == "NS1R_METHOD_ACCESS_REQUIRED"

    with pytest.raises(FoundryError) as exc:
        service.create_project(
            **kwargs,
            access_source_records=[{
                "authority_type": "method_access",
                "method_id": "METHOD-002",
                "source_record_id": "builder.method.002.accepted.manual",
            }],
        )
    assert exc.value.code == "NS1R_ACCESS_SOURCE_INVALID"


def test_open_initial_methods_use_typed_path_grants_without_post_creation_access(catalog_environment):
    service = CharacterBuilderService(catalog_environment["db"])
    categories = {category["slot_id"]: category for category in service.options()["categories"]}
    methods = {choice["choice_id"]: choice for choice in categories["method_choice"]["choices"]}
    assert methods["METHOD-081"]["initial_creation_selectable"] is True
    assert methods["METHOD-081"]["related_choice_ids"] == [
        "tianxia.path.body_refining", "tianxia.path.qi_cultivation"
    ]
    assert methods["METHOD-002"]["initial_creation_selectable"] is False

    created = service.create_project(
        working_name="Open Method Initial Creation",
        concept="Two-path initial creation authority regression",
        target_cl=1,
        power_band="rival/boss",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={
            "path_choice": methods["METHOD-081"]["related_choice_ids"],
            "method_choice": ["METHOD-081"],
        },
    )
    state = created["character_sheet"]["non_sphere_state"]
    assert state["primary_method_id"] == "METHOD-081"
    assert state["readiness"]["status"] == "READY"
    assert not any(row["code"] == "METHOD_ACQUISITION_EVIDENCE_REQUIRED" for row in state["readiness"]["blockers"])
    reopened_state = NonSphereAuthorityService(catalog_environment["db"]).get_state(created["project_id"])
    assert reopened_state["readiness"]["status"] == "READY"
    assert reopened_state["initial_creation_method_ids"] == ["METHOD-081"]


def test_foundation_dropdown_projection_is_owner_facing_and_insights_are_grouped(catalog_environment):
    options = CharacterBuilderService(catalog_environment["db"]).options()
    categories = {category["slot_id"]: category for category in options["categories"]}
    foundations = categories["foundation_choice"]["choices"]
    assert foundations
    assert all("subsystem" not in choice["description"].casefold() for choice in foundations)
    assert all(choice["description"] for choice in foundations)
    insights = categories["insight_priorities"]
    assert insights["grouped_projection"] == "typed_insight_metadata"
    expected_groups = {
        "general_insights", "sphere_insights", "path_insights", "method_insights",
        "foundation_insights", "background_origin_insights", "item_equipment_insights",
        "special_insights", "unresolved_insights",
    }
    assert {group["id"] for group in insights["groups"]} == expected_groups
    assert {choice["insight_group"] for choice in insights["choices"]} <= expected_groups
    assert all(choice["insight_authority"]["preference_only"] for choice in insights["choices"])
