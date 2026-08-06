from __future__ import annotations

from copy import deepcopy

import pytest

from app.core import FoundryError, canonical_json
from app.api import create_app
from character_builder import CharacterBuilderService
from character_creation.current_fixture import exact_stage1_response
from non_sphere_authority import NonSphereAuthorityService
from path_method_authority import (
    CANONICAL_PATH_IDS,
    NO_COMPATIBLE_METHOD_MESSAGE,
    compatibility_envelope,
    method_granted_path_ids,
)
from planner_lab import CharacterPlannerLab
from stage1.service import Stage1ClipboardService


def _categories(options: dict) -> dict:
    return {row["slot_id"]: row for row in options["categories"]}


def _all_three_project(builder: CharacterBuilderService) -> dict:
    return builder.create_project(
        working_name="PLN1 Path Method authority regression",
        concept="A bounded all-three advancing-Path contract fixture.",
        target_cl=1,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={"path_choice": list(CANONICAL_PATH_IDS)},
    )


def test_path_authority_has_three_dormant_tracks_and_explicit_one_two_three_method_shapes(fresh_db):
    authority = NonSphereAuthorityService(fresh_db)
    state = authority.blank_state("pln1-level-zero")
    assert [row["path_id"] for row in state["paths"]] == list(CANONICAL_PATH_IDS)
    assert all(row["attainment"] == 0 and row["status"] == "DORMANT" for row in state["paths"])
    assert all(row["resource"]["active"] is False for row in state["paths"])

    methods = authority.method_catalog(initial_creation=True)["records"]
    grant_counts = {len(method_granted_path_ids(row)) for row in methods}
    assert {1, 2, 3} <= grant_counts
    for required in ([], list(CANONICAL_PATH_IDS[:1]), list(CANONICAL_PATH_IDS[:2]), list(CANONICAL_PATH_IDS)):
        envelope = compatibility_envelope(required, methods)
        assert envelope["all_path_ids"] == list(CANONICAL_PATH_IDS)
        assert envelope["required_advancing_path_ids"] == required
        assert envelope["level_zero_track_semantics"]["initial_attainment"] == 0
        assert envelope["level_zero_track_semantics"]["active_features"] is False
        assert envelope["level_zero_track_semantics"]["resource_progression"] is False
        assert all(method_id in envelope["method_granted_path_ids"] for method_id in envelope["compatible_method_ids"])


def test_builder_and_stage1_use_same_canonical_path_method_envelope(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    options = _categories(builder.options())
    path_category = options["path_choice"]
    assert path_category["label"] == "Advancing Path Requirements"
    assert path_category["kind"] == "multi"
    assert path_category["max"] == 3
    assert [row["choice_id"] for row in path_category["choices"]] == list(CANONICAL_PATH_IDS)
    assert path_category["authority_contract"]["level_zero_tracks"] == "all_three_present_dormant"
    assert path_category["selection_semantics"] == "owner_required_advancing_paths"

    method_rows = options["method_choice"]["choices"]
    assert {len(row["related_choice_ids"]) for row in method_rows} >= {1, 2, 3}
    created = _all_three_project(builder)
    prompt = Stage1ClipboardService(db).generate_prompt(created["project_id"])
    envelope = prompt["envelope"]
    slots = {row["slot_id"]: row for row in envelope["decision_slots"]}
    authority = envelope["path_method_authority"]
    assert slots["path_choice"]["label"] == "Advancing Path Requirements"
    assert slots["path_choice"]["max_selections"] == 3
    assert slots["path_choice"]["required_choice_ids"] == list(CANONICAL_PATH_IDS)
    assert authority["required_advancing_path_ids"] == list(CANONICAL_PATH_IDS)
    offered_methods = {row["choice_id"] for row in slots["method_choice"]["choices"]}
    assert offered_methods
    assert offered_methods <= set(authority["compatible_method_ids"])
    assert slots["method_choice"]["selection_semantics"] == "method_acquisition_and_primary_method_authority"


def test_stage1_deferred_and_typed_none_method_remain_valid_but_incompatible_selected_method_is_diagnosed(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    created = builder.create_project(
        working_name="PLN1 Stage 1 compatibility diagnostics",
        concept="Cross-slot authority regression.",
        target_cl=1,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={},
    )
    prompt = Stage1ClipboardService(db).generate_prompt(created["project_id"])
    envelope = prompt["envelope"]
    method_slot = next(row for row in envelope["decision_slots"] if row["slot_id"] == "method_choice")
    authority = NonSphereAuthorityService(db)
    single_path_method = next(
        row["method_id"]
        for row in authority.method_catalog(initial_creation=True)["records"]
        if len(method_granted_path_ids(row)) == 1
        and row["method_id"] in {choice["choice_id"] for choice in method_slot["choices"]}
    )
    all_three = list(CANONICAL_PATH_IDS)

    for method_state in ("deferred_with_reason", "explicit_none"):
        method_decision = {
            "slot_id": "method_choice",
            "state": method_state,
            "choice_ids": [],
            "reason_code": "deferred_future_decision" if method_state == "deferred_with_reason" else "legal_none",
            "reason": "Leave Method open for the server-owned compatibility review.",
        }
        diagnostics = Stage1ClipboardService._decision_diagnostics(
            {"decisions": [{"slot_id": "path_choice", "state": "selected", "choice_ids": all_three}, method_decision]},
            envelope,
        )
        assert not any(row["code"] == "METHOD_PATH_COMPATIBILITY_INVALID" for row in diagnostics)

    incompatible = Stage1ClipboardService._decision_diagnostics(
        {
            "decisions": [
                {"slot_id": "path_choice", "state": "selected", "choice_ids": all_three},
                {"slot_id": "method_choice", "state": "selected", "choice_ids": [single_path_method]},
            ]
        },
        envelope,
    )
    finding = next(row for row in incompatible if row["code"] == "METHOD_PATH_COMPATIBILITY_INVALID")
    assert finding["expected"]["required_path_ids"] == all_three
    assert finding["proposed"]["method_id"] == single_path_method
    assert finding["unsupported_path_ids"]


def test_no_compatible_method_fails_before_prompt_generation(catalog_environment, monkeypatch):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    created = _all_three_project(builder)
    only_body = {
        "method_id": "METHOD-ONLY-BODY",
        "explicit_ap_grants": [{"path_id": "BODY_REFINING", "grants_attainment_points": True}],
    }
    monkeypatch.setattr(
        "stage1.service.NonSphereAuthorityService.method_catalog",
        lambda self, *args, **kwargs: {"records": [deepcopy(only_body)]},
    )
    with pytest.raises(FoundryError) as exc:
        Stage1ClipboardService(db).generate_prompt(created["project_id"])
    assert exc.value.code == "NS1R_NO_COMPATIBLE_METHOD_FOR_REQUIRED_PATHS"
    assert exc.value.message == NO_COMPATIBLE_METHOD_MESSAGE
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM stage1_prompt_exchanges WHERE project_id=?", (created["project_id"],)).fetchone()[0] == 0


def test_corrected_stage1_proposal_is_accepted_as_blueprint_intent_and_planner_lab_covers_scenarios(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    created = _all_three_project(builder)
    stage1 = Stage1ClipboardService(db)
    prompt = stage1.generate_prompt(created["project_id"])
    response = exact_stage1_response(prompt)
    method_slot = next(row for row in prompt["envelope"]["decision_slots"] if row["slot_id"] == "method_choice")
    compatible_method = method_slot["choices"][0]["choice_id"]
    method_decision = next(row for row in response["response_payload"]["decisions"] if row["slot_id"] == "method_choice")
    method_decision.update({
        "state": "selected",
        "choice_ids": [compatible_method],
        "reason_code": None,
        "reason": None,
    })
    checked = stage1.validate_response(prompt["prompt_id"], canonical_json(response))
    assert checked["validation"]["valid"] is True
    committed = stage1.approve_and_commit(checked["attempt_id"], "owner")
    assert committed["commit"]["projection_status"] == "projected"

    lab = CharacterPlannerLab(db)
    reports = lab.scenario_reports()
    assert len(reports) == 7
    assert {len(row["chosen_by_owner"]["path_ids"]) for row in reports} == {0, 1, 2, 3}
    assert all(row["source_descriptions"]["method"]["compatible"] for row in reports)
    zero_lock = next(row for row in reports if row["scenario_id"] == "zero-owner-locks")
    assert zero_lock["chosen_by_owner"]["path_ids"] == []
    assert len(zero_lock["chosen_by_ai"]["path_ids"]) in {1, 2, 3}
    assert zero_lock["actual_advancing_path_ids"] == zero_lock["source_descriptions"]["method"]["explicit_granted_path_ids"]
    assert all(row["chosen_by_ai"]["selection_basis"].startswith("deterministic authority-order") for row in reports)
    corrected = lab.corrected_request_contract(list(CANONICAL_PATH_IDS))
    assert corrected["decision_slots"]["path_choice"]["max_selections"] == 3
    assert corrected["method_review"]["compatible"] is True
    assert corrected["path_method_authority"]["required_advancing_path_ids"] == list(CANONICAL_PATH_IDS)

    old_request = {
        "stage1_prompt": {
            "envelope": {
                "decision_slots": [{
                    "slot_id": "path_choice",
                    "max_selections": 1,
                    "required_choice_ids": list(CANONICAL_PATH_IDS),
                    "choices": [{"choice_id": path_id} for path_id in CANONICAL_PATH_IDS],
                }],
            }
        }
    }
    old_plan = {
        "stage1_response": {
            "response_payload": {
                "decisions": [{"slot_id": "path_choice", "choice_ids": list(CANONICAL_PATH_IDS)}],
            }
        },
        "stage2_proposal": {"catalog_priority_order": {"method_choice_id": "METHOD-007"}},
    }
    analysis = lab.analyze_jiang_request(old_request, old_plan)
    assert analysis["request_advertised_max_one"] is True
    assert analysis["mismatches"] == {"cardinality": True, "method_path": True, "offered_ids": False}
    assert analysis["classification"] == "metadata_conflict_and_method_path_mismatch"
    assert analysis["method_path_review"]["missing_path_ids"]


def test_primary_options_endpoint_exposes_the_same_path_contract(catalog_environment):
    app = create_app(catalog_environment["settings"])
    response = app.state.character_builder.options()
    categories = _categories(response)
    assert categories["path_choice"]["authority_contract"]["canonical_path_ids"] == list(CANONICAL_PATH_IDS)
    assert categories["path_choice"]["max"] == 3
