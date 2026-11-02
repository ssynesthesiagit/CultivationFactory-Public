from copy import deepcopy
import json

import pytest

import character_creation.service as creation_service
from app.core import canonical_json, sha256_bytes, sha256_json
from character_creation.service import CharacterCreationExecutionService


def _order_repair_fixture(*, prior_skeleton=None):
    """Build a public-safe route diagnostic matching the live two-row shape."""
    request_sha256 = "r" * 64
    project_id = "project.synthetic-order-mirror"
    revision = 7
    route_a = {
        "route_id": "route.alpha",
        "sphere_id": "sphere.alpha",
        "free_talent_pair": {"sphere_id": "sphere.alpha", "talent_id": "FREE_ALPHA"},
        "ordinary_talent_ids_by_cl": {
            "1": "T1",
            "2": "T2",
            "3": "T3",
            "4": "T4",
        },
    }
    route_b = {
        "route_id": "route.beta",
        "sphere_id": "sphere.beta",
        "free_talent_pair": {"sphere_id": "sphere.beta", "talent_id": "FREE_BETA"},
        "ordinary_talent_ids_by_cl": {
            "1": "U1",
            "2": "U2",
            "3": "U3",
            "4": "U4",
        },
    }
    provider_payload = {
        "response_contract": {
            "expected_acquisition_counts": {
                "sphere_free_talent_pairs": 1,
                "ordinary_talent_ids": 4,
                "insight_occurrences": 0,
            },
            "presented_legal_first_cycle_pairs": [
                deepcopy(route_a["free_talent_pair"]),
                deepcopy(route_b["free_talent_pair"]),
            ],
        },
        "sphere_route_modules": [deepcopy(route_a), deepcopy(route_b)],
    }
    prior_ordinary = ["T1", "T3", "T2", "T4"]
    mirror = [] if prior_skeleton is None else deepcopy(prior_skeleton)
    prior_payload = {
        "schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
        "request_sha256": request_sha256,
        "selection_intent": {
            "by_slot": {
                "path_choice": ["path.qi"],
                "advancement_skeleton": mirror,
            },
        },
        "acquisition_intent": {
            "sphere_free_talent_pairs": [deepcopy(route_a["free_talent_pair"])],
            "ordinary_talent_ids": prior_ordinary,
            "insight_occurrences": [],
        },
        "bounded_choices": {"ability_scores": {"STR": 10}},
        "owner_descriptive_fields": {
            "identity": {"name": "Synthetic Order Test"},
            "concept": "A public-safe fixture.",
        },
        "unrelated_retained_field": {"must_remain": ["exact-provider-bytes"]},
    }
    prior_response = canonical_json(prior_payload)
    expected_map = {
        "1": ["T1", "U1"],
        "2": ["T2", "U2"],
        "3": ["T3", "U3"],
        "4": ["T4", "U4"],
    }
    derived = ["T1", "T2", "T3", "T4"]
    issues = []
    for index in (1, 2):
        # The validator emits both rows for a selected route mismatch: the
        # union projection and the selected-route singleton.  Keep both rows
        # in this fixture so the repair is tested against the live shape.
        issues.append({
            "field": f"acquisition_intent.ordinary_talent_ids.{index}",
            "reason": "NOT_PRESENTED_LEGAL_ORDINARY_TALENT",
            "effective_cl": index + 1,
            "proposed": prior_ordinary[index],
            "allowed_choice_ids": expected_map[str(index + 1)],
        })
        issues.append({
            "field": f"acquisition_intent.ordinary_talent_ids.{index}",
            "reason": "CROSS_ROUTE_MIXING",
            "effective_cl": index + 1,
            "proposed": prior_ordinary[index],
            "allowed_choice_ids": [derived[index]],
        })
    issues.append({
        "field": "selection_intent.by_slot.advancement_skeleton",
        "reason": "MUST_MIRROR_ORDINARY_TALENT_IDS",
        "proposed": mirror,
        # The persisted validator diagnostic from the measured run reports
        # the submitted ordinary array here.  The paired per-CL rows remain
        # the independent proof of the corrected order.
        "required_value": prior_ordinary,
    })
    diagnostic = {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
        "message": "The preferred response did not copy the frozen presented acquisition choices and counts.",
        "details": {
            "issues": issues,
            "expected_acquisition_counts": deepcopy(
                provider_payload["response_contract"]["expected_acquisition_counts"]
            ),
            "presented_legal_first_cycle_pairs": deepcopy(
                provider_payload["response_contract"]["presented_legal_first_cycle_pairs"]
            ),
            "presented_legal_ordinary_talent_ids_by_cl": expected_map,
        },
    }
    run = {
        "run_id": "cg1.run.synthetic-order-mirror",
        "project_id": project_id,
        "starting_revision": revision,
        "status": "NEEDS_REVIEW",
        "execution_mode": "STANDARD_API",
        "request": {
            "project_id": project_id,
            "project_revision": revision,
            "request_sha256": request_sha256,
        },
        "validation": {"last_submission_error": deepcopy(diagnostic)},
        "transport": {"provider_id": "local", "automatic_retries": 0},
        "attempt_history": [{
            "attempt_id": "cg1.attempt.synthetic-first",
            "response_text": prior_response,
            "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
        }],
        "response": {
            "exact_response_text": prior_response,
            "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
        },
    }
    return run, prior_response, diagnostic, provider_payload


@pytest.fixture
def order_fixture(monkeypatch):
    fixture = _order_repair_fixture()
    monkeypatch.setattr(
        creation_service,
        "_provider_payload",
        lambda *args, **kwargs: deepcopy(fixture[3]),
    )
    return fixture


def test_live_shaped_order_repair_derives_unique_order_and_exact_mirror(order_fixture):
    run, prior_response, diagnostic, _provider_payload = order_fixture

    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )

    assert target is not None
    assert target["target_kind"] == "ordinary_order_mirror_server_repair"
    assert target["ordinary_issue_indices"] == [1, 2]
    assert target["derived_ordinary_talent_ids"] == ["T1", "T2", "T3", "T4"]
    assert target["diagnostic_mirror_required_value"] == ["T1", "T3", "T2", "T4"]
    assert target["presented_legal_ordinary_talent_ids_by_cl"] == {
        "1": ["T1", "U1"],
        "2": ["T2", "U2"],
        "3": ["T3", "U3"],
        "4": ["T4", "U4"],
    }

    merged_text, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        "",
        diagnostic,
        run=run,
        repair_target=target,
    )
    merged = json.loads(merged_text)
    prior = json.loads(prior_response)
    assert merged["acquisition_intent"]["ordinary_talent_ids"] == ["T1", "T2", "T3", "T4"]
    assert merged["selection_intent"]["by_slot"]["advancement_skeleton"] == [
        "T1", "T2", "T3", "T4"
    ]
    prior["acquisition_intent"]["ordinary_talent_ids"] = ["T1", "T2", "T3", "T4"]
    prior["selection_intent"]["by_slot"]["advancement_skeleton"] = ["T1", "T2", "T3", "T4"]
    assert merged == prior
    assert evidence["provider_called"] is False
    assert evidence["raw_provider_completion_sha256"] is None
    assert evidence["provider_response_sha256"] is None
    assert run["attempt_history"][0]["response_text"] == prior_response
    assert run["attempt_history"][0]["response_sha256"] == sha256_bytes(
        prior_response.encode("utf-8")
    )
    assert evidence["applied_response_sha256"] == sha256_bytes(merged_text.encode("utf-8"))
    assert evidence["applied_response_sha256"] != sha256_bytes(prior_response.encode("utf-8"))


def test_retry_local_build_applies_order_repair_without_provider_or_completion(order_fixture):
    run, prior_response, diagnostic, _provider_payload = order_fixture
    applied = []
    service = object.__new__(CharacterCreationExecutionService)
    service.provider = object()
    service.get = lambda _run_id: deepcopy(run)
    service._provider_selected_id = lambda: "local"
    service._latest_attempt_id = lambda _run_id: "cg1.attempt.synthetic-first"
    service._recover_scoped_local_correction_context = lambda *args, **kwargs: (False, None)
    service._legacy_retry_bypass_context = lambda *args, **kwargs: None

    def apply_response(run_id, response_text, transport, **kwargs):
        applied.append((run_id, response_text, deepcopy(transport), deepcopy(kwargs)))
        return {"status": "READY_FOR_REVIEW", "response": {"exact_response_text": response_text}}

    service._apply_response = apply_response
    result = service.retry_local_build(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(applied) == 1
    assert applied[0][0] == run["run_id"]
    corrected = json.loads(applied[0][1])
    assert corrected["acquisition_intent"]["ordinary_talent_ids"] == ["T1", "T2", "T3", "T4"]
    assert corrected["selection_intent"]["by_slot"]["advancement_skeleton"] == [
        "T1", "T2", "T3", "T4"
    ]
    correction = applied[0][2]["local_correction"]
    assert correction["target_kind"] == "ordinary_order_mirror_server_repair"
    assert correction["provider_called"] is False
    assert correction["automatic_retries"] == 0
    assert correction["raw_provider_completion_sha256"] is None
    assert correction["provider_response_sha256"] is None
    assert run["response"]["exact_response_text"] == prior_response
    assert run["validation"]["last_submission_error"] == diagnostic


@pytest.mark.parametrize(
    "mutation",
    [
        "ambiguous_route",
        "duplicate_talent",
        "wrong_count",
        "unexpected_issue",
        "conflicting_skeleton",
        "stale_diagnostic",
        "wrong_mirror_required_value",
        "duplicate_reason",
    ],
)
def test_order_repair_rejects_ambiguous_or_stale_proofs(order_fixture, mutation):
    run, prior_response, diagnostic, provider_payload = order_fixture
    if mutation == "ambiguous_route":
        provider_payload["sphere_route_modules"].append(
            deepcopy(provider_payload["sphere_route_modules"][0])
        )
    elif mutation == "duplicate_talent":
        provider_payload["sphere_route_modules"][0]["ordinary_talent_ids_by_cl"]["4"] = "T3"
    elif mutation == "wrong_count":
        diagnostic["details"]["expected_acquisition_counts"]["ordinary_talent_ids"] = 3
        run["validation"]["last_submission_error"] = deepcopy(diagnostic)
    elif mutation == "unexpected_issue":
        diagnostic["details"]["issues"].append({
            "field": "acquisition_intent.insight_occurrences",
            "reason": "UNEXPECTED",
        })
        run["validation"]["last_submission_error"] = deepcopy(diagnostic)
    elif mutation == "conflicting_skeleton":
        payload = json.loads(prior_response)
        payload["selection_intent"]["by_slot"]["advancement_skeleton"] = ["T1"]
        prior_response = canonical_json(payload)
        diagnostic["details"]["issues"][-1]["proposed"] = ["T1"]
        run["validation"]["last_submission_error"] = deepcopy(diagnostic)
    elif mutation == "stale_diagnostic":
        diagnostic["message"] = "recomputed but not persisted"
    elif mutation == "wrong_mirror_required_value":
        diagnostic["details"]["issues"][-1]["required_value"] = ["T4", "T3", "T2", "T1"]
        run["validation"]["last_submission_error"] = deepcopy(diagnostic)
    elif mutation == "duplicate_reason":
        duplicate = deepcopy(diagnostic["details"]["issues"][1])
        diagnostic["details"]["issues"].append(duplicate)
        run["validation"]["last_submission_error"] = deepcopy(diagnostic)

    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is None or target.get("target_kind") != "ordinary_order_mirror_server_repair"
    target = CharacterCreationExecutionService._provider_ordinary_order_mirror_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is None


def test_order_repair_prompt_exposes_structural_cl_index_map_and_stays_below_cap():
    # Use the existing public-safe six-route/CL15 request fixture.  This
    # exercises the production payload builder rather than duplicating its
    # legal-choice source in a test-only authority.
    from test_compact_provider_prompt import _request_with_complete_routes

    request = _request_with_complete_routes()
    prompt = CharacterCreationExecutionService._provider_prompt({"request": request})
    payload = json.loads(prompt)
    position_map = payload["response_contract"]["ordinary_talent_position_map"]
    expected_route_ids = {
        route["route_id"]
        for route in payload["sphere_route_modules"]
        if isinstance(route, dict) and isinstance(route.get("route_id"), str)
    }

    assert set(position_map) == {str(cl) for cl in range(1, 16)}
    for effective_cl in range(1, 16):
        row = position_map[str(effective_cl)]
        assert row["effective_cl"] == effective_cl
        assert row["array_index"] == effective_cl - 1
        assert row["destination"] == "acquisition_intent.ordinary_talent_ids"
        assert row["mirror_destination"] == "selection_intent.by_slot.advancement_skeleton"
        assert set(row["route_bound_ids"]) == expected_route_ids
        assert all(isinstance(value, str) and value for value in row["route_bound_ids"].values())
    assert "ordinary_talent_position_map" in " ".join(payload["instructions"])
    assert len(prompt.encode("utf-8")) <= creation_service.PROVIDER_PROMPT_HARD_CAP_BYTES


def test_order_repair_no_route_map_references_existing_allowlist_once():
    from test_compact_provider_prompt import _request

    request = _request(target_cl=3)
    payload = json.loads(CharacterCreationExecutionService._provider_prompt({"request": request}))
    position_map = payload["response_contract"]["ordinary_talent_position_map"]
    for effective_cl in range(1, 4):
        row = position_map[str(effective_cl)]
        assert "allowed_ids" not in row
        assert row["allowed_ids_ref"] == (
            "response_contract.presented_legal_ordinary_talent_ids_by_cl."
            f"{effective_cl}"
        )
    assert len(canonical_json(payload).encode("utf-8")) <= creation_service.PROVIDER_PROMPT_HARD_CAP_BYTES


def test_order_repair_target_binding_hashes_are_exact(order_fixture):
    run, prior_response, diagnostic, _provider_payload = order_fixture
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert target["request_sha256"] == run["request"]["request_sha256"]
    assert target["prior_response_sha256"] == sha256_bytes(prior_response.encode("utf-8"))
    assert target["diagnostic_sha256"] == sha256_json(diagnostic)

    stale_run = deepcopy(run)
    stale_run["request"]["request_sha256"] = "s" * 64
    assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=stale_run,
        prior_response=prior_response,
    ) is None
