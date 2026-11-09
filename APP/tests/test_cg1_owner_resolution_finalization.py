from __future__ import annotations

from copy import deepcopy
import threading

import pytest

from app.core import FoundryError, canonical_json, sha256_bytes, sha256_json
from character_creation import CharacterCreationExecutionService
from character_creation.delegated_choice_authority import final_plan_sha256


class ReachedLiveExecution(Exception):
    pass


def _finalization_service_and_run(*, owner_resolutions=True):
    service = object.__new__(CharacterCreationExecutionService)
    service.owner_principal = "owner"
    service._finalize_lock = threading.Lock()
    service._require_owner_decisions_resolved = lambda run: None
    service._has_delegated_envelope = lambda run: False
    service._revision = lambda project_id: 0
    service._content_lock_hash = lambda project_id: "content-lock"

    request = {
        "project_revision": 0,
        "content_lock_hash": "content-lock",
    }
    request["request_sha256"] = service.request_payload_sha256(request)
    response_plan = {
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "selection_intent": {"by_slot": {"insight_priorities": []}},
    }
    response_text = canonical_json(response_plan)
    response_sha256 = sha256_bytes(response_text.encode("utf-8"))
    response = {
        "exact_response_text": response_text,
        "response_sha256": response_sha256,
    }
    run = {
        "run_id": "cg1.run.finalization-owner-overlay",
        "project_id": "p",
        "starting_revision": 0,
        "status": "READY_FOR_REVIEW",
        "quality": {"status": "CLEAN"},
        "request": request,
        "response": response,
        "validation": {},
        "final_plan": {},
    }
    if owner_resolutions:
        resolution = {
            "schema": "TianxiaFoundry.OwnerDecisionResolution.v1",
            "decision_id": "cg1.decision.finalization-owner-overlay",
            "field": "insight_priorities",
            "slot_id": "insight_priorities",
            "operation": "add_slot_value",
            "target_value": None,
            "value": "insight.body-as-cauldron",
            "binding": {
                "run_id": run["run_id"],
                "request_sha256": request["request_sha256"],
                "response_sha256": response_sha256,
                "content_lock_hash": request["content_lock_hash"],
                "blocker_sha256": "b" * 64,
            },
        }
        run["validation"]["owner_resolutions"] = [resolution]
        run["validation"]["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            [resolution],
            response_sha256=response_sha256,
            status="APPLIED",
        )
        run["validation"]["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256([resolution])

    reviewed_plan = service._apply_owner_resolutions(run, response_plan)
    run["validation"]["plan_sha256"] = sha256_json(reviewed_plan)
    run["final_plan"] = {
        "plan_sha256": sha256_json(reviewed_plan),
        "response_sha256": response_sha256,
        "request_sha256": request["request_sha256"],
        "immutable_after_validation": True,
    }
    run["final_plan"]["final_plan_sha256"] = final_plan_sha256(run["final_plan"])

    service.get = lambda run_id: run
    service._parse_plan = lambda text, **_kwargs: (deepcopy(response_plan), text.encode("utf-8"))

    def stop_before_live(*args, **kwargs):
        raise ReachedLiveExecution

    service._approved_candidate_for_finalization = stop_before_live
    return service, run, response_plan


def test_exact_applied_owner_batch_reconstructs_reviewed_plan_before_live_execution():
    service, run, _ = _finalization_service_and_run()

    with pytest.raises(ReachedLiveExecution):
        service.finalize(run["run_id"])


def test_finalize_still_rejects_raw_response_hash_mismatch_before_owner_overlay():
    service, run, _ = _finalization_service_and_run()
    before = deepcopy(run)
    run["response"]["response_sha256"] = "f" * 64

    with pytest.raises(FoundryError) as exc:
        service.finalize(run["run_id"])

    assert exc.value.code == "CG1_APPROVED_RESPONSE_DIVERGED"
    assert run == {**before, "response": {**before["response"], "response_sha256": "f" * 64}}


@pytest.mark.parametrize("state", ("PENDING", "LEGACY", "NON_LIST", "NON_DICT", "BINDING", "DUPLICATE", "EMPTY_APPLIED"))
def test_invalid_owner_batch_fails_before_live_execution_without_mutation(state):
    service, run, _ = _finalization_service_and_run()
    validation = run["validation"]
    original_rows = deepcopy(validation["owner_resolutions"])
    if state == "PENDING":
        validation["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            original_rows,
            response_sha256=run["response"]["response_sha256"],
            status="PENDING",
        )
    elif state == "LEGACY":
        validation.pop("owner_resolution_batch")
        validation.pop("owner_resolution_batch_sha256")
    elif state == "NON_LIST":
        validation["owner_resolutions"] = {"not": "a-list"}
    elif state == "NON_DICT":
        validation["owner_resolutions"] = [original_rows[0], "not-a-resolution"]
    elif state == "BINDING":
        validation["owner_resolutions"][0]["binding"]["request_sha256"] = "stale" * 13
    elif state == "DUPLICATE":
        conflicting = deepcopy(original_rows[0])
        conflicting["value"] = "insight.other-value"
        rows = [original_rows[0], conflicting]
        validation["owner_resolutions"] = rows
        validation["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            rows,
            response_sha256=run["response"]["response_sha256"],
            status="APPLIED",
        )
        validation["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256(rows)
    elif state == "EMPTY_APPLIED":
        validation["owner_resolutions"] = []
        validation["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            [],
            response_sha256=run["response"]["response_sha256"],
            status="APPLIED",
        )
        validation["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256([])
    before = deepcopy(run)

    with pytest.raises(FoundryError) as exc:
        service.finalize(run["run_id"])

    assert exc.value.code == "CG1_OWNER_DECISION_AUTHORIZATION_INVALID"
    assert run == before


def test_finalize_without_owner_resolutions_keeps_existing_hash_path():
    service, run, response_plan = _finalization_service_and_run(owner_resolutions=False)
    run["validation"]["plan_sha256"] = sha256_json(response_plan)
    run["final_plan"]["plan_sha256"] = sha256_json(response_plan)
    run["final_plan"]["final_plan_sha256"] = final_plan_sha256(run["final_plan"])

    with pytest.raises(ReachedLiveExecution):
        service.finalize(run["run_id"])
