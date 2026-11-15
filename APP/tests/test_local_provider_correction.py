from copy import deepcopy
from contextlib import contextmanager
import json
import sqlite3
from types import SimpleNamespace

import pytest

import character_creation.service as character_creation_service
from app.core import canonical_json
from app.core import sha256_bytes
from app.core import FoundryError
from character_creation.service import (
    CharacterCreationExecutionService,
    PROVIDER_PROMPT_HARD_CAP_BYTES,
    _provider_payload,
    _provider_response_template,
)
from character_creation.response_materialization import RESPONSE_SCHEMA as DELEGATED_RESPONSE_SCHEMA


class _Provider:
    def __init__(self, receipts, *, provider_id=None):
        self.receipts = list(receipts)
        self.calls = []
        self.provider_id = provider_id or next(
            (
                item.get("provider_id")
                for item in self.receipts
                if isinstance(item, dict) and isinstance(item.get("provider_id"), str)
            ),
            None,
        )

    def status(self):
        return {"provider_id": self.provider_id}

    def complete_json(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        receipt = self.receipts.pop(0)
        if isinstance(receipt, BaseException):
            raise receipt
        return deepcopy(receipt)


def _receipt(response_text: str, *, provider_id: str) -> dict:
    return {
        "provider_id": provider_id,
        "model": "test-local-model",
        "purpose": "test-purpose",
        "response_text": response_text,
        "completion_sha256": sha256_bytes(response_text.encode("utf-8")),
    }


def _run() -> dict:
    return {
        "run_id": "cg1.run.local-correction",
        "project_id": "project.local-correction",
        "starting_revision": 7,
        "execution_mode": "STANDARD_API",
        "request": {
            "project_id": "project.local-correction",
            "project_revision": 7,
            "request_sha256": "r" * 64,
        },
    }


def _point_buy_case(scores: dict[str, int] | None = None) -> tuple[dict, dict]:
    run = _run()
    run["request"]["bounded_choice_contract"] = {
        "schema": "TianxiaFoundry.BoundedChoiceContract.v1",
        "fields": {
            "ability_scores": {
                "type": "point_buy_scores",
                "abilities": ["STR", "DEX", "CON", "INT", "WIS", "CHA"],
                "allowed_values": [8, 9, 10, 11, 12, 13, 14, 15],
                "budget": 27,
            },
        },
    }
    current = scores or {
        "STR": 15,
        "DEX": 14,
        "CON": 14,
        "INT": 10,
        "WIS": 12,
        "CHA": 10,
    }
    plan = {
        "schema": DELEGATED_RESPONSE_SCHEMA,
        "request_sha256": run["request"]["request_sha256"],
        "bounded_choices": {"ability_scores": deepcopy(current)},
    }
    return run, plan


def test_point_buy_budget_owner_decision_is_deterministic_and_fail_closed():
    run, plan = _point_buy_case()
    decision = CharacterCreationExecutionService._point_buy_budget_owner_decision(run, plan)

    assert decision is not None
    assert decision["field"] == "ability_scores"
    assert decision["operation"] == "set_field"
    assert decision["current_scores"] == {
        "STR": 15,
        "DEX": 14,
        "CON": 14,
        "INT": 10,
        "WIS": 12,
        "CHA": 10,
    }
    assert decision["computed_cost"] == 31
    assert decision["required_budget"] == 27
    expected = {
        "STR": 15,
        "DEX": 13,
        "CON": 13,
        "INT": 10,
        "WIS": 12,
        "CHA": 10,
    }
    assert decision["repaired_scores"] == expected
    assert decision["repaired_cost"] == 27
    competing = {
        "STR": 14,
        "DEX": 14,
        "CON": 13,
        "INT": 10,
        "WIS": 12,
        "CHA": 10,
    }
    cost_by_score = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
    assert sum(cost_by_score[value] for value in competing.values()) == 27
    expected_deltas = tuple(
        current - expected[ability]
        for ability, current in zip(("STR", "DEX", "CON", "INT", "WIS", "CHA"), (15, 14, 14, 10, 12, 10))
    )
    competing_deltas = tuple(
        current - competing[ability]
        for ability, current in zip(("STR", "DEX", "CON", "INT", "WIS", "CHA"), (15, 14, 14, 10, 12, 10))
    )
    assert (sum(expected_deltas), sum(value * value for value in expected_deltas), tuple(-expected[ability] for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA"))) < (
        sum(competing_deltas),
        sum(value * value for value in competing_deltas),
        tuple(-competing[ability] for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")),
    )
    assert len(decision["legal_choices"]) == 1
    assert decision["legal_choices"][0]["value"] == expected
    assert decision["algorithm"] == "bounded_point_buy_budget_normalization.v1"

    for scores in (
        {ability: 8 for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")},
        {"STR": 15, "DEX": 14, "CON": 13, "INT": 12, "WIS": 10, "CHA": 8},
        {"STR": 15, "DEX": 14, "CON": 14, "INT": 10, "WIS": 12, "CHA": True},
        {"STR": 15, "DEX": 14, "CON": 14, "INT": 10, "WIS": 12},
    ):
        _run_value, plan_value = _point_buy_case(scores)
        assert CharacterCreationExecutionService._point_buy_budget_owner_decision(
            _run_value,
            plan_value,
        ) is None

    for contract_schema in (None, "TianxiaFoundry.BoundedChoiceContract.v0"):
        schema_run, schema_plan = _point_buy_case()
        contract = schema_run["request"]["bounded_choice_contract"]
        if contract_schema is None:
            contract.pop("schema")
        else:
            contract["schema"] = contract_schema
        assert CharacterCreationExecutionService._point_buy_budget_owner_decision(
            schema_run,
            schema_plan,
        ) is None

    fixed_run, fixed_plan = _point_buy_case()
    fixed_run["request"]["stage1_prompt"] = {
        "envelope": {
            "user_locks": [{
                "field": "character_sheet.ability_point_buy",
                "value": {"fixed_scores": deepcopy(plan["bounded_choices"]["ability_scores"])},
            }],
        },
    }
    assert CharacterCreationExecutionService._point_buy_budget_owner_decision(
        fixed_run,
        fixed_plan,
    ) is None


def test_point_buy_budget_decision_is_raised_before_stage2_without_rewriting_response():
    run, plan = _point_buy_case()
    response_text = canonical_json(plan)
    response_sha256 = sha256_bytes(response_text.encode("utf-8"))
    service = object.__new__(CharacterCreationExecutionService)
    service._parse_plan = lambda _text, **kwargs: (deepcopy(plan), _text.encode("utf-8"))
    service._validate_complete_response_binding = lambda *args, **kwargs: None
    service._project = lambda _project_id, **kwargs: {}
    service._has_delegated_envelope = lambda _run: True
    service._manual_ai_correction_for_response = lambda *args, **kwargs: None
    service._validate_preferred_bounded_fields = lambda *args, **kwargs: None

    with pytest.raises(FoundryError) as caught:
        service._validate_and_compile(run, response_text)

    assert caught.value.code == "CG1_BOUNDED_DECISION_REQUIRED"
    assert caught.value.details["field"] == "ability_scores"
    assert caught.value.details["operation"] == "set_field"
    assert caught.value.details["computed_cost"] == 31
    assert caught.value.details["required_budget"] == 27
    assert caught.value.details["legal_choices"] == [{
        "value": {
            "STR": 15,
            "DEX": 13,
            "CON": 13,
            "INT": 10,
            "WIS": 12,
            "CHA": 10,
        },
        "label": "Factory-normalized legal 27-point-buy allocation.",
        "cost": 27,
    }]
    assert response_text == canonical_json(plan)
    assert sha256_bytes(response_text.encode("utf-8")) == response_sha256


def test_point_buy_owner_overlay_preserves_response_bytes_and_existing_milestones():
    run, plan = _point_buy_case()
    original_response = canonical_json(plan)
    original_hash = sha256_bytes(original_response.encode("utf-8"))
    decision = CharacterCreationExecutionService._point_buy_budget_owner_decision(run, plan)
    assert decision is not None
    normalized = decision["legal_choices"][0]["value"]
    run["validation"] = {
        "owner_resolutions": [
            {
                "operation": "set_milestone_choice",
                "value": {
                    "milestone_id": "CL4",
                    "kind": "asi",
                    "deltas": {"CON": 2},
                },
            },
            {
                "operation": "set_milestone_choice",
                "value": {
                    "milestone_id": "CL8",
                    "kind": "asi",
                    "deltas": {"CON": 2},
                },
            },
            {
                "field": "ability_scores",
                "operation": "set_field",
                "value": deepcopy(normalized),
            },
        ],
    }

    overlay = CharacterCreationExecutionService._apply_owner_resolutions(run, plan)

    assert overlay["bounded_choices"]["ability_scores"] == normalized
    assert overlay["bounded_choices"]["ability_score_changes_by_milestone_id"] == {
        "CL4": {"deltas": {"CON": 2}},
        "CL8": {"deltas": {"CON": 2}},
    }
    assert plan["bounded_choices"]["ability_scores"]["CON"] == 14
    assert run["validation"]["owner_resolutions"][0]["value"]["milestone_id"] == "CL4"
    assert original_response == canonical_json(plan)
    assert sha256_bytes(original_response.encode("utf-8")) == original_hash


def _blocked_result(
    run: dict,
    response_text: str,
    *,
    provider_id: str,
    automatic_retries: int = 0,
    diagnostic_code: str = "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
) -> dict:
    return {
        "status": "NEEDS_REVIEW",
        "request": deepcopy(run["request"]),
        "response": {
            "exact_response_text": response_text,
            "response_sha256": sha256_bytes(response_text.encode("utf-8")),
        },
        "validation": {
            "last_submission_error": {
                "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
                "code": diagnostic_code,
                "message": "The acquisition intent omitted a frozen required array.",
                "details": {"required": ["insight_occurrences"]},
            },
        },
        "transport": {
            "provider_id": provider_id,
            "automatic_retries": automatic_retries,
        },
        "final_plan": {},
        "final_revision": None,
        "commit": {},
        "canonical_intent_hash": None,
        "materialized_plan_sha256": None,
    }


def _explicit_review_run(
    *,
    provider_id: str = "local",
    execution_mode: str = "STANDARD_API",
    diagnostic_code: str = "CG1_METHOD_PATH_INCOMPATIBLE",
) -> dict:
    run = _run()
    response_text = '{"path":"retained"}'
    run.update({
        "status": "NEEDS_REVIEW",
        "execution_mode": execution_mode,
        "response": {
            "exact_response_text": response_text,
            "response_sha256": sha256_bytes(response_text.encode("utf-8")),
        },
        "validation": {
            "last_submission_error": {
                "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
                "code": diagnostic_code,
                "message": "The retained provider response failed a bounded Factory validator.",
                "details": {"slot_id": "method_choice"},
            },
        },
        "transport": {
            "provider_id": provider_id,
            "automatic_retries": 0,
            "provider_called": True,
        },
        "final_plan": {},
        "final_revision": None,
        "commit": {},
        "canonical_intent_hash": None,
        "materialized_plan_sha256": None,
        "attempt_history": [{"attempt_id": "cg1.attempt.first", "status": "BLOCKED"}],
    })
    return run


def _service(monkeypatch, run: dict, receipts: list[dict], results: list[dict], *, provider_id: str | None = None):
    # Keep this test at the provider orchestration boundary.  The real
    # _apply_response performs the isolated compile and append-only history;
    # these fakes let the test prove retry gating without a catalog/database.
    service = object.__new__(CharacterCreationExecutionService)
    service.provider = _Provider(receipts, provider_id=provider_id or "local")
    service.timing_logger = SimpleNamespace(info=lambda *args, **kwargs: None)
    service.get = lambda run_id: deepcopy(run)

    @contextmanager
    def connection():
        # Exercise the real immutable route guard with the retained request;
        # compilation/history remain isolated at _apply_response below.
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("CREATE TABLE character_creation_runs (run_id TEXT, request_json TEXT)")
            conn.execute("INSERT INTO character_creation_runs VALUES (?, ?)", (
                run["run_id"], canonical_json(run["request"]),
            ))
            yield conn
        finally:
            conn.close()

    service.db = SimpleNamespace(connection=connection)
    apply_calls = []

    def apply_response(run_id, response_text, transport, **kwargs):
        apply_calls.append({
            "run_id": run_id,
            "response_text": response_text,
            "transport": deepcopy(transport),
            "kwargs": deepcopy(kwargs),
        })
        return deepcopy(results[len(apply_calls) - 1])

    service._apply_response = apply_response
    service._latest_attempt_id = lambda run_id: "cg1.attempt.first"
    service._revision = lambda project_id: 7
    monkeypatch.setattr(
        CharacterCreationExecutionService,
        "_provider_prompt",
        staticmethod(lambda _run: '{"compact":true}'),
    )
    return service, apply_calls


def _retained_for_explicit_correction(run: dict, first: dict) -> dict:
    """The NEEDS_REVIEW run left by a first Local AI response that failed validation.

    Automatic provider correction was removed in e67e4e9e ("Provider correction
    is an explicit owner action"): _run_provider keeps the failed response and
    the owner may press "Ask Local AI to Fix This" (retry_local_ai_correction).
    Tests that used to exercise the automatic correction now drive that explicit
    action from the exact retained first result.
    """
    retained = _explicit_review_run(
        provider_id=(first.get("transport") or {}).get("provider_id") or "local",
        diagnostic_code=first["validation"]["last_submission_error"]["code"],
    )
    retained["request"] = deepcopy(run["request"])
    if "owner_descriptive_fields" in run:
        retained["owner_descriptive_fields"] = deepcopy(run["owner_descriptive_fields"])
    retained["response"] = deepcopy(first["response"])
    retained["validation"]["last_submission_error"] = deepcopy(first["validation"]["last_submission_error"])
    return retained


def _corrected_result(retained: dict, response_text: str) -> dict:
    return {
        **deepcopy(retained),
        "status": "READY_FOR_REVIEW",
        "response": {
            "exact_response_text": response_text,
            "response_sha256": sha256_bytes(response_text.encode("utf-8")),
        },
    }


def _contract_error(response_sha256: str, *, reason: str = "Provider completion content is empty or missing.") -> FoundryError:
    return FoundryError(
        "AI_PROVIDER_RESPONSE_CONTRACT_INVALID",
        "Detected Local AI returned a response that cannot enter the local JSON validator.",
        details={
            "response_sha256": response_sha256,
            "purpose": "character_creation_complete_plan",
            "reason": reason,
        },
    )


def _network_error() -> FoundryError:
    return FoundryError(
        "AI_PROVIDER_NETWORK_ERROR",
        "The API Provider request failed before a complete response was received.",
        details={"exception_type": "ReadTimeout"},
    )


def test_local_contract_failure_falls_back_after_one_provider_call(monkeypatch):
    run = _run()
    service, apply_calls = _service(monkeypatch, run, [_contract_error("e" * 64)], [])
    fallback_calls = []

    def fallback(run_value, error, **kwargs):
        fallback_calls.append((run_value, error, kwargs))
        return {
            "status": "WAITING_FOR_RESPONSE",
            "execution_mode": "MANUAL_CHAT",
            "transport": {
                "automatic_retries": kwargs.get("automatic_retries", 0),
                "timings": deepcopy(kwargs.get("timing_receipt") or {}),
            },
        }

    service._provider_fallback = fallback
    result = service._run_provider(run["run_id"])

    assert result["status"] == "WAITING_FOR_RESPONSE"
    assert len(service.provider.calls) == 1
    assert apply_calls == []
    assert len(fallback_calls) == 1
    _run_value, error, fallback_kwargs = fallback_calls[0]
    assert error.code == "AI_PROVIDER_RESPONSE_CONTRACT_INVALID"
    assert fallback_kwargs.get("automatic_retries", 0) == 0
    assert isinstance(
        fallback_kwargs["timing_receipt"]["phases_ms"]["factory_prompt_construction"],
        (int, float),
    )
    assert result["transport"]["automatic_retries"] == 0


def test_local_validator_failure_is_retained_for_explicit_correction_without_auto_retry(monkeypatch):
    run = _method_path_run()
    prior_response = _method_path_prior_response(run)
    first = {**run, **_method_path_first_result(run, prior_response)}
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(prior_response, provider_id="local")],
        [first],
    )
    service._provider_correction_prompt = lambda *_args, **_kwargs: pytest.fail(
        "_run_provider must not invoke the provider correction prompt"
    )

    result = service._run_provider(run["run_id"])

    assert result == first
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 1
    assert result["transport"]["automatic_retries"] == 0
    context = service._explicit_provider_correction_context(result)
    assert context is not None
    assert context["diagnostic"]["code"] == "CG1_METHOD_PATH_INCOMPATIBLE"
    assert service._action_availability(result)["retry_local_ai_correction"]["available"] is True


def test_local_invalid_response_is_retained_then_explicitly_corrected_once_with_provenance(monkeypatch):
    run = _run()
    original_request = deepcopy(run["request"])
    first_response = '{"bad":"first"}'
    corrected_response = '{"good":"corrected"}'
    first = {**run, **_blocked_result(run, first_response, provider_id="local")}
    service, apply_calls = _service(monkeypatch, run, [_receipt(first_response, provider_id="local")], [first])
    service._provider_correction_prompt = lambda *_args, **_kwargs: pytest.fail(
        "_run_provider must not invoke the provider correction prompt"
    )
    retained = service._run_provider(run["run_id"])
    assert retained == first
    assert len(service.provider.calls) == 1
    assert retained["transport"]["automatic_retries"] == 0
    assert service._action_availability(retained)["retry_local_ai_correction"]["available"] is True

    retained = _retained_for_explicit_correction(run, first)
    second = {
        **_corrected_result(retained, corrected_response),
        "attempt_history": [
            {"attempt_id": "cg1.attempt.first", "status": "BLOCKED"},
            {
                "attempt_id": "cg1.attempt.second",
                "status": "READY_FOR_REVIEW",
                "prior_attempt_id": "cg1.attempt.first",
            },
        ],
    }
    service, apply_calls = _service(
        monkeypatch,
        retained,
        [_receipt(corrected_response, provider_id="local")],
        [second],
    )
    canonical_mutations = []
    original_apply = service._apply_response

    def guarded_apply(run_id, response_text, transport, **kwargs):
        assert retained["request"] == original_request
        if response_text == corrected_response:
            canonical_mutations.append("successful-isolated-compile")
        assert not canonical_mutations or response_text == corrected_response
        return original_apply(run_id, response_text, transport, **kwargs)

    service._apply_response = guarded_apply
    result = service.retry_local_ai_correction(retained["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    assert service.provider.calls[0]["purpose"] == "character_creation_local_correction"
    correction = json.loads(service.provider.calls[0]["prompt_text"])["correction_contract"]
    assert correction["request_sha256"] == run["request"]["request_sha256"]
    assert correction["prior_response_text"] == first_response
    assert correction["prior_response_sha256"] == sha256_bytes(first_response.encode("utf-8"))
    assert correction["validator_diagnostic"]["code"] == "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID"
    assert apply_calls[0]["kwargs"]["prior_attempt_id"] == "cg1.attempt.first"
    assert apply_calls[0]["kwargs"]["action_type"] == "LOCAL_PROVIDER_CORRECTION"
    assert apply_calls[0]["transport"]["local_correction"]["explicit"] is True
    assert "target_scoped_merge" not in apply_calls[0]["transport"].get("local_correction", {})
    assert result["attempt_history"][1]["prior_attempt_id"] == "cg1.attempt.first"
    assert canonical_mutations == ["successful-isolated-compile"]
    assert retained["request"] == original_request


def test_path_required_gets_one_explicit_local_correction_and_protected_failures_do_not(monkeypatch):
    run = _run()
    first_response = '{"path":"missing"}'
    corrected_response = '{"path":"corrected"}'
    first = {**run, **_blocked_result(
        run,
        first_response,
        provider_id="local",
        diagnostic_code="CG1_DELEGATED_PATH_REQUIRED",
    )}
    automatic_service, automatic_apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(first_response, provider_id="local")],
        [first],
    )
    assert automatic_service._run_provider(run["run_id"]) == first
    assert len(automatic_service.provider.calls) == 1
    assert len(automatic_apply_calls) == 1

    retained = _retained_for_explicit_correction(run, first)
    service, apply_calls = _service(
        monkeypatch,
        retained,
        [_receipt(corrected_response, provider_id="local")],
        [_corrected_result(retained, corrected_response)],
    )
    result = service.retry_local_ai_correction(retained["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    assert apply_calls[0]["kwargs"]["action_type"] == "LOCAL_PROVIDER_CORRECTION"

    cloud_service, cloud_apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(first_response, provider_id="custom")],
        [
            _blocked_result(
                run,
                first_response,
                provider_id="custom",
                diagnostic_code="CG1_DELEGATED_PATH_REQUIRED",
            ),
        ],
        provider_id="custom",
    )
    cloud_result = cloud_service._run_provider(run["run_id"])
    assert cloud_result["status"] == "NEEDS_REVIEW"
    assert len(cloud_service.provider.calls) == 1
    assert len(cloud_apply_calls) == 1
    assert cloud_apply_calls[0]["kwargs"].get("action_type") is None

    for protected_code in (
        "AI_PROVIDER_NETWORK_ERROR",
        "AI_PROVIDER_ENDPOINT_BLOCKED",
        "CG1_COMPLETE_RESPONSE_REQUEST_HASH_MISMATCH",
        "CG1_STAGE2_INVALID",
    ):
        protected_result = _blocked_result(
            run,
            first_response,
            provider_id="local",
            diagnostic_code=protected_code,
        )
        assert service._provider_correction_eligible(run, protected_result, "local") is None


def test_provider_template_presents_an_exact_path_choice_id():
    template = _provider_response_template(
        request_sha256="a" * 64,
        descriptive_context={
            "identity.name": {"state": "delegated"},
            "concept": {"state": "delegated"},
        },
        presented_choices_by_slot={
            "path_choice": [{
                "id": "tianxia.path.qi_cultivation",
                "name": "Qi Cultivation",
                "cue": "Advance through Qi cultivation.",
            }],
        },
        ordinary_shortlist={},
        target_cl=1,
    )

    assert template["selection_intent"]["by_slot"]["path_choice"] == [
        "tianxia.path.qi_cultivation",
    ]
    assert template["selection_intent"]["by_slot"]["advancement_skeleton"] == []


def _ambiguous_path_diagnostic() -> dict:
    return {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_BOUNDED_DECISION_REQUIRED",
        "message": "More than one selected Path can advance at this CL; choose one exact Path progression route.",
        "details": {
            "cl": 1,
            "available_path_ids": [
                "body_refining",
                "qi_cultivation",
                "spirit_awakening",
            ],
        },
    }


def _singleton_path_diagnostic(path_id: str = "body_refining") -> dict:
    return {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_BOUNDED_DECISION_REQUIRED",
        "message": "Exactly one frozen Path can advance at this CL.",
        "details": {
            "cl": 1,
            "available_path_ids": [path_id],
        },
    }


def _add_singleton_path_authority(run: dict, *, path_id: str = "body_refining") -> dict:
    """Attach the minimum frozen Path authority required for auto-repair tests."""
    request = run.setdefault("request", {})
    envelope = request.setdefault("delegated_choice_envelope", {})
    frozen_target = envelope.setdefault("frozen_owner_target_cl", {"value": 1})
    if isinstance(frozen_target, dict):
        frozen_target.setdefault("value", 1)
    else:
        envelope["frozen_owner_target_cl"] = {"value": 1}
    allowed_by_slot = envelope.setdefault("allowed_choice_ids_by_slot", {})
    path_choices = allowed_by_slot.setdefault("path_choice", [])
    if not isinstance(path_choices, list):
        allowed_by_slot["path_choice"] = [path_id]
    elif path_id not in path_choices:
        path_choices.append(path_id)
    progression = envelope.setdefault("path_progression_choices", [])
    if not isinstance(progression, list):
        envelope["path_progression_choices"] = [{"cl": 1, "path_ids": [path_id]}]
    elif not any(isinstance(row, dict) and row.get("cl") == 1 for row in progression):
        progression.append({"cl": 1, "path_ids": [path_id]})
    return run


def _target_scoped_prior_response(run: dict) -> str:
    return canonical_json({
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "request_sha256": run["request"]["request_sha256"],
        "selection_intent": {
            "by_slot": {
                "method_choice": ["METHOD-001"],
                "path_choice": [
                    "body_refining",
                    "qi_cultivation",
                    "spirit_awakening",
                ],
                "background_choice": ["background-001"],
                "origin_insight_choice": ["insight-001"],
            },
        },
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": ["talent-001"],
            "insight_occurrences": [],
        },
        "bounded_choices": {
            "ability_scores": {"STR": 15, "DEX": 14},
            "path_progression_by_cl": {"2": "body_refining"},
        },
        "owner_descriptive_fields": {
            "identity": {"name": "Retained name"},
            "concept": "Retained concept",
        },
    })


def _target_scoped_first_result(run: dict, prior_response: str) -> dict:
    result = _blocked_result(
        run,
        prior_response,
        provider_id="local",
        diagnostic_code="CG1_BOUNDED_DECISION_REQUIRED",
    )
    result["validation"]["last_submission_error"] = _ambiguous_path_diagnostic()
    return result


def _method_path_run() -> dict:
    run = _run()
    run["request"]["delegated_choice_envelope"] = {
        "allowed_choice_ids_by_slot": {
            "method_choice": ["METHOD-001", "METHOD-081"],
            "path_choice": ["body_refining", "qi_cultivation", "spirit_awakening"],
        },
        "path_method_authority": {
            "method_granted_path_ids": {
                "METHOD-001": ["qi_cultivation"],
                "METHOD-081": ["body_refining", "qi_cultivation"],
            },
        },
        "selection_limits_by_slot": {
            "method_choice": {"final_min": 1, "final_max": 1},
            "path_choice": {"final_min": 1, "final_max": 3},
        },
        "path_progression_choices": [
            {"cl": 1, "path_ids": ["body_refining", "qi_cultivation"]},
        ],
    }
    return run


def _method_path_optional_method_run() -> dict:
    run = _method_path_run()
    run["request"]["delegated_choice_envelope"]["selection_limits_by_slot"]["method_choice"] = {
        "final_min": 0,
        "final_max": 1,
    }
    return run


def _method_path_prior_response(run: dict) -> str:
    payload = json.loads(_target_scoped_prior_response(run))
    payload["bounded_choices"]["path_progression_by_cl"] = {
        "1": "body_refining",
    }
    return canonical_json(payload)


def _method_path_diagnostic() -> dict:
    return {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_METHOD_PATH_INCOMPATIBLE",
        "message": "The selected Method does not explicitly grant AP for every final selected Path.",
        "details": {
            "method_id": "METHOD-001",
            "selected_path_ids": ["body_refining", "qi_cultivation", "spirit_awakening"],
            "missing_path_ids": ["body_refining", "spirit_awakening"],
        },
    }


def _ordinary_duplicate_run() -> dict:
    run = _run()
    ordinary_ids = [
        "TAL_FREE",
        "TAL_SAFE_A",
        "TAL_SAFE_B",
        "TAL_HIGH_CL",
        "TAL_PREREQ",
        "TAL_BLOCKED",
        "TAL_UNAVAILABLE",
        "TAL_OTHER_SPHERE",
    ]

    def source_row(choice_id: str, name: str, description: str) -> dict:
        return {
            "choice_id": choice_id,
            "content_type": "talent",
            "name": name,
            "description": description,
            "publication_state": "published",
        }

    def authority(choice_id: str, *, sphere_id: str = "sphere.scoundrel", minimum_cl: int = 1) -> dict:
        return {
            "authority_complete": True,
            "allowed_channels": ["level-choice"],
            "allowed_kinds": ["level_talent_acquisition"],
            "minimum_cl": minimum_cl,
            "sphere_id": sphere_id,
        }

    rows = {
        choice_id: source_row(choice_id, choice_id.replace("TAL_", ""), f"Short cue for {choice_id}.")
        for choice_id in ordinary_ids
    }
    authorities = {
        choice_id: authority(choice_id)
        for choice_id in ordinary_ids
    }
    authorities["TAL_HIGH_CL"]["minimum_cl"] = 3
    authorities["TAL_OTHER_SPHERE"]["sphere_id"] = "sphere.other"
    availability = {
        choice_id: {
            "availability": {
                "minimum_cl": 1,
                "realm_rules": {},
                "source_cl": {},
                "suppression": {},
            },
            "prerequisites": [],
            "incompatibilities": [],
        }
        for choice_id in ordinary_ids
    }
    availability["TAL_HIGH_CL"]["availability"]["minimum_cl"] = 3
    availability["TAL_PREREQ"]["prerequisites"] = [{"target_id": "TAL_NOT_PRESENT"}]
    envelope = {
        "frozen_owner_target_cl": {"value": 1},
        "ordinary_talent_count": 1,
        "allowed_choice_ids_by_slot": {"advancement_skeleton": ordinary_ids},
        "offered_choice_ids_by_slot": {"advancement_skeleton": ordinary_ids},
        "nonselectable_choice_ids_by_slot": {"advancement_skeleton": ["TAL_BLOCKED"]},
        "unavailable_or_rejected_choice_ids_by_slot": {"advancement_skeleton": ["TAL_UNAVAILABLE"]},
        "prerequisites_and_availability": {"advancement_skeleton": availability},
        "choices_by_slot": {"advancement_skeleton": rows},
        "typed_choice_authority_by_slot": {
            "advancement_skeleton": {"stage2_authority_by_choice": authorities},
        },
    }
    run["request"]["delegated_choice_envelope"] = envelope
    run["owner_descriptive_fields"] = {
        "resolved": {
            "identity": {"name": "Scratch"},
            "concept": "A streetwise survivor who trades secrets for food.",
        },
    }
    return run


def _ordinary_duplicate_required_two_run() -> dict:
    run = _ordinary_duplicate_run()
    envelope = run["request"]["delegated_choice_envelope"]
    rows = envelope["choices_by_slot"]["advancement_skeleton"]
    authorities = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    availability = envelope["prerequisites_and_availability"]["advancement_skeleton"]
    extra_ids = ["TAL_OUTGOING", "TAL_NEEDS_OUTGOING", "TAL_PAIR_A", "TAL_PAIR_B"]
    for choice_id in extra_ids:
        rows[choice_id] = {
            "choice_id": choice_id,
            "content_type": "talent",
            "name": choice_id,
            "description": f"Short cue for {choice_id}.",
            "publication_state": "published",
        }
        authorities[choice_id] = {
            "authority_complete": True,
            "allowed_channels": ["level-choice"],
            "allowed_kinds": ["level_talent_acquisition"],
            "minimum_cl": 1,
            "sphere_id": "sphere.scoundrel",
        }
        availability[choice_id] = {
            "availability": {
                "minimum_cl": 1,
                "realm_rules": {},
                "source_cl": {},
                "suppression": {},
            },
            "prerequisites": [],
            "incompatibilities": [],
        }
    availability["TAL_NEEDS_OUTGOING"]["prerequisites"] = [{"target_id": "TAL_OUTGOING"}]
    availability["TAL_PAIR_A"]["prerequisites"] = [{"target_id": "TAL_PAIR_B"}]
    availability["TAL_PAIR_B"]["prerequisites"] = [{"target_id": "TAL_PAIR_A"}]
    envelope["ordinary_talent_count"] = 2
    envelope["frozen_owner_target_cl"]["value"] = 2
    envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"] = list(
        envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"]
    ) + extra_ids
    envelope["offered_choice_ids_by_slot"]["advancement_skeleton"] = list(
        envelope["offered_choice_ids_by_slot"]["advancement_skeleton"]
    ) + extra_ids
    envelope["nonselectable_choice_ids_by_slot"]["advancement_skeleton"].append("TAL_OUTGOING")
    return run


def _ordinary_duplicate_oversized_run() -> dict:
    """A CL10 frozen plan with a compact model's 20-item duplicate shortlist."""
    run = _ordinary_duplicate_run()
    envelope = run["request"]["delegated_choice_envelope"]
    rows = envelope["choices_by_slot"]["advancement_skeleton"]
    authorities = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    availability = envelope["prerequisites_and_availability"]["advancement_skeleton"]
    synthetic_ids = [f"TAL_PACK_{index:02d}" for index in range(21)]
    for choice_id in synthetic_ids:
        rows[choice_id] = {
            "choice_id": choice_id,
            "id": choice_id,
            "content_type": "talent",
            "name": choice_id,
            "description": f"Short cue for {choice_id}.",
            "publication_state": "published",
        }
        authorities[choice_id] = {
            "authority_complete": True,
            "allowed_channels": ["level-choice"],
            "allowed_kinds": ["level_talent_acquisition"],
            "minimum_cl": 1,
            "sphere_id": "sphere.scoundrel",
        }
        availability[choice_id] = {
            "availability": {
                "minimum_cl": 1,
                "realm_rules": {},
                "source_cl": {},
                "suppression": {},
            },
            "prerequisites": [],
            "incompatibilities": [],
        }
    envelope["frozen_owner_target_cl"]["value"] = 10
    envelope["ordinary_talent_count"] = 10
    envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"] = list(
        envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"]
    ) + synthetic_ids
    envelope["offered_choice_ids_by_slot"]["advancement_skeleton"] = list(
        envelope["offered_choice_ids_by_slot"]["advancement_skeleton"]
    ) + synthetic_ids
    return run


def _ordinary_duplicate_oversized_ids() -> list[str]:
    return ["TAL_SAFE_A", "TAL_SAFE_B"] * 10


def _ordinary_duplicate_oversized_prior_response(run: dict) -> str:
    payload = json.loads(
        _ordinary_duplicate_prior_response(
            run,
            ordinary_ids=_ordinary_duplicate_oversized_ids(),
        )
    )
    payload["selection_intent"]["by_slot"]["advancement_skeleton"] = _ordinary_duplicate_oversized_ids()
    return canonical_json(payload)


def _ordinary_duplicate_oversized_diagnostic() -> dict:
    return {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_DELEGATED_DUPLICATE_CHOICE",
        "message": "The compact advancement shortlist repeated legal same-sphere anchors.",
        "details": {
            "choice_ids": _ordinary_duplicate_oversized_ids(),
            "slot_id": "advancement_skeleton",
        },
    }


def _ordinary_duplicate_repaired_response_context() -> tuple[dict, str, dict, dict]:
    run = _ordinary_duplicate_oversized_run()
    # Give this small unit fixture the same route-backed first-cycle pair
    # surface that a real request seals.  The ordinary repair itself still
    # draws only from the frozen advancement authority; this slot merely lets
    # the surrounding compact preflight validate the retained pair unchanged.
    envelope = run["request"]["delegated_choice_envelope"]
    sphere_id = "sphere.scoundrel"
    envelope["allowed_choice_ids_by_slot"]["sphere_priorities"] = [sphere_id]
    envelope["offered_choice_ids_by_slot"]["sphere_priorities"] = [sphere_id]
    envelope["nonselectable_choice_ids_by_slot"]["sphere_priorities"] = []
    envelope["unavailable_or_rejected_choice_ids_by_slot"]["sphere_priorities"] = []
    envelope["choices_by_slot"]["sphere_priorities"] = {
        sphere_id: {
            "choice_id": sphere_id,
            "id": sphere_id,
            "content_type": "sphere",
            "name": "Scoundrel Sphere",
            "description": "A synthetic sphere for this provider-free authority fixture.",
            "publication_state": "published",
        },
    }
    envelope["typed_choice_authority_by_slot"]["sphere_priorities"] = {
        "stage2_authority_by_choice": {
            sphere_id: {
                "authority_complete": True,
                "allowed_channels": ["sect-trial-cl1-sphere"],
                "allowed_kinds": ["sect_trial_sphere_acquisition"],
            },
        },
    }
    envelope["prerequisites_and_availability"]["sphere_priorities"] = {
        sphere_id: {
            "availability": {
                "minimum_cl": 1,
                "realm_rules": {},
                "source_cl": {},
                "suppression": {},
            },
            "prerequisites": [],
            "incompatibilities": [],
        },
    }
    envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]["TAL_FREE"]["allowed_channels"].append(
        "sect-trial-cl1-talent"
    )
    envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]["TAL_FREE"]["allowed_kinds"].append(
        "sect_trial_talent_acquisition"
    )
    run["request"]["bounded_choice_contract"] = {
        "schema": "TianxiaFoundry.BoundedChoiceContract.v1",
        "fields": {"ability_scores": "27-point-buy"},
    }
    prior_payload = json.loads(_ordinary_duplicate_oversized_prior_response(run))
    prior_payload["schema"] = DELEGATED_RESPONSE_SCHEMA
    prior_response = canonical_json(prior_payload)
    diagnostic = _ordinary_duplicate_oversized_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    merged, evidence = CharacterCreationExecutionService._merge_ordinary_duplicate_target_response(
        prior_response,
        canonical_json({"option_id": target["option_ids"][0]}),
        target,
    )
    marker = {
        **evidence,
        "target_kind": "ordinary_duplicate",
        "deterministic_server_repair": True,
        "provider_called": False,
        "prior_attempt_id": "cg1.attempt.provider",
        "prior_response_sha256": sha256_bytes(prior_response.encode("utf-8")),
        # The selector is synthetic in this fixture; the persisted marker for
        # a deterministic repair must never masquerade as provider evidence.
        "raw_provider_completion_sha256": None,
        "raw_provider_response_sha256": None,
        "provider_completion_sha256": None,
        "provider_response_sha256": None,
        "validator_diagnostic": deepcopy(diagnostic),
    }
    ordinary_attempt_id = "cg1.attempt.ordinary"
    ordinary_response = merged

    # Preserve the real retained-run shape: a later deterministic bounded
    # cleanup and a Retry Local Build both leave the expanded ordinary array
    # untouched.  The provenance verifier must therefore walk through them
    # instead of relying on only the latest transport marker.
    bounded_payload = json.loads(ordinary_response)
    bounded_payload["bounded_choices"]["legacy_empty_alias"] = {}
    bounded_with_alias = canonical_json(bounded_payload)
    bounded_diagnostic = {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_PREFERRED_RESPONSE_BOUNDED_FIELD_INVALID",
        "message": "The response supplied an unadvertised empty bounded field.",
        "details": {"fields": ["legacy_empty_alias"]},
    }
    bounded_target = CharacterCreationExecutionService._provider_bounded_field_cleanup_repair_target(
        bounded_diagnostic,
        run=run,
        prior_response=bounded_with_alias,
    )
    assert bounded_target is not None
    bounded_response, bounded_evidence = CharacterCreationExecutionService._merge_bounded_field_cleanup_target_response(
        bounded_with_alias,
        bounded_target,
        diagnostic=bounded_diagnostic,
        run=run,
    )
    bounded_marker = {
        **bounded_evidence,
        "target_kind": "bounded_field_cleanup",
        "deterministic_server_repair": True,
        "provider_called": False,
        "prior_attempt_id": ordinary_attempt_id,
        "prior_response_sha256": sha256_bytes(ordinary_response.encode("utf-8")),
        "raw_provider_completion_sha256": None,
        "raw_provider_response_sha256": None,
        "provider_completion_sha256": None,
        "provider_response_sha256": None,
        "validator_diagnostic": deepcopy(bounded_diagnostic),
    }
    request_sha256 = run["request"]["request_sha256"]

    def history_row(
        attempt_id: str,
        action_type: str,
        response: str,
        *,
        prior_attempt_id: str | None,
        transport: dict,
        ordinal: int,
    ) -> dict:
        return {
            "attempt_id": attempt_id,
            "run_id": run["run_id"],
            "project_id": run["project_id"],
            "ordinal": ordinal,
            "action_type": action_type,
            "status": "BLOCKED",
            "request_sha256": request_sha256,
            "response_sha256": sha256_bytes(response.encode("utf-8")),
            "response_text": response,
            "prior_attempt_id": prior_attempt_id,
            "binding": {
                "submitted_request_sha256": request_sha256,
                "active_request_sha256": request_sha256,
                "transport": transport,
            },
        }

    provider_attempt_id = "cg1.attempt.provider"
    retry_attempt_id = "cg1.attempt.retry"
    run["attempt_history"] = [
        history_row(
            provider_attempt_id,
            "IMPORT_RESPONSE",
            prior_response,
            prior_attempt_id=None,
            transport={"provider_called": True, "provider_id": "local"},
            ordinal=2,
        ),
        history_row(
            ordinary_attempt_id,
            "LOCAL_PROVIDER_CORRECTION",
            ordinary_response,
            prior_attempt_id=provider_attempt_id,
            transport={"provider_called": False, "automatic_retries": 0, "local_correction": marker},
            ordinal=3,
        ),
        history_row(
            "cg1.attempt.bounded",
            "LOCAL_PROVIDER_CORRECTION",
            bounded_response,
            prior_attempt_id=ordinary_attempt_id,
            transport={
                "provider_called": False,
                "automatic_retries": 0,
                "complete_request_sha256": request_sha256,
                "prior_attempt_id": ordinary_attempt_id,
                "local_correction": bounded_marker,
            },
            ordinal=4,
        ),
        history_row(
            retry_attempt_id,
            "RETRY_LOCAL_BUILD",
            bounded_response,
            prior_attempt_id="cg1.attempt.bounded",
            transport={
                "provider_called": False,
                "automatic_retries": 0,
                "transfer": "retry_local_build",
                "submitted_request_sha256": request_sha256,
                "prior_attempt_id": "cg1.attempt.bounded",
            },
            ordinal=5,
        ),
    ]
    # A deterministic local correction is not a new provider submission.  Its
    # outer binding is explicitly null while the active request and complete
    # request transport hashes remain exact.
    run["attempt_history"][2]["binding"]["submitted_request_sha256"] = None
    run["transport"] = {
        "provider_called": False,
        "automatic_retries": 0,
        "transfer": "retry_local_build",
        "submitted_request_sha256": request_sha256,
        "prior_attempt_id": "cg1.attempt.bounded",
    }
    run["response"] = {
        "exact_response_text": bounded_response,
        "response_sha256": sha256_bytes(bounded_response.encode("utf-8")),
    }
    return run, bounded_response, diagnostic, target


def _legacy_retry_suffix_context() -> tuple[dict, str]:
    """Add two immutable pre-fix Retry Local Build rows to the exact chain."""
    run, response_text, _diagnostic, _target = _ordinary_duplicate_repaired_response_context()
    base_retry = deepcopy(run["attempt_history"][-1])
    legacy_five = deepcopy(base_retry)
    legacy_five["attempt_id"] = "cg1.attempt.legacy-five"
    legacy_five["ordinal"] = 5
    legacy_five["prior_attempt_id"] = "cg1.attempt.bounded"
    legacy_five["binding"]["transport"]["prior_attempt_id"] = "cg1.attempt.bounded"
    legacy_five["binding"]["transport"].pop("automatic_retries")
    legacy_six = deepcopy(legacy_five)
    legacy_six["attempt_id"] = "cg1.attempt.legacy-six"
    legacy_six["ordinal"] = 6
    legacy_six["prior_attempt_id"] = legacy_five["attempt_id"]
    legacy_six["binding"]["transport"]["prior_attempt_id"] = legacy_five["attempt_id"]
    run["attempt_history"] = run["attempt_history"][:-1] + [legacy_five, legacy_six]
    run["transport"] = deepcopy(legacy_six["binding"]["transport"])
    run["validation"] = {
        "last_submission_error": {
            "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
            "code": "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
            "message": "The retained response remains blocked.",
            "details": {},
        },
    }
    run["status"] = "NEEDS_REVIEW"
    return run, response_text


def _legacy_retry_interior_descendant_context() -> tuple[dict, str]:
    """Build the retained live shape with descendants after a legacy bypass."""
    run, response_text = _legacy_retry_suffix_context()
    _add_singleton_path_authority(run)
    request_sha256 = run["request"]["request_sha256"]

    def history_row(
        attempt_id: str,
        action_type: str,
        response: str,
        *,
        prior_attempt_id: str,
        transport: dict,
        ordinal: int,
        submitted_request_sha256: str | None,
    ) -> dict:
        return {
            "attempt_id": attempt_id,
            "run_id": run["run_id"],
            "project_id": run["project_id"],
            "ordinal": ordinal,
            "action_type": action_type,
            "status": "BLOCKED",
            "request_sha256": request_sha256,
            "response_sha256": sha256_bytes(response.encode("utf-8")),
            "response_text": response,
            "prior_attempt_id": prior_attempt_id,
            "binding": {
                "submitted_request_sha256": submitted_request_sha256,
                "active_request_sha256": request_sha256,
                "transport": deepcopy(transport),
            },
        }

    bypass_attempt_id = "cg1.attempt.bypass"
    strict_retry_attempt_id = "cg1.attempt.strict-retry"
    bypass_transport = {
        "provider_called": False,
        "automatic_retries": 0,
        "transfer": "retry_local_build",
        "submitted_request_sha256": request_sha256,
        "prior_attempt_id": "cg1.attempt.bounded",
        "legacy_retry_bypass": {
            "schema": "TianxiaFoundry.LegacyRetryBypass.v1",
            "bypassed_attempt_ids": [
                "cg1.attempt.legacy-five",
                "cg1.attempt.legacy-six",
            ],
            "linked_prior_attempt_id": "cg1.attempt.bounded",
            "response_sha256": sha256_bytes(response_text.encode("utf-8")),
            "request_sha256": request_sha256,
            "reason": "missing_automatic_retries_only",
        },
    }
    run["attempt_history"].append(
        history_row(
            bypass_attempt_id,
            "RETRY_LOCAL_BUILD",
            response_text,
            prior_attempt_id="cg1.attempt.bounded",
            transport=bypass_transport,
            ordinal=7,
            submitted_request_sha256=request_sha256,
        )
    )

    strict_transport = {
        "provider_called": False,
        "automatic_retries": 0,
        "transfer": "retry_local_build",
        "submitted_request_sha256": request_sha256,
        "prior_attempt_id": bypass_attempt_id,
    }
    run["attempt_history"].append(
        history_row(
            strict_retry_attempt_id,
            "RETRY_LOCAL_BUILD",
            response_text,
            prior_attempt_id=bypass_attempt_id,
            transport=strict_transport,
            ordinal=8,
            submitted_request_sha256=request_sha256,
        )
    )

    singleton_diagnostic = _singleton_path_diagnostic()
    singleton_target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        singleton_diagnostic,
        run=run,
        prior_response=response_text,
    )
    assert singleton_target is not None
    singleton_response, singleton_evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        response_text,
        canonical_json({
            "bounded_choices": {
                "path_progression_by_cl": {"1": "body_refining"},
            },
        }),
        singleton_diagnostic,
        run=run,
        repair_target=singleton_target,
    )
    singleton_marker = {
        **singleton_evidence,
        "target_kind": "bounded_path_progression_singleton",
        "deterministic_server_repair": True,
        "provider_called": False,
        "deterministic_repair_algorithm": "bounded_path_progression_singleton",
        "deterministic_repair_version": "v1",
        "deterministic_repair_policy": "select_the_only_frozen_available_path_for_the_reported_cl",
        "prior_attempt_id": strict_retry_attempt_id,
        "prior_response_sha256": sha256_bytes(response_text.encode("utf-8")),
        "applied_response_sha256": sha256_bytes(singleton_response.encode("utf-8")),
        "request_sha256": request_sha256,
        "raw_provider_completion_sha256": None,
        "raw_provider_response_sha256": None,
        "provider_completion_sha256": None,
        "provider_response_sha256": None,
        "validator_diagnostic": deepcopy(singleton_diagnostic),
    }
    singleton_transport = {
        "provider_called": False,
        "automatic_retries": 0,
        "complete_request_sha256": request_sha256,
        "prior_attempt_id": strict_retry_attempt_id,
        "local_correction": singleton_marker,
    }
    run["attempt_history"].append(
        history_row(
            "cg1.attempt.singleton-correction",
            "LOCAL_PROVIDER_CORRECTION",
            singleton_response,
            prior_attempt_id=strict_retry_attempt_id,
            transport=singleton_transport,
            ordinal=9,
            submitted_request_sha256=None,
        )
    )
    run["transport"] = deepcopy(singleton_transport)
    run["response"] = {
        "exact_response_text": singleton_response,
        "response_sha256": sha256_bytes(singleton_response.encode("utf-8")),
    }
    return run, singleton_response


def _ordinary_duplicate_prior_response(run: dict, *, ordinary_ids: list[str] | None = None) -> str:
    return canonical_json({
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "request_sha256": run["request"]["request_sha256"],
        "selection_intent": {"by_slot": {"background_sphere_choice": ["background-sphere.scoundrel"]}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [{"sphere_id": "sphere.scoundrel", "talent_id": "TAL_FREE"}],
            "ordinary_talent_ids": ordinary_ids or ["TAL_FREE"],
            "insight_occurrences": [],
        },
        "bounded_choices": {"ability_scores": {"STR": 15}},
        "owner_descriptive_fields": {
            "identity": {"name": "Scratch"},
            "concept": "A streetwise survivor who trades secrets for food.",
        },
        "unrelated_retained_field": {"secret": "must remain byte-stable"},
    })


def _ordinary_duplicate_diagnostic(*, ordinary_ids: list[str] | None = None) -> dict:
    return {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_DELEGATED_DUPLICATE_CHOICE",
        "message": "A free Sphere Talent cannot be repeated as an ordinary Talent acquisition.",
        "details": {
            "free_talent_ids": ["TAL_FREE"],
            "ordinary_talent_ids": ordinary_ids or ["TAL_FREE"],
        },
    }


def _ordinary_duplicate_target(run: dict, prior_response: str) -> dict:
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        _ordinary_duplicate_diagnostic(),
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert target["target_kind"] == "ordinary_duplicate"
    return target


def _ordinary_duplicate_response(run: dict, prior_response: str, selected_id: str) -> str:
    target = _ordinary_duplicate_target(run, prior_response)
    mapping = {"ordinary_talent_ids": [selected_id]}
    option_id = next(
        option_id
        for option_id, option in target["options"].items()
        if option == mapping
    )
    return canonical_json({"option_id": option_id})


def _insight_unavailable_run() -> dict:
    run = _run()
    insight_ids = [
        "INS_BAD",
        "INS_SAFE",
        "INS_PATH",
        "INS_OTHER_SPHERE",
        "INS_HIGH",
        "INS_BLOCKED",
        "INS_UNAVAILABLE",
    ]

    def source_row(choice_id: str) -> dict:
        return {
            "choice_id": choice_id,
            "id": choice_id,
            "content_type": "cultivation_insight",
            "name": choice_id.replace("INS_", "").title(),
            "description": f"Short cue for {choice_id}.",
            "publication_state": "published",
        }

    def authority(choice_id: str, *, minimum_cl: int = 1) -> dict:
        return {
            "authority_complete": True,
            "allowed_channels": ["cultivation-insight"],
            "allowed_kinds": ["cultivation_insight_acquisition"],
            "minimum_cl": minimum_cl,
            "allowed_cls": [minimum_cl],
        }

    rows = {choice_id: source_row(choice_id) for choice_id in insight_ids}
    authorities = {choice_id: authority(choice_id) for choice_id in insight_ids}
    authorities["INS_BAD"] = authority("INS_BAD", minimum_cl=8)
    authorities["INS_HIGH"] = authority("INS_HIGH", minimum_cl=3)
    availability = {
        choice_id: {
            "availability": {
                "minimum_cl": 1,
                "realm_rules": {},
                "source_cl": {},
                "suppression": {},
            },
            "prerequisites": [],
            "incompatibilities": [],
        }
        for choice_id in insight_ids
    }
    availability["INS_BAD"]["availability"]["minimum_cl"] = 8
    availability["INS_HIGH"]["availability"]["minimum_cl"] = 3
    availability["INS_PATH"]["prerequisites"] = [{"target_id": "path.qi"}]
    availability["INS_OTHER_SPHERE"]["prerequisites"] = [{"target_id": "sphere.other"}]
    envelope = {
        "frozen_owner_target_cl": {"value": 1},
        "selection_limits_by_slot": {
            "insight_priorities": {"final_min": 0, "final_max": 8},
        },
        "allowed_choice_ids_by_slot": {"insight_priorities": insight_ids},
        "offered_choice_ids_by_slot": {"insight_priorities": insight_ids},
        "nonselectable_choice_ids_by_slot": {"insight_priorities": ["INS_BLOCKED"]},
        "unavailable_or_rejected_choice_ids_by_slot": {"insight_priorities": ["INS_UNAVAILABLE"]},
        "prerequisites_and_availability": {"insight_priorities": availability},
        "choices_by_slot": {"insight_priorities": rows},
        "typed_choice_authority_by_slot": {
            "insight_priorities": {"stage2_authority_by_choice": authorities},
        },
    }
    run["request"]["delegated_choice_envelope"] = envelope
    run["owner_descriptive_fields"] = {
        "resolved": {
            "identity": {"name": "Scratch"},
            "concept": "A patient toolmaker seeking forgotten techniques.",
        },
    }
    return run


def _insight_unavailable_prior_response(run: dict) -> str:
    return canonical_json({
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "request_sha256": run["request"]["request_sha256"],
        "selection_intent": {
            "by_slot": {
                "path_choice": ["path.qi"],
                "background_sphere_choice": ["sphere.scoundrel"],
                "insight_priorities": ["INS_BAD"],
            },
        },
        "acquisition_intent": {
            "sphere_free_talent_pairs": [
                {"sphere_id": "sphere.scoundrel", "talent_id": "TAL_FREE"},
            ],
            "ordinary_talent_ids": ["TAL_SAFE_TALENT"],
            "insight_occurrences": [],
        },
        "bounded_choices": {"ability_scores": {"STR": 15}},
        "owner_descriptive_fields": {
            "identity": {"name": "Scratch"},
            "concept": "A patient toolmaker seeking forgotten techniques.",
        },
        "unrelated_retained_field": {"secret": "must remain byte-stable"},
    })


def _insight_unavailable_diagnostic() -> dict:
    return {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_DELEGATED_CHOICE_UNAVAILABLE",
        "message": "The selected Insight is unavailable at this character level.",
        "details": {
            "choice_id": "INS_BAD",
            "minimum_cl": 8,
            "slot_id": "insight_priorities",
            "target_cl": 1,
        },
    }


def _insight_unavailable_target(run: dict, prior_response: str) -> dict:
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        _insight_unavailable_diagnostic(),
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert target["target_kind"] == "insight_unavailable"
    return target


def _insight_unavailable_response(run: dict, prior_response: str, option_index: int = 0) -> str:
    target = _insight_unavailable_target(run, prior_response)
    option_id = target["option_ids"][option_index]
    return canonical_json({"option_id": option_id})


def _free_talent_sphere_run() -> dict:
    run = _run()
    sphere_id = "sphere.scoundrel"
    talent_id = "TAL_FREE"

    def availability(minimum_cl: int = 1) -> dict:
        return {
            "minimum_cl": minimum_cl,
            "realm_rules": {},
            "source_cl": {},
            "suppression": {},
        }

    sphere_row = {
        "choice_id": sphere_id,
        "content_type": "sphere",
        "authority": "canonical",
        "publication_state": "published",
        "acquisition_channels": ["sphere-acquisition"],
        "availability": availability(),
        "prerequisites": [],
        "incompatibilities": [],
        "name": "Scoundrel",
    }
    talent_row = {
        "choice_id": talent_id,
        "content_type": "talent",
        "authority": "canonical",
        "publication_state": "published",
        "acquisition_channels": ["ordinary-sphere-talent"],
        "availability": availability(),
        "prerequisites": [],
        "incompatibilities": [],
        "parent_relationships": [{"record_id": sphere_id, "relation": "dependency"}],
        "name": "Free Talent",
    }
    envelope = {
        "frozen_owner_target_cl": {"value": 1},
        "selection_limits_by_slot": {
            "sphere_priorities": {
                "allow_none": True,
                "final_min": 0,
                "final_max": None,
                "owner_lock_min": 0,
                "owner_lock_max": None,
            },
        },
        "allowed_choice_ids_by_slot": {
            "sphere_priorities": [sphere_id],
            "advancement_skeleton": [talent_id],
        },
        "offered_choice_ids_by_slot": {
            "sphere_priorities": [sphere_id],
            "advancement_skeleton": [talent_id],
        },
        "nonselectable_choice_ids_by_slot": {
            "sphere_priorities": [],
            "advancement_skeleton": [],
        },
        "unavailable_or_rejected_choice_ids_by_slot": {
            "sphere_priorities": [],
            "advancement_skeleton": [],
        },
        "owner_locks": {"by_slot": {"sphere_priorities": []}},
        "choices_by_slot": {
            "sphere_priorities": {sphere_id: sphere_row},
            "advancement_skeleton": {talent_id: talent_row},
        },
        "prerequisites_and_availability": {
            "sphere_priorities": {
                sphere_id: {
                    "availability": availability(),
                    "prerequisites": [],
                    "incompatibilities": [],
                },
            },
        },
    }
    run["request"]["delegated_choice_envelope"] = envelope
    run["request"]["stage1_prompt"] = {
        "envelope": {
            "decision_slots": [
                {
                    "slot_id": "sphere_priorities",
                    "min_selections": 1,
                    "max_selections": None,
                },
            ],
        },
    }
    run["owner_descriptive_fields"] = {
        "resolved": {"identity": {"name": "Scratch"}, "concept": "A patient toolmaker."},
    }
    return run


def _free_talent_sphere_prior_response(run: dict) -> str:
    return canonical_json({
        "schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
        "request_sha256": run["request"]["request_sha256"],
        "selection_intent": {
            "by_slot": {
                "path_choice": ["path.qi"],
                "sphere_priorities": [],
                "insight_priorities": ["insight.safe"],
            },
        },
        "acquisition_intent": {
            "sphere_free_talent_pairs": [
                {"sphere_id": "sphere.scoundrel", "talent_id": "TAL_FREE"},
            ],
            "ordinary_talent_ids": ["TAL_ORDINARY"],
            "insight_occurrences": [],
        },
        "bounded_choices": {"ability_scores": {"STR": 15}},
        "owner_descriptive_fields": {
            "identity": {"name": "Scratch"},
            "concept": "A patient toolmaker.",
        },
        "unrelated_retained_field": {"must_remain": ["byte", {"stable": True}]},
    })


def _free_talent_sphere_diagnostic() -> dict:
    return {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_DELEGATED_FREE_TALENT_SPHERE_MISMATCH",
        "message": "Every accepted free Sphere Talent must belong to an accepted Sphere grant.",
        "details": {
            "owning_sphere_id": "sphere.scoundrel",
            "sphere_ids": [],
            "talent_id": "TAL_FREE",
        },
    }


def _free_talent_not_legal_run() -> dict:
    run = _free_talent_sphere_run()
    envelope = run["request"]["delegated_choice_envelope"]
    envelope["choices_by_slot"]["sphere_priorities"]["sphere.legal"] = {
        "choice_id": "sphere.legal",
        "content_type": "sphere",
        "authority": "canonical",
        "publication_state": "published",
        "acquisition_channels": ["ai-bootstrap-free-cl1-sphere"],
        "availability": {"minimum_cl": 1, "realm_rules": {}, "source_cl": {}, "suppression": {}},
        "prerequisites": [],
        "incompatibilities": [],
        "name": "Legal Sphere",
    }
    envelope["choices_by_slot"]["advancement_skeleton"]["TAL_LEGAL"] = {
        "choice_id": "TAL_LEGAL",
        "content_type": "talent",
        "authority": "canonical",
        "publication_state": "published",
        "acquisition_channels": ["ai-bootstrap-free-cl1-talent"],
        "availability": {"minimum_cl": 1, "realm_rules": {}, "source_cl": {}, "suppression": {}},
        "prerequisites": [],
        "incompatibilities": [],
        "parent_relationships": [{"record_id": "sphere.legal", "relation": "dependency"}],
        "name": "Legal Free Talent",
    }
    for slot_id, choice_id in (
        ("sphere_priorities", "sphere.legal"),
        ("advancement_skeleton", "TAL_LEGAL"),
    ):
        envelope["allowed_choice_ids_by_slot"][slot_id].append(choice_id)
        envelope["offered_choice_ids_by_slot"][slot_id].append(choice_id)
    typed = envelope["typed_choice_authority_by_slot"] = {
        "sphere_priorities": {"stage2_authority_by_choice": {
            "sphere.scoundrel": {
                "authority_complete": True,
                "allowed_kinds": ["background_sphere_acquisition"],
                "allowed_channels": ["background-grant"],
            },
            "sphere.legal": {
                "authority_complete": True,
                "allowed_kinds": ["ai_bootstrap_sphere_acquisition"],
                "allowed_channels": ["ai-bootstrap-free-cl1-sphere"],
            },
        }},
        "advancement_skeleton": {"stage2_authority_by_choice": {
            "TAL_FREE": {
                "authority_complete": True,
                "allowed_kinds": ["ai_bootstrap_talent_acquisition"],
                "allowed_channels": ["ai-bootstrap-free-cl1-talent"],
                "owning_canonical_sphere_id": "sphere.scoundrel",
                "minimum_cl": 1,
                "free_sphere_talent_eligible": True,
            },
            "TAL_LEGAL": {
                "authority_complete": True,
                "allowed_kinds": ["ai_bootstrap_talent_acquisition"],
                "allowed_channels": ["ai-bootstrap-free-cl1-talent"],
                "owning_canonical_sphere_id": "sphere.legal",
                "minimum_cl": 1,
                "free_sphere_talent_eligible": True,
            },
        }},
    }
    run["request"]["stage1_prompt"] = {
        "envelope": {
            "user_locks": [
                {"field": "character_sheet.generation_route", "value": "ai_bootstrap"},
            ],
        },
    }
    return run


def _free_talent_not_legal_diagnostic() -> dict:
    return {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_DELEGATED_FREE_TALENT_NOT_LEGAL",
        "message": "The selected Sphere/free-Talent pair is not legal for the frozen generation route.",
        "details": {
            "sphere_id": "sphere.scoundrel",
            "talent_id": "TAL_FREE",
            "route": "ai_bootstrap",
            "required_sphere_kind": "ai_bootstrap_sphere_acquisition",
            "required_talent_kind": "ai_bootstrap_talent_acquisition",
            "advertised_sphere_kinds": ["background_sphere_acquisition"],
            "advertised_talent_kinds": ["ai_bootstrap_talent_acquisition"],
        },
    }


def _add_route_legal_free_talent_candidate(
    run: dict,
    sphere_id: str,
    talent_id: str,
    *,
    sphere_name: str | None = None,
    talent_name: str | None = None,
) -> None:
    envelope = run["request"]["delegated_choice_envelope"]
    sphere_row = {
        "choice_id": sphere_id,
        "content_type": "sphere",
        "authority": "canonical",
        "publication_state": "published",
        "acquisition_channels": ["ai-bootstrap-free-cl1-sphere"],
        "availability": {"minimum_cl": 1, "realm_rules": {}, "source_cl": {}, "suppression": {}},
        "prerequisites": [],
        "incompatibilities": [],
        "name": sphere_name or sphere_id,
    }
    talent_row = {
        "choice_id": talent_id,
        "content_type": "talent",
        "authority": "canonical",
        "publication_state": "published",
        "acquisition_channels": ["ai-bootstrap-free-cl1-talent"],
        "availability": {"minimum_cl": 1, "realm_rules": {}, "source_cl": {}, "suppression": {}},
        "prerequisites": [],
        "incompatibilities": [],
        "parent_relationships": [{"record_id": sphere_id, "relation": "dependency"}],
        "name": talent_name or talent_id,
    }
    envelope["choices_by_slot"]["sphere_priorities"][sphere_id] = sphere_row
    envelope["choices_by_slot"]["advancement_skeleton"][talent_id] = talent_row
    for slot_id, choice_id in (
        ("sphere_priorities", sphere_id),
        ("advancement_skeleton", talent_id),
    ):
        if choice_id not in envelope["allowed_choice_ids_by_slot"][slot_id]:
            envelope["allowed_choice_ids_by_slot"][slot_id].append(choice_id)
        if choice_id not in envelope["offered_choice_ids_by_slot"][slot_id]:
            envelope["offered_choice_ids_by_slot"][slot_id].append(choice_id)
    typed = envelope.setdefault("typed_choice_authority_by_slot", {})
    typed.setdefault("sphere_priorities", {}).setdefault("stage2_authority_by_choice", {})[sphere_id] = {
        "authority_complete": True,
        "allowed_kinds": ["ai_bootstrap_sphere_acquisition"],
        "allowed_channels": ["ai-bootstrap-free-cl1-sphere"],
    }
    typed.setdefault("advancement_skeleton", {}).setdefault("stage2_authority_by_choice", {})[talent_id] = {
        "authority_complete": True,
        "allowed_kinds": ["ai_bootstrap_talent_acquisition"],
        "allowed_channels": ["ai-bootstrap-free-cl1-talent"],
        "owning_canonical_sphere_id": sphere_id,
        "minimum_cl": 1,
        "free_sphere_talent_eligible": True,
    }


def _method_path_first_result(run: dict, prior_response: str) -> dict:
    result = _blocked_result(
        run,
        prior_response,
        provider_id="local",
        diagnostic_code="CG1_METHOD_PATH_INCOMPATIBLE",
    )
    result["validation"]["last_submission_error"] = _method_path_diagnostic()
    return result


def _method_path_target(run: dict, prior_response: str) -> dict:
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        _method_path_diagnostic(),
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert target["target_kind"] == "method_path"
    return target


def test_method_path_optional_method_bounds_publish_actual_limits_and_one_method_repairs():
    run = _method_path_optional_method_run()
    prior_response = _method_path_prior_response(run)
    target = _method_path_target(run, prior_response)

    assert target["selection_limits"]["method_choice"] == {
        "final_min": 0,
        "final_max": 1,
    }
    assert target["repair_selection_count"] == {"method_choice": 1}
    assert target["response_schema"]["additionalProperties"] is False
    assert target["response_schema"]["properties"]["option_id"]["enum"] == target["option_ids"]
    assert target["options"]
    assert all(
        isinstance(option.get("method_choice"), list)
        and len(option["method_choice"]) == 1
        and option["method_choice"][0] in target["allowed_method_ids"]
        for option in target["options"].values()
    )
    assert all(
        set(option["path_choice"]).issubset(
            set(target["method_granted_path_ids"][option["method_choice"][0]])
        )
        for option in target["options"].values()
    )


def test_method_path_correction_without_retained_progression_offers_only_complete_single_path_options():
    run = _method_path_run()
    prior_payload = json.loads(_method_path_prior_response(run))
    prior_payload["bounded_choices"]["path_progression_by_cl"] = {}

    target = _method_path_target(run, canonical_json(prior_payload))

    assert target["existing_progression_keys"] == []
    assert target["options"]
    assert all(len(option["path_choice"]) == 1 for option in target["options"].values())
    assert all(option["path_progression_by_cl"] == {} for option in target["options"].values())


@pytest.mark.parametrize(
    "method_limits",
    [
        {"final_min": 0, "final_max": 2},
        {"final_min": -1, "final_max": 1},
        {"final_min": 0, "final_max": "1"},
    ],
)
def test_method_path_rejects_multi_method_or_malformed_frozen_bounds(method_limits):
    run = _method_path_run()
    run["request"]["delegated_choice_envelope"]["selection_limits_by_slot"]["method_choice"] = method_limits
    prior_response = _method_path_prior_response(run)
    assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
        _method_path_diagnostic(),
        run=run,
        prior_response=prior_response,
    ) is None


def _method_path_response(
    run: dict,
    prior_response: str,
    method_id: str,
    path_ids: list[str],
    progression: dict[str, str],
) -> str:
    target = _method_path_target(run, prior_response)
    mapping = {
        "method_choice": [method_id],
        "path_choice": path_ids,
        "path_progression_by_cl": progression,
    }
    option_id = next(
        (candidate_id for candidate_id, candidate in target["options"].items() if candidate == mapping),
        None,
    )
    assert option_id is not None
    return canonical_json({"option_id": option_id})


def test_method_path_explicit_correction_merges_only_authority_coherent_targets(monkeypatch):
    run = _method_path_run()
    prior_response = _method_path_prior_response(run)
    provider_response = _method_path_response(
        run,
        prior_response,
        "METHOD-081",
        ["body_refining", "qi_cultivation"],
        {"1": "qi_cultivation"},
    )
    retained = _retained_for_explicit_correction(run, _method_path_first_result(run, prior_response))
    service, apply_calls = _service(
        monkeypatch,
        retained,
        [_receipt(provider_response, provider_id="local")],
        [_corrected_result(retained, provider_response)],
    )

    result = service.retry_local_ai_correction(retained["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 1
    target = _method_path_target(run, prior_response)
    assert service.provider.calls[0]["response_schema"] == target["response_schema"]
    prior = json.loads(prior_response)
    applied = json.loads(apply_calls[0]["response_text"])
    assert applied["selection_intent"]["by_slot"]["method_choice"] == ["METHOD-081"]
    assert applied["selection_intent"]["by_slot"]["path_choice"] == [
        "body_refining",
        "qi_cultivation",
    ]
    assert applied["bounded_choices"]["path_progression_by_cl"] == {"1": "qi_cultivation"}
    assert applied["request_sha256"] == prior["request_sha256"]
    assert applied["acquisition_intent"] == prior["acquisition_intent"]
    assert applied["owner_descriptive_fields"] == prior["owner_descriptive_fields"]
    assert applied["bounded_choices"]["ability_scores"] == prior["bounded_choices"]["ability_scores"]
    correction = apply_calls[0]["transport"]["local_correction"]
    assert correction["target_kind"] == "method_path"
    assert correction["selected_method_id"] == "METHOD-081"
    assert correction["selected_path_ids"] == ["body_refining", "qi_cultivation"]
    assert correction["raw_provider_completion_sha256"] == sha256_bytes(provider_response.encode("utf-8"))
    assert correction["raw_provider_response_sha256"] == correction["raw_provider_completion_sha256"]
    assert correction["applied_response_sha256"] == sha256_bytes(apply_calls[0]["response_text"].encode("utf-8"))
    assert correction["raw_provider_completion_sha256"] != correction["applied_response_sha256"]


def test_method_path_automatic_run_computes_no_provider_correction_target(monkeypatch):
    # The explicit action reuses one target for prompt, schema and merge
    # (test_method_path_explicit_reuses_one_target_for_prompt_schema_and_merge).
    # The automatic run may only look for a provider-free repair: it builds no
    # correction prompt and merges nothing (e67e4e9e).
    run = _method_path_run()
    prior_response = _method_path_prior_response(run)
    expected_target = _method_path_target(run, prior_response)
    first = {**run, **_method_path_first_result(run, prior_response)}
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(prior_response, provider_id="local")],
        [first],
    )

    target_calls = []
    original_target = CharacterCreationExecutionService._provider_target_scoped_repair_target

    def target_wrapper(diagnostic, *, run=None, prior_response=None):
        target = original_target(diagnostic, run=run, prior_response=prior_response)
        target_calls.append(deepcopy(target))
        return target

    monkeypatch.setattr(
        CharacterCreationExecutionService,
        "_provider_target_scoped_repair_target",
        staticmethod(target_wrapper),
    )
    monkeypatch.setattr(
        CharacterCreationExecutionService,
        "_provider_correction_prompt",
        staticmethod(lambda *_args, **_kwargs: pytest.fail("no automatic correction prompt")),
    )
    monkeypatch.setattr(
        CharacterCreationExecutionService,
        "_merge_target_scoped_correction_response",
        staticmethod(lambda *_args, **_kwargs: pytest.fail("no automatic correction merge")),
    )

    result = service._run_provider(run["run_id"])

    assert result == first
    assert target_calls == [expected_target]
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 1
    assert service._explicit_provider_correction_context(result) is not None


def test_method_path_downstream_validation_failure_retains_target_merge_evidence(monkeypatch):
    run = _method_path_run()
    prior_response = _method_path_prior_response(run)
    provider_response = _method_path_response(
        run,
        prior_response,
        "METHOD-081",
        ["qi_cultivation"],
        {"1": "qi_cultivation"},
    )
    retained = _retained_for_explicit_correction(run, _method_path_first_result(run, prior_response))
    service, apply_calls = _service(
        monkeypatch,
        retained,
        [_receipt(provider_response, provider_id="local")],
        [],
    )
    original_apply = service._apply_response

    def fail_corrected_apply(run_id, response_text, transport, **kwargs):
        if kwargs.get("action_type") == "LOCAL_PROVIDER_CORRECTION":
            raise FoundryError(
                "CG1_METHOD_PATH_INCOMPATIBLE",
                "The corrected response still failed the frozen validator.",
            )
        return original_apply(run_id, response_text, transport, **kwargs)

    service._apply_response = fail_corrected_apply
    failures = []

    def record_failure(run_id, **kwargs):
        failures.append((run_id, kwargs))
        return deepcopy(retained)

    service._record_explicit_provider_correction_failure = record_failure
    result = service.retry_local_ai_correction(retained["run_id"])

    assert result["status"] == "NEEDS_REVIEW"
    assert result["response"]["exact_response_text"] == prior_response
    assert len(service.provider.calls) == 1
    assert apply_calls == []
    assert len(failures) == 1
    assert failures[0][1]["error"].code == "CG1_METHOD_PATH_INCOMPATIBLE"
    evidence = failures[0][1]["target_merge_evidence"]
    assert evidence["target_scoped_merge"] is True
    assert evidence["target_kind"] == "method_path"
    assert evidence["raw_provider_completion_sha256"] == sha256_bytes(provider_response.encode("utf-8"))
    assert evidence["applied_response_sha256"]


def test_method_path_explicit_correction_accepts_method_001_qi_and_preserves_unrelated_fields(monkeypatch):
    run = _explicit_review_run(diagnostic_code="CG1_METHOD_PATH_INCOMPATIBLE")
    run["request"] = _method_path_run()["request"]
    prior_response = _method_path_prior_response(run)
    run["response"] = {
        "exact_response_text": prior_response,
        "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
    }
    run["validation"]["last_submission_error"] = _method_path_diagnostic()
    provider_response = _method_path_response(
        run,
        prior_response,
        "METHOD-001",
        ["qi_cultivation"],
        {"1": "qi_cultivation"},
    )
    corrected = {
        **run,
        "status": "READY_FOR_REVIEW",
        "response": {
            "exact_response_text": provider_response,
            "response_sha256": sha256_bytes(provider_response.encode("utf-8")),
        },
    }
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(provider_response, provider_id="local")],
        [corrected],
    )

    result = service.retry_local_ai_correction(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    target = _method_path_target(run, prior_response)
    assert service.provider.calls[0]["response_schema"] == target["response_schema"]
    applied = json.loads(apply_calls[0]["response_text"])
    prior = json.loads(prior_response)
    assert applied["selection_intent"]["by_slot"]["method_choice"] == ["METHOD-001"]
    assert applied["selection_intent"]["by_slot"]["path_choice"] == ["qi_cultivation"]
    assert applied["acquisition_intent"] == prior["acquisition_intent"]
    assert applied["owner_descriptive_fields"] == prior["owner_descriptive_fields"]
    assert apply_calls[0]["transport"]["local_correction"]["target_kind"] == "method_path"


def test_method_path_explicit_reuses_one_target_for_prompt_schema_and_merge(monkeypatch):
    run = _explicit_review_run(diagnostic_code="CG1_METHOD_PATH_INCOMPATIBLE")
    run["request"] = _method_path_run()["request"]
    prior_response = _method_path_prior_response(run)
    run["response"] = {
        "exact_response_text": prior_response,
        "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
    }
    run["validation"]["last_submission_error"] = _method_path_diagnostic()
    expected_target = _method_path_target(run, prior_response)
    provider_response = _method_path_response(
        run,
        prior_response,
        "METHOD-001",
        ["qi_cultivation"],
        {"1": "qi_cultivation"},
    )
    corrected = {
        **run,
        "status": "READY_FOR_REVIEW",
        "response": {
            "exact_response_text": provider_response,
            "response_sha256": sha256_bytes(provider_response.encode("utf-8")),
        },
    }
    service, _apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(provider_response, provider_id="local")],
        [corrected],
    )

    target_calls = []
    original_target = CharacterCreationExecutionService._provider_target_scoped_repair_target

    def target_wrapper(diagnostic, *, run=None, prior_response=None):
        target = original_target(diagnostic, run=run, prior_response=prior_response)
        target_calls.append(deepcopy(target))
        return target

    prompt_targets = []
    original_prompt = CharacterCreationExecutionService._provider_correction_prompt

    def prompt_wrapper(run, prior_response, diagnostic, **kwargs):
        prompt_targets.append(deepcopy(kwargs.get("repair_target")))
        return original_prompt(run, prior_response, diagnostic, **kwargs)

    merge_targets = []
    original_merge = CharacterCreationExecutionService._merge_target_scoped_correction_response

    def merge_wrapper(prior_response, provider_response, diagnostic, **kwargs):
        merge_targets.append(deepcopy(kwargs.get("repair_target")))
        return original_merge(prior_response, provider_response, diagnostic, **kwargs)

    monkeypatch.setattr(
        CharacterCreationExecutionService,
        "_provider_target_scoped_repair_target",
        staticmethod(target_wrapper),
    )
    monkeypatch.setattr(
        CharacterCreationExecutionService,
        "_provider_correction_prompt",
        staticmethod(prompt_wrapper),
    )
    monkeypatch.setattr(
        CharacterCreationExecutionService,
        "_merge_target_scoped_correction_response",
        staticmethod(merge_wrapper),
    )

    result = service.retry_local_ai_correction(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert target_calls == [expected_target]
    assert prompt_targets == [expected_target]
    assert merge_targets == [expected_target]
    assert service.provider.calls[0]["response_schema"] == expected_target["response_schema"]


def test_method_path_target_rejections_fail_closed_without_mutation(monkeypatch):
    run = _method_path_run()
    prior_response = _method_path_prior_response(run)
    target = _method_path_target(run, prior_response)
    valid_option_id = next(iter(target["options"]))
    invalid_responses = [
        canonical_json({}),
        canonical_json({"option_id": "unknown-option"}),
        canonical_json({"option_id": [valid_option_id]}),
        canonical_json({"option_id": valid_option_id, "extra": True}),
    ]
    for provider_response in invalid_responses:
        retained = _retained_for_explicit_correction(run, _method_path_first_result(run, prior_response))
        service, apply_calls = _service(
            monkeypatch,
            retained,
            [_receipt(provider_response, provider_id="local")],
            [],
        )
        failures = []

        def record_failure(run_id, **kwargs):
            failures.append((run_id, kwargs))
            return deepcopy(retained)

        service._record_explicit_provider_correction_failure = record_failure
        result = service.retry_local_ai_correction(retained["run_id"])

        assert len(service.provider.calls) == 1
        assert apply_calls == []
        assert result["response"]["exact_response_text"] == prior_response
        assert len(failures) == 1
        assert failures[0][1]["error"].code == "CG1_LOCAL_CORRECTION_TARGET_INVALID"
        assert failures[0][1]["error"].details["raw_provider_completion_sha256"] == sha256_bytes(provider_response.encode("utf-8"))


def test_target_scoped_explicit_correction_merges_only_the_allowed_path(monkeypatch):
    run = _run()
    prior_response = _target_scoped_prior_response(run)
    provider_response = canonical_json({
        # The model dropped the method and unrelated slots.  The server must
        # use this only as the explicit Path target and retain the prior JSON.
        "bounded_choices": {
            "path_progression_by_cl": {"1": "qi_cultivation"},
        },
        "selection_intent": {"by_slot": {"method_choice": []}},
    })
    retained = _retained_for_explicit_correction(run, _target_scoped_first_result(run, prior_response))
    service, apply_calls = _service(
        monkeypatch,
        retained,
        [_receipt(provider_response, provider_id="local")],
        [_corrected_result(retained, provider_response)],
    )

    result = service.retry_local_ai_correction(retained["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    correction_schema = service.provider.calls[0]["response_schema"]
    progression_schema = correction_schema["properties"]["bounded_choices"]["properties"]["path_progression_by_cl"]
    assert progression_schema["required"] == ["1"]
    assert progression_schema["properties"]["1"]["enum"] == [
        "body_refining",
        "qi_cultivation",
        "spirit_awakening",
    ]
    applied_text = apply_calls[0]["response_text"]
    applied = json.loads(applied_text)
    prior = json.loads(prior_response)
    assert applied["request_sha256"] == prior["request_sha256"]
    assert applied["selection_intent"] == prior["selection_intent"]
    assert applied["acquisition_intent"] == prior["acquisition_intent"]
    assert applied["owner_descriptive_fields"] == prior["owner_descriptive_fields"]
    assert applied["bounded_choices"]["ability_scores"] == prior["bounded_choices"]["ability_scores"]
    assert applied["bounded_choices"]["path_progression_by_cl"] == {
        "1": "qi_cultivation",
        "2": "body_refining",
    }
    local_correction = apply_calls[0]["transport"]["local_correction"]
    assert local_correction["target_scoped_merge"] is True
    assert local_correction["selected_path_id"] == "qi_cultivation"
    assert local_correction["raw_provider_completion_sha256"] == sha256_bytes(provider_response.encode("utf-8"))
    assert local_correction["provider_completion_sha256"] == sha256_bytes(provider_response.encode("utf-8"))
    assert local_correction["applied_response_sha256"] == sha256_bytes(applied_text.encode("utf-8"))
    assert local_correction["raw_provider_completion_sha256"] != local_correction["applied_response_sha256"]
    assert apply_calls[0]["transport"]["complete_request_sha256"] == run["request"]["request_sha256"]


def test_singleton_path_progression_repair_is_provider_free_and_exact(monkeypatch):
    run = _add_singleton_path_authority(_run())
    prior_response = _target_scoped_prior_response(run)
    diagnostic = _singleton_path_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )

    assert target is not None
    assert target["target_kind"] == "bounded_path_progression_singleton"
    assert target["field"] == "bounded_choices.path_progression_by_cl"
    assert target["key"] == "1"
    assert target["available_path_ids"] == ["body_refining"]
    assert target["exact_selection_count"] == 1

    first = _target_scoped_first_result(run, prior_response)
    first["validation"]["last_submission_error"] = deepcopy(diagnostic)
    expected_response, _ = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        canonical_json({
            "bounded_choices": {
                "path_progression_by_cl": {"1": "body_refining"},
            },
        }),
        diagnostic,
        run=run,
        repair_target=target,
    )
    second = {
        **_blocked_result(
            run,
            expected_response,
            provider_id="local",
            diagnostic_code=diagnostic["code"],
        ),
        "status": "READY_FOR_REVIEW",
    }
    second["validation"]["last_submission_error"] = deepcopy(diagnostic)
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(prior_response, provider_id="local")],
        [first, second],
    )

    result = service._run_provider(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 2
    applied = json.loads(apply_calls[1]["response_text"])
    prior = json.loads(prior_response)
    assert applied["selection_intent"] == prior["selection_intent"]
    assert applied["acquisition_intent"] == prior["acquisition_intent"]
    assert applied["owner_descriptive_fields"] == prior["owner_descriptive_fields"]
    assert applied["bounded_choices"]["ability_scores"] == prior["bounded_choices"]["ability_scores"]
    assert applied["bounded_choices"]["path_progression_by_cl"] == {
        "1": "body_refining",
        "2": "body_refining",
    }
    correction = apply_calls[1]["transport"]["local_correction"]
    assert correction["target_kind"] == "bounded_path_progression_singleton"
    assert correction["deterministic_server_repair"] is True
    assert correction["provider_called"] is False
    assert apply_calls[1]["transport"]["automatic_retries"] == 0
    assert correction["selected_path_id"] == "body_refining"
    assert correction["deterministic_repair_algorithm"] == "bounded_path_progression_singleton"
    assert correction["deterministic_repair_version"] == "v1"
    assert correction["deterministic_repair_policy"] == (
        "select_the_only_frozen_available_path_for_the_reported_cl"
    )
    assert correction["raw_provider_completion_sha256"] is None
    assert correction["raw_provider_response_sha256"] is None
    assert correction["provider_completion_sha256"] is None
    assert correction["provider_response_sha256"] is None


def test_ambiguous_path_progression_does_not_auto_select_singleton(monkeypatch):
    run = _run()
    prior_response = _target_scoped_prior_response(run)
    diagnostic = _ambiguous_path_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert "target_kind" not in target

    first = _target_scoped_first_result(run, prior_response)
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(prior_response, provider_id="local")],
        [first],
    )
    result = service._run_provider(run["run_id"])

    assert result == first
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 1


@pytest.mark.parametrize(
    "mutation",
    ["target_kind", "field", "key", "available_path_ids", "response_schema"],
)
def test_singleton_path_progression_target_rejects_malformed_target(mutation):
    run = _add_singleton_path_authority(_run())
    prior_response = _target_scoped_prior_response(run)
    diagnostic = _singleton_path_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    if mutation == "target_kind":
        target["target_kind"] = []
    elif mutation == "field":
        target["field"] = "bounded_choices.path_progression_by_cl.invalid"
    elif mutation == "key":
        target["key"] = "2"
    elif mutation == "available_path_ids":
        target["available_path_ids"] = ["body_refining", "qi_cultivation"]
    else:
        target["response_schema"] = {"type": "object"}

    service = object.__new__(CharacterCreationExecutionService)
    with pytest.raises(FoundryError) as exc_info:
        service._apply_deterministic_server_repair(
            run["run_id"],
            run=run,
            provider_id="local",
            prior_attempt_id="cg1.attempt.first",
            prior_response=prior_response,
            diagnostic=diagnostic,
            repair_target=target,
            explicit=False,
        )
    assert exc_info.value.code == "CG1_LOCAL_CORRECTION_TARGET_INVALID"


def test_explicit_singleton_path_progression_repair_is_provider_free(monkeypatch):
    run = _add_singleton_path_authority(
        _explicit_review_run(diagnostic_code="CG1_BOUNDED_DECISION_REQUIRED")
    )
    prior_response = _target_scoped_prior_response(run)
    diagnostic = _singleton_path_diagnostic()
    run["response"] = {
        "exact_response_text": prior_response,
        "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
    }
    run["validation"]["last_submission_error"] = deepcopy(diagnostic)
    corrected = {
        **run,
        "status": "READY_FOR_REVIEW",
    }
    service, apply_calls = _service(
        monkeypatch,
        run,
        [],
        [corrected],
    )

    result = service.retry_local_ai_correction(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert service.provider.calls == []
    assert len(apply_calls) == 1
    applied = json.loads(apply_calls[0]["response_text"])
    assert applied["bounded_choices"]["path_progression_by_cl"] == {
        "1": "body_refining",
        "2": "body_refining",
    }
    correction = apply_calls[0]["transport"]["local_correction"]
    assert correction["explicit"] is True
    assert correction["target_kind"] == "bounded_path_progression_singleton"
    assert correction["deterministic_server_repair"] is True
    assert correction["provider_called"] is False
    assert correction["selected_path_id"] == "body_refining"
    assert apply_calls[0]["transport"]["automatic_retries"] == 0
    assert correction["raw_provider_completion_sha256"] is None
    assert correction["raw_provider_response_sha256"] is None
    assert correction["provider_completion_sha256"] is None
    assert correction["provider_response_sha256"] is None


def test_singleton_path_progression_rejects_boolean_diagnostic_cl_and_matching_key():
    run = _add_singleton_path_authority(_run())
    prior_response = _target_scoped_prior_response(run)
    valid_diagnostic = _singleton_path_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        valid_diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    malformed_diagnostic = deepcopy(valid_diagnostic)
    malformed_diagnostic["details"]["cl"] = True
    target["key"] = "True"

    service = object.__new__(CharacterCreationExecutionService)
    service.provider = _Provider([])
    applied = []

    def apply_response(*args, **kwargs):
        applied.append((args, kwargs))
        raise AssertionError("malformed singleton target must not be applied")

    service._apply_response = apply_response
    with pytest.raises(FoundryError) as exc_info:
        service._apply_deterministic_server_repair(
            run["run_id"],
            run=run,
            provider_id="local",
            prior_attempt_id="cg1.attempt.first",
            prior_response=prior_response,
            diagnostic=malformed_diagnostic,
            repair_target=target,
            explicit=False,
        )

    assert exc_info.value.code == "CG1_LOCAL_CORRECTION_TARGET_INVALID"
    assert applied == []
    assert service.provider.calls == []


def test_target_scoped_explicit_correction_preserves_prior_fields(monkeypatch):
    run = _explicit_review_run(diagnostic_code="CG1_BOUNDED_DECISION_REQUIRED")
    prior_response = _target_scoped_prior_response(run)
    run["response"] = {
        "exact_response_text": prior_response,
        "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
    }
    run["validation"]["last_submission_error"] = _ambiguous_path_diagnostic()
    provider_response = canonical_json({
        "bounded_choices": {"path_progression_by_cl": {"1": "spirit_awakening"}},
    })
    corrected = {
        **run,
        "status": "READY_FOR_REVIEW",
        "response": {
            "exact_response_text": provider_response,
            "response_sha256": sha256_bytes(provider_response.encode("utf-8")),
        },
    }
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(provider_response, provider_id="local")],
        [corrected],
    )

    result = service.retry_local_ai_correction(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    applied = json.loads(apply_calls[0]["response_text"])
    prior = json.loads(prior_response)
    assert applied["selection_intent"] == prior["selection_intent"]
    assert applied["acquisition_intent"] == prior["acquisition_intent"]
    assert applied["bounded_choices"]["path_progression_by_cl"] == {
        "1": "spirit_awakening",
        "2": "body_refining",
    }
    assert apply_calls[0]["transport"]["local_correction"]["target_scoped_merge"] is True


@pytest.mark.parametrize(
    "provider_response",
    [
        canonical_json({"bounded_choices": {"path_progression_by_cl": {}}}),
        canonical_json({"bounded_choices": {"path_progression_by_cl": {"1": "not-allowed"}}}),
        canonical_json({"bounded_choices": {"path_progression_by_cl": {"1": ["qi_cultivation", "body_refining"]}}}),
    ],
)
def test_target_scoped_invalid_choice_fails_closed_without_canonical_mutation(monkeypatch, provider_response):
    run = _run()
    prior_response = _target_scoped_prior_response(run)
    retained = _retained_for_explicit_correction(run, _target_scoped_first_result(run, prior_response))
    service, apply_calls = _service(
        monkeypatch,
        retained,
        [_receipt(provider_response, provider_id="local")],
        [],
    )
    failures = []

    def record_failure(run_id, **kwargs):
        failures.append((run_id, kwargs))
        return deepcopy(retained)

    service._record_explicit_provider_correction_failure = record_failure
    result = service.retry_local_ai_correction(retained["run_id"])

    assert len(service.provider.calls) == 1
    assert apply_calls == []
    assert result["response"]["exact_response_text"] == prior_response
    assert len(failures) == 1
    error = failures[0][1]["error"]
    assert error.code == "CG1_LOCAL_CORRECTION_TARGET_INVALID"
    assert error.details["raw_provider_completion_sha256"] == sha256_bytes(provider_response.encode("utf-8"))


def _correction_prompt_payload(
    monkeypatch,
    diagnostic: dict,
    *,
    run: dict | None = None,
    prior_response: str | None = None,
) -> dict:
    monkeypatch.setattr(
        CharacterCreationExecutionService,
        "_provider_prompt",
        staticmethod(lambda _run: canonical_json({"instructions": [], "authority": {}})),
    )
    prompt = CharacterCreationExecutionService._provider_correction_prompt(
        run or _run(),
        prior_response or '{"path_progression_by_cl":{}}',
        diagnostic,
    )
    return json.loads(prompt)


def test_correction_prompt_targets_exactly_one_listed_path_for_ambiguous_cl(monkeypatch):
    payload = _correction_prompt_payload(
        monkeypatch,
        {
            "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
            "code": "CG1_BOUNDED_DECISION_REQUIRED",
            "message": "More than one selected Path can advance at this CL; choose one exact Path progression route.",
            "details": {
                "cl": 1,
                "available_path_ids": [
                    "body_refining",
                    "qi_cultivation",
                    "spirit_awakening",
                ],
            },
        },
    )

    contract = payload["correction_contract"]
    target = contract["repair_target"]
    assert target["field"] == "bounded_choices.path_progression_by_cl"
    assert target["key"] == "1"
    assert target["exact_selection_count"] == 1
    assert target["available_path_ids"] == [
        "body_refining",
        "qi_cultivation",
        "spirit_awakening",
    ]
    progression_schema = target["response_schema"]["properties"]["bounded_choices"]["properties"]["path_progression_by_cl"]
    assert progression_schema["required"] == ["1"]
    assert progression_schema["properties"]["1"]["enum"] == target["available_path_ids"]
    assert "exactly one Path ID" in target["instruction"]
    assert 'path_progression_by_cl["1"]' in target["instruction"]
    assert contract["return_exactly_one_json_object"] is True
    assert contract["return_exactly_one_complete_response"] is False
    assert contract["replace_the_prior_response_in_full"] is False
    assert contract["do_not_return_a_patch_or_partial_object"] is False
    assert contract["target_scoped_merge"]["provider_output_may_omit_unrelated_fields"] is True
    assert any("one small JSON object" in row for row in payload["instructions"])
    assert not any("full replacement JSON object" in row for row in payload["instructions"])
    assert len(canonical_json(payload).encode("utf-8")) <= PROVIDER_PROMPT_HARD_CAP_BYTES


def test_generic_correction_prompt_has_no_path_inference_target_and_stays_bounded(monkeypatch):
    payload = _correction_prompt_payload(
        monkeypatch,
        {
            "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
            "code": "CG1_METHOD_PATH_INCOMPATIBLE",
            "message": "The selected Method is incompatible with the selected Path.",
            "details": {
                "cl": 1,
                "available_path_ids": ["body_refining", "qi_cultivation"],
            },
        },
    )

    contract = payload["correction_contract"]
    assert "repair_target" not in contract
    assert contract["return_exactly_one_complete_response"] is True
    assert contract["replace_the_prior_response_in_full"] is True
    assert contract["do_not_return_a_patch_or_partial_object"] is True
    assert any("full replacement JSON object" in row for row in payload["instructions"])
    assert len(canonical_json(payload).encode("utf-8")) <= PROVIDER_PROMPT_HARD_CAP_BYTES


def test_optional_method_run_uses_compact_method_path_prompt(monkeypatch):
    run = _method_path_optional_method_run()
    run["owner_descriptive_fields"] = {
        "resolved": {
            "identity": {"name": "Optional Method Character"},
            "concept": "A deliberate path repair test context.",
        },
    }
    run["request"]["delegated_choice_envelope"]["choices_by_slot"] = {
        "method_choice": [
            {"id": "METHOD-001", "display_name": "Method One", "semantic_cue": "Qi foundation."},
            {"id": "METHOD-081", "display_name": "Method Eighty-One", "semantic_cue": "Body and qi."},
        ],
        "path_choice": [
            {"id": "body_refining", "display_name": "Body Refining", "semantic_cue": "Harden the body."},
            {"id": "qi_cultivation", "display_name": "Qi Cultivation", "semantic_cue": "Shape inner qi."},
        ],
    }
    prior_response = _method_path_prior_response(run)
    prior_payload = json.loads(prior_response)
    prior_payload["distinctive_prior_response_token"] = "OPTIONAL_METHOD_PRIOR_SECRET"
    prior_response = canonical_json(prior_payload)
    payload = _correction_prompt_payload(
        monkeypatch,
        _method_path_diagnostic(),
        run=run,
        prior_response=prior_response,
    )

    target = payload["correction_contract"]["repair_target"]
    assert payload["prompt_kind"] == "method_path_option_selector"
    assert target["selection_limits"]["method_choice"] == {
        "final_min": 0,
        "final_max": 1,
    }
    assert target["repair_selection_count"] == {"method_choice": 1}
    assert "OPTIONAL_METHOD_PRIOR_SECRET" not in canonical_json(payload)
    assert len(canonical_json(payload).encode("utf-8")) < 20_000


def test_explicitly_unavailable_target_is_not_rederived(monkeypatch):
    run = _run()
    prior_response = '{"retained":true}'

    def fail_rederive(*_args, **_kwargs):
        raise AssertionError("an explicitly unavailable target must not be rederived")

    monkeypatch.setattr(
        CharacterCreationExecutionService,
        "_provider_target_scoped_repair_target",
        staticmethod(fail_rederive),
    )
    monkeypatch.setattr(
        CharacterCreationExecutionService,
        "_provider_prompt",
        staticmethod(lambda _run: canonical_json({"instructions": [], "authority": {}})),
    )

    prompt = CharacterCreationExecutionService._provider_correction_prompt(
        run,
        prior_response,
        _method_path_diagnostic(),
        repair_target=None,
    )
    payload = json.loads(prompt)
    assert "repair_target" not in payload["correction_contract"]
    merged, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        '{"replacement":true}',
        _method_path_diagnostic(),
        run=run,
        repair_target=None,
    )
    assert merged == '{"replacement":true}'
    assert evidence == {}


def test_method_path_correction_prompt_is_minimal_and_exposes_frozen_compatibility(monkeypatch):
    run = _method_path_run()
    run["owner_descriptive_fields"] = {
        "resolved": {
            "identity": {"name": "Ash of the First Dawn"},
            "concept": "A patient survivor rebuilding a broken cultivation path.",
        },
    }
    run["request"]["delegated_choice_envelope"]["choices_by_slot"] = {
        "method_choice": [
            {"id": "METHOD-001", "display_name": "Method One", "semantic_cue": "Qi foundation."},
            {"id": "METHOD-081", "display_name": "Method Eighty-One", "semantic_cue": "Body and qi."},
        ],
        "path_choice": [
            {"id": "body_refining", "display_name": "Body Refining", "semantic_cue": "Harden the body."},
            {"id": "qi_cultivation", "display_name": "Qi Cultivation", "semantic_cue": "Shape inner qi."},
            {"id": "spirit_awakening", "display_name": "Spirit Awakening", "semantic_cue": "Awaken the spirit."},
        ],
        "unrelated_large_slot": [{
            "id": "UNRELATED_LARGE_CHOICE_TOKEN",
            "display_name": "UNRELATED_LARGE_CHOICE_TOKEN",
            "semantic_cue": "UNRELATED_LARGE_CHOICE_TOKEN " * 1000,
        }],
    }
    prior_response = _method_path_prior_response(run)
    prior_response_payload = json.loads(prior_response)
    prior_response_payload["distinctive_prior_response_token"] = "PRIOR_METHOD_PATH_SECRET_TOKEN"
    prior_response = canonical_json(prior_response_payload)
    payload = _correction_prompt_payload(
        monkeypatch,
        _method_path_diagnostic(),
        run=run,
        prior_response=prior_response,
    )

    contract = payload["correction_contract"]
    target = contract["repair_target"]
    assert target["target_kind"] == "method_path"
    assert target["allowed_method_ids"] == ["METHOD-001", "METHOD-081"]
    assert target["allowed_path_ids"] == [
        "body_refining",
        "qi_cultivation",
        "spirit_awakening",
    ]
    assert target["method_granted_path_ids"] == {
        "METHOD-001": ["qi_cultivation"],
        "METHOD-081": ["body_refining", "qi_cultivation"],
    }
    assert target["existing_progression_keys"] == ["1"]
    assert len(target["options"]) == 5
    assert set(target["option_ids"]) == set(target["options"])
    assert target["response_schema"]["type"] == "object"
    assert target["response_schema"]["additionalProperties"] is False
    assert target["response_schema"]["required"] == ["option_id"]
    assert target["response_schema"]["properties"]["option_id"]["enum"] == target["option_ids"]
    assert payload["prompt_kind"] == "method_path_option_selector"
    assert payload["binding"]["request_sha256"] == run["request"]["request_sha256"]
    assert payload["binding"]["prior_response_sha256"] == sha256_bytes(prior_response.encode("utf-8"))
    assert payload["character_context"]["name"]["value"] == "Ash of the First Dawn"
    assert payload["character_context"]["concept"]["value"] == (
        "A patient survivor rebuilding a broken cultivation path."
    )
    assert set(payload["server_owned_option_context"]["choice_summaries"]) == {
        "method_choice",
        "path_choice",
    }
    prompt_text = canonical_json(payload)
    assert "PRIOR_METHOD_PATH_SECRET_TOKEN" not in prompt_text
    assert "UNRELATED_LARGE_CHOICE_TOKEN" not in prompt_text
    assert "prior_response_text" not in prompt_text
    assert len(prompt_text.encode("utf-8")) < 20_000
    expected_options = {
        canonical_json({
            "method_choice": ["METHOD-001"],
            "path_choice": ["qi_cultivation"],
            "path_progression_by_cl": {"1": "qi_cultivation"},
        }),
        canonical_json({
            "method_choice": ["METHOD-081"],
            "path_choice": ["body_refining"],
            "path_progression_by_cl": {"1": "body_refining"},
        }),
        canonical_json({
            "method_choice": ["METHOD-081"],
            "path_choice": ["qi_cultivation"],
            "path_progression_by_cl": {"1": "qi_cultivation"},
        }),
        canonical_json({
            "method_choice": ["METHOD-081"],
            "path_choice": ["body_refining", "qi_cultivation"],
            "path_progression_by_cl": {"1": "body_refining"},
        }),
        canonical_json({
            "method_choice": ["METHOD-081"],
            "path_choice": ["body_refining", "qi_cultivation"],
            "path_progression_by_cl": {"1": "qi_cultivation"},
        }),
    }
    assert {canonical_json(option) for option in target["options"].values()} == expected_options
    assert target == CharacterCreationExecutionService._provider_target_scoped_repair_target(
        _method_path_diagnostic(),
        run=run,
        prior_response=prior_response,
    )
    assert contract["minimal_response_shape"] == {"option_id": "one opaque ID from option_ids"}
    assert contract["return_exactly_one_complete_response"] is False
    assert contract["replace_the_prior_response_in_full"] is False
    assert any("coherent combination" in row for row in payload["instructions"])
    assert any("server-owned option_ids enum" in row for row in payload["instructions"])
    assert any("option_id" in row for row in payload["instructions"])
    assert not any("full replacement JSON object" in row for row in payload["instructions"])
    assert len(canonical_json(payload).encode("utf-8")) <= PROVIDER_PROMPT_HARD_CAP_BYTES


def test_ordinary_duplicate_target_filters_frozen_legal_candidates_and_preserves_count():
    run = _ordinary_duplicate_run()
    prior_response = _ordinary_duplicate_prior_response(run)
    target = _ordinary_duplicate_target(run, prior_response)

    assert target["required_count"] == 1
    assert target["candidate_ids"] == ["TAL_SAFE_A", "TAL_SAFE_B"]
    assert len(target["options"]) == 2
    assert target["response_schema"]["additionalProperties"] is False
    assert target["response_schema"]["required"] == ["option_id"]
    assert target["response_schema"]["properties"]["option_id"]["enum"] == target["option_ids"]
    assert all(
        option["ordinary_talent_ids"] in (["TAL_SAFE_A"], ["TAL_SAFE_B"])
        and len(option["ordinary_talent_ids"]) == target["required_count"]
        and len(set(option["ordinary_talent_ids"])) == target["required_count"]
        and "TAL_FREE" not in option["ordinary_talent_ids"]
        for option in target["options"].values()
    )
    assert target == _ordinary_duplicate_target(run, prior_response)


def test_ordinary_duplicate_required_two_uses_only_replacement_facts_and_joint_prerequisites():
    run = _ordinary_duplicate_required_two_run()
    ordinary_ids = ["TAL_FREE", "TAL_OUTGOING"]
    prior_response = _ordinary_duplicate_prior_response(run, ordinary_ids=ordinary_ids)
    diagnostic = _ordinary_duplicate_diagnostic(ordinary_ids=ordinary_ids)
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert target["required_count"] == 2
    option_values = [option["ordinary_talent_ids"] for option in target["options"].values()]
    assert all(len(value) == 2 and len(set(value)) == 2 for value in option_values)
    assert all("TAL_OUTGOING" not in value for value in option_values)
    assert all("TAL_NEEDS_OUTGOING" not in value for value in option_values)
    assert any(set(value) == {"TAL_PAIR_A", "TAL_PAIR_B"} for value in option_values)
    selectable_ids = {candidate_id for value in option_values for candidate_id in value}
    assert set(target["candidate_ids"]) == selectable_ids
    assert {row["id"] for row in target["candidate_summaries"]} == selectable_ids
    assert len(target["options"]) <= 24


def test_ordinary_duplicate_oversized_compact_shape_gets_one_provider_free_expansion(monkeypatch):
    run = _ordinary_duplicate_oversized_run()
    prior_response = _ordinary_duplicate_oversized_prior_response(run)
    diagnostic = _ordinary_duplicate_oversized_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert target["required_count"] == 10
    assert target["oversized_duplicate_shape"] is True
    assert target["preserved_ordinary_talent_ids"] == ["TAL_SAFE_A", "TAL_SAFE_B"]

    first = _blocked_result(
        run,
        prior_response,
        provider_id="local",
        diagnostic_code=diagnostic["code"],
    )
    first["validation"]["last_submission_error"] = deepcopy(diagnostic)
    second = {
        **_blocked_result(run, prior_response, provider_id="local", diagnostic_code=diagnostic["code"]),
        "status": "READY_FOR_REVIEW",
    }
    second["validation"]["last_submission_error"] = deepcopy(diagnostic)
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(prior_response, provider_id="local")],
        [first, second],
    )

    result = service._run_provider(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 2
    correction = apply_calls[1]["transport"]["local_correction"]
    assert correction["target_kind"] == "ordinary_duplicate"
    assert correction["deterministic_server_repair"] is True
    assert correction["provider_called"] is False
    assert correction["deterministic_repair_version"] == "v1"
    assert correction["selected_option_id"] == target["option_ids"][0]
    assert correction["preserved_ordinary_talent_ids"] == ["TAL_SAFE_A", "TAL_SAFE_B"]
    assert correction["raw_provider_completion_sha256"] is None
    expanded_ids = correction["full_expanded_ordinary_talent_ids"]
    assert len(expanded_ids) == 10
    assert len(set(expanded_ids)) == 10
    applied = json.loads(apply_calls[1]["response_text"])
    assert applied["acquisition_intent"]["ordinary_talent_ids"] == expanded_ids
    assert applied["selection_intent"]["by_slot"]["advancement_skeleton"] == expanded_ids


def test_ordinary_duplicate_oversized_expansion_respects_each_effective_cl(monkeypatch):
    run = _ordinary_duplicate_oversized_run()
    envelope = run["request"]["delegated_choice_envelope"]
    authorities = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    availability = envelope["prerequisites_and_availability"]["advancement_skeleton"]
    # This Talent is legal for the frozen CL10 target but only from CL8.  A
    # correction option must therefore place it at CL8-10, never at an early
    # array position selected by lexicographic/circular ordering.
    late_id = "TAL_PACK_00"
    authorities[late_id]["minimum_cl"] = 8
    availability[late_id]["availability"]["minimum_cl"] = 8
    prior_response = _ordinary_duplicate_oversized_prior_response(run)
    diagnostic = _ordinary_duplicate_oversized_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert late_id in target["candidate_ids"]
    assert any(late_id in option["ordinary_talent_ids"] for option in target["options"].values())
    minimum_by_id = {
        choice_id: authority["minimum_cl"]
        for choice_id, authority in authorities.items()
        if isinstance(authority, dict) and type(authority.get("minimum_cl")) is int
    }
    for option in target["options"].values():
        selected = option["ordinary_talent_ids"]
        assert len(selected) == 10
        assert len(set(selected)) == 10
        assert all(minimum_by_id[choice_id] <= effective_cl for effective_cl, choice_id in enumerate(selected, 1))

    first = _blocked_result(
        run,
        prior_response,
        provider_id="local",
        diagnostic_code=diagnostic["code"],
    )
    first["validation"]["last_submission_error"] = deepcopy(diagnostic)
    second = {
        **_blocked_result(run, prior_response, provider_id="local", diagnostic_code=diagnostic["code"]),
        "status": "READY_FOR_REVIEW",
    }
    second["validation"]["last_submission_error"] = deepcopy(diagnostic)
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(prior_response, provider_id="local")],
        [first, second],
    )

    result = service._run_provider(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 2
    expanded_ids = json.loads(apply_calls[1]["response_text"])["acquisition_intent"]["ordinary_talent_ids"]
    assert late_id in expanded_ids
    assert all(minimum_by_id[choice_id] <= effective_cl for effective_cl, choice_id in enumerate(expanded_ids, 1))
    assert apply_calls[1]["transport"]["automatic_retries"] == 0
    assert apply_calls[1]["transport"]["local_correction"]["provider_called"] is False


def test_ordinary_duplicate_oversized_shape_rejects_insufficient_or_incomplete_authority():
    diagnostic = _ordinary_duplicate_oversized_diagnostic()
    for mutation in ("missing", "incomplete"):
        run = _ordinary_duplicate_oversized_run()
        envelope = run["request"]["delegated_choice_envelope"]
        if mutation == "missing":
            envelope["choices_by_slot"]["advancement_skeleton"].pop("TAL_SAFE_B")
        else:
            envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]["TAL_SAFE_B"]["authority_complete"] = False
        prior_response = _ordinary_duplicate_oversized_prior_response(run)
        assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
            diagnostic,
            run=run,
            prior_response=prior_response,
        ) is None


def test_compact_preflight_accepts_only_proof_bound_ordinary_expansion():
    run, response_text, _diagnostic, target = _ordinary_duplicate_repaired_response_context()
    plan = json.loads(response_text)
    compact_contract = _provider_payload(run, cue_limit=0, display_limit=0)["response_contract"]
    compact_ids = set(compact_contract["presented_legal_ordinary_talent_ids_by_cl"]["1"])
    expanded_ids = plan["acquisition_intent"]["ordinary_talent_ids"]
    assert any(choice_id not in compact_ids for choice_id in expanded_ids)

    CharacterCreationExecutionService._validate_preferred_bounded_fields(
        run,
        plan,
        response_text=response_text,
    )

    strict_run = deepcopy(run)
    strict_run["transport"] = {"provider_called": False, "automatic_retries": 0}
    strict_run["attempt_history"] = []
    with pytest.raises(FoundryError) as exc_info:
        CharacterCreationExecutionService._validate_preferred_bounded_fields(
            strict_run,
            plan,
            response_text=response_text,
        )
    assert exc_info.value.code == "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID"
    assert any(
        issue.get("reason") == "NOT_PRESENTED_LEGAL_ORDINARY_TALENT"
        for issue in exc_info.value.details["issues"]
    )
    assert target["options"][target["option_ids"][0]]["ordinary_talent_ids"] == expanded_ids


def test_validated_ordinary_expansion_preserves_noncanonical_provider_bytes():
    run, response_text, _diagnostic, _target = _ordinary_duplicate_repaired_response_context()
    plan = json.loads(response_text)
    provider_row = run["attempt_history"][0]
    pretty_provider_response = json.dumps(json.loads(provider_row["response_text"]), indent=2) + "\n"
    pretty_provider_hash = sha256_bytes(pretty_provider_response.encode("utf-8"))
    assert pretty_provider_hash != provider_row["response_sha256"]
    provider_row["response_text"] = pretty_provider_response
    provider_row["response_sha256"] = pretty_provider_hash
    ordinary_marker = run["attempt_history"][1]["binding"]["transport"]["local_correction"]
    ordinary_marker["prior_response_sha256"] = pretty_provider_hash

    proof = CharacterCreationExecutionService._validated_repaired_ordinary_context(
        run,
        plan,
        response_text,
    )
    assert proof is not None
    assert proof["ordinary_talent_ids"] == plan["acquisition_intent"]["ordinary_talent_ids"]
    assert proof["selected_option_id"] == ordinary_marker["selected_option_id"]

    # A tampered retained hash remains fail-closed even when the JSON parses.
    provider_row["response_sha256"] = "0" * 64
    assert CharacterCreationExecutionService._validated_repaired_ordinary_context(
        run,
        plan,
        response_text,
    ) is None


@pytest.mark.parametrize("selected_option_id", [[], {}, "", "missing-option"])
def test_ordinary_duplicate_validated_expansion_rejects_malformed_or_unknown_selected_option(selected_option_id):
    run, response_text, _diagnostic, _target = _ordinary_duplicate_repaired_response_context()
    plan = json.loads(response_text)
    marker = run["attempt_history"][1]["binding"]["transport"]["local_correction"]
    marker["selected_option_id"] = selected_option_id

    assert CharacterCreationExecutionService._validated_repaired_ordinary_context(
        run,
        plan,
        response_text,
    ) is None


def test_compact_preflight_walks_ordinary_cleanup_retry_provenance_chain():
    run, response_text, _diagnostic, _target = _ordinary_duplicate_repaired_response_context()
    plan = json.loads(response_text)

    # The current response is the Retry Local Build leaf.  The ordinary
    # expansion itself is two correction edges earlier, after an initial
    # provider response, and every later edge preserves both arrays.
    assert [row["action_type"] for row in run["attempt_history"]] == [
        "IMPORT_RESPONSE",
        "LOCAL_PROVIDER_CORRECTION",
        "LOCAL_PROVIDER_CORRECTION",
        "RETRY_LOCAL_BUILD",
    ]
    assert run["attempt_history"][-1]["response_sha256"] == sha256_bytes(
        response_text.encode("utf-8")
    )
    CharacterCreationExecutionService._validate_preferred_bounded_fields(
        run,
        plan,
        response_text=response_text,
    )


def test_ordinary_duplicate_chain_accepts_singleton_path_progression_intermediary():
    run, response_text, _diagnostic, _target = _ordinary_duplicate_repaired_response_context()
    _add_singleton_path_authority(run)
    singleton_diagnostic = _singleton_path_diagnostic()
    singleton_target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        singleton_diagnostic,
        run=run,
        prior_response=response_text,
    )
    assert singleton_target is not None
    assert singleton_target["target_kind"] == "bounded_path_progression_singleton"
    parent_attempt_id = run["attempt_history"][-1]["attempt_id"]
    request_sha256 = run["request"]["request_sha256"]
    singleton_response, merge_evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        response_text,
        canonical_json({
            "bounded_choices": {
                "path_progression_by_cl": {"1": "body_refining"},
            },
        }),
        singleton_diagnostic,
        run=run,
        repair_target=singleton_target,
    )
    singleton_marker = {
        **merge_evidence,
        "target_kind": "bounded_path_progression_singleton",
        "deterministic_server_repair": True,
        "provider_called": False,
        "deterministic_repair_algorithm": "bounded_path_progression_singleton",
        "deterministic_repair_version": "v1",
        "deterministic_repair_policy": "select_the_only_frozen_available_path_for_the_reported_cl",
        "prior_attempt_id": parent_attempt_id,
        "prior_response_sha256": sha256_bytes(response_text.encode("utf-8")),
        "applied_response_sha256": sha256_bytes(singleton_response.encode("utf-8")),
        "request_sha256": request_sha256,
        "raw_provider_completion_sha256": None,
        "raw_provider_response_sha256": None,
        "provider_completion_sha256": None,
        "provider_response_sha256": None,
        "validator_diagnostic": deepcopy(singleton_diagnostic),
    }
    singleton_transport = {
        "provider_called": False,
        "automatic_retries": 0,
        "complete_request_sha256": request_sha256,
        "prior_attempt_id": parent_attempt_id,
        "local_correction": singleton_marker,
    }
    run["attempt_history"].append({
        "attempt_id": "cg1.attempt.singleton-path",
        "run_id": run["run_id"],
        "project_id": run["project_id"],
        "ordinal": 6,
        "action_type": "LOCAL_PROVIDER_CORRECTION",
        "status": "BLOCKED",
        "request_sha256": request_sha256,
        "response_sha256": sha256_bytes(singleton_response.encode("utf-8")),
        "response_text": singleton_response,
        "prior_attempt_id": parent_attempt_id,
        "binding": {
            "submitted_request_sha256": None,
            "active_request_sha256": request_sha256,
            "transport": singleton_transport,
        },
    })
    run["transport"] = deepcopy(singleton_transport)
    run["response"] = {
        "exact_response_text": singleton_response,
        "response_sha256": sha256_bytes(singleton_response.encode("utf-8")),
    }

    proof = CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        singleton_response,
    )
    assert proof is not None
    assert proof["marker"]["target_kind"] == "ordinary_duplicate"
    validated = CharacterCreationExecutionService._validated_repaired_ordinary_context(
        run,
        json.loads(singleton_response),
        singleton_response,
    )
    assert validated is not None
    assert len(validated["ordinary_talent_ids"]) == 10
    assert len(set(validated["ordinary_talent_ids"])) == 10


def test_ordinary_duplicate_chain_accepts_interior_legacy_bypass_with_descendants():
    run, response_text = _legacy_retry_interior_descendant_context()
    plan = json.loads(response_text)

    assert [row["action_type"] for row in run["attempt_history"]] == [
        "IMPORT_RESPONSE",
        "LOCAL_PROVIDER_CORRECTION",
        "LOCAL_PROVIDER_CORRECTION",
        "RETRY_LOCAL_BUILD",
        "RETRY_LOCAL_BUILD",
        "RETRY_LOCAL_BUILD",
        "RETRY_LOCAL_BUILD",
        "LOCAL_PROVIDER_CORRECTION",
    ]
    assert [row["attempt_id"] for row in run["attempt_history"][-4:]] == [
        "cg1.attempt.legacy-six",
        "cg1.attempt.bypass",
        "cg1.attempt.strict-retry",
        "cg1.attempt.singleton-correction",
    ]

    proof = CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        response_text,
    )
    assert proof is not None
    assert proof["marker"]["target_kind"] == "ordinary_duplicate"
    validated = CharacterCreationExecutionService._validated_repaired_ordinary_context(
        run,
        plan,
        response_text,
    )
    assert validated is not None
    assert len(validated["ordinary_talent_ids"]) == 10
    assert len(set(validated["ordinary_talent_ids"])) == 10


@pytest.mark.parametrize("mutation", ["later_fork", "tampered_descendant", "bypass_metadata"])
def test_ordinary_duplicate_chain_rejects_interior_legacy_bypass_tampering(mutation):
    run, response_text = _legacy_retry_interior_descendant_context()
    rows = run["attempt_history"]
    bypass = rows[-3]
    strict_retry = rows[-2]
    singleton = rows[-1]
    if mutation == "later_fork":
        fork = deepcopy(strict_retry)
        fork["attempt_id"] = "cg1.attempt.fork"
        fork["ordinal"] = 10
        fork["prior_attempt_id"] = bypass["attempt_id"]
        fork["binding"]["transport"]["prior_attempt_id"] = bypass["attempt_id"]
        rows.append(fork)
    elif mutation == "tampered_descendant":
        singleton["prior_attempt_id"] = bypass["attempt_id"]
        singleton["binding"]["transport"]["prior_attempt_id"] = bypass["attempt_id"]
        singleton["binding"]["transport"]["local_correction"]["prior_attempt_id"] = bypass["attempt_id"]
        singleton["binding"]["transport"]["local_correction"]["prior_response_sha256"] = bypass["response_sha256"]
    else:
        bypass["binding"]["transport"]["legacy_retry_bypass"]["bypassed_attempt_ids"] = [
            "cg1.attempt.legacy-six",
            "cg1.attempt.legacy-five",
        ]

    assert CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        response_text,
    ) is None
    assert CharacterCreationExecutionService._validated_repaired_ordinary_context(
        run,
        json.loads(response_text),
        response_text,
    ) is None


def test_ordinary_duplicate_retry_local_build_bypasses_legacy_noop_suffix_and_records_proof(monkeypatch):
    run, response_text = _legacy_retry_suffix_context()
    retained_result = {
        **_blocked_result(
            run,
            response_text,
            provider_id="local",
            diagnostic_code="CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
        ),
        "status": "READY_FOR_REVIEW",
    }
    service, apply_calls = _service(monkeypatch, run, [], [retained_result])
    service._latest_attempt_id = lambda _run_id: run["attempt_history"][-1]["attempt_id"]

    result = service.retry_local_build(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert service.provider.calls == []
    assert len(apply_calls) == 1
    call = apply_calls[0]
    assert call["kwargs"]["prior_attempt_id"] == "cg1.attempt.bounded"
    transport = call["transport"]
    assert transport["automatic_retries"] == 0
    assert transport["legacy_retry_bypass"] == {
        "schema": "TianxiaFoundry.LegacyRetryBypass.v1",
        "bypassed_attempt_ids": [
            "cg1.attempt.legacy-five",
            "cg1.attempt.legacy-six",
        ],
        "linked_prior_attempt_id": "cg1.attempt.bounded",
        "response_sha256": sha256_bytes(response_text.encode("utf-8")),
        "request_sha256": run["request"]["request_sha256"],
        "reason": "missing_automatic_retries_only",
    }

    # Model the append-only row written by _apply_response and prove the
    # ordinary-repair walk accepts only the newly linked branch.
    recovered_row = deepcopy(run["attempt_history"][-1])
    recovered_row.update({
        "attempt_id": "cg1.attempt.recovered",
        "ordinal": 7,
        "prior_attempt_id": call["kwargs"]["prior_attempt_id"],
        "binding": {
            "submitted_request_sha256": run["request"]["request_sha256"],
            "active_request_sha256": run["request"]["request_sha256"],
            "transport": deepcopy(transport),
        },
    })
    run["attempt_history"].append(recovered_row)
    run["transport"] = deepcopy(transport)
    proof = CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        response_text,
    )
    assert proof is not None
    assert proof["marker"]["target_kind"] == "ordinary_duplicate"


@pytest.mark.parametrize(
    "mutation",
    [
        "response_difference",
        "provider_called",
        "extra_field",
        "broken_parent",
        "missing_binding",
        "nonnull_predecessor_submitted",
        "missing_complete_request",
        "wrong_complete_request",
        "nondeterministic_predecessor",
        "provider_called_predecessor",
        "hash_mismatch_predecessor",
        "invalid_predecessor_target_kind",
    ],
)
def test_ordinary_duplicate_retry_local_build_rejects_unsafe_legacy_noop_bypass(mutation, monkeypatch):
    run, response_text = _legacy_retry_suffix_context()
    legacy = run["attempt_history"][-1]
    predecessor = run["attempt_history"][-3]
    if mutation == "response_difference":
        changed = canonical_json({"changed": True})
        legacy["response_text"] = changed
        legacy["response_sha256"] = sha256_bytes(changed.encode("utf-8"))
    elif mutation == "provider_called":
        legacy["binding"]["transport"]["provider_called"] = True
    elif mutation == "extra_field":
        legacy["binding"]["transport"]["unexpected"] = "not-legacy"
    elif mutation == "broken_parent":
        legacy["prior_attempt_id"] = "cg1.attempt.missing"
        legacy["binding"]["transport"]["prior_attempt_id"] = "cg1.attempt.missing"
    elif mutation == "missing_binding":
        legacy.pop("binding")
    elif mutation == "nonnull_predecessor_submitted":
        predecessor["binding"]["submitted_request_sha256"] = run["request"]["request_sha256"]
    elif mutation == "missing_complete_request":
        predecessor["binding"]["transport"].pop("complete_request_sha256")
    elif mutation == "wrong_complete_request":
        predecessor["binding"]["transport"]["complete_request_sha256"] = "f" * 64
    elif mutation == "nondeterministic_predecessor":
        predecessor["binding"]["transport"]["local_correction"]["deterministic_server_repair"] = False
    elif mutation == "provider_called_predecessor":
        predecessor["binding"]["transport"]["local_correction"]["provider_called"] = True
    elif mutation == "invalid_predecessor_target_kind":
        predecessor["binding"]["transport"]["local_correction"]["target_kind"] = "unsupported_repair"
    else:
        predecessor["binding"]["transport"]["local_correction"]["applied_response_sha256"] = "0" * 64
    initial_history = deepcopy(run["attempt_history"])
    initial_transport = deepcopy(run["transport"])
    retained_result = {
        **_blocked_result(
            run,
            response_text,
            provider_id="local",
            diagnostic_code="CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
        ),
        "status": "READY_FOR_REVIEW",
    }
    service, apply_calls = _service(monkeypatch, run, [], [retained_result])
    service._latest_attempt_id = lambda _run_id: run["attempt_history"][-1]["attempt_id"]

    with pytest.raises(FoundryError) as exc_info:
        service.retry_local_build(run["run_id"])
    assert exc_info.value.code == "CG1_RETRY_LOCAL_BUILD_LEGACY_PROVENANCE_INVALID"
    assert apply_calls == []
    assert service.provider.calls == []
    if mutation == "invalid_predecessor_target_kind":
        assert run["attempt_history"] == initial_history
        assert run["transport"] == initial_transport


@pytest.mark.parametrize(
    "mutation",
    [
        "stale_hash",
        "mutated_array",
        "broken_link",
        "provider_called",
        "cycle",
        "missing_retry_retries",
        "nonzero_retry_retries",
        "missing_run_id",
        "mismatched_run_id",
        "missing_project_id",
        "mismatched_project_id",
        "missing_request_sha256",
        "mismatched_request_sha256",
    ],
)
def test_compact_preflight_rejects_forged_ordinary_provenance_chain(mutation):
    run, response_text, _diagnostic, _target = _ordinary_duplicate_repaired_response_context()
    rows = run["attempt_history"]
    if mutation == "stale_hash":
        rows[2]["response_sha256"] = "0" * 64
    elif mutation == "mutated_array":
        payload = json.loads(rows[2]["response_text"])
        ordinary = payload["acquisition_intent"]["ordinary_talent_ids"]
        ordinary[0], ordinary[1] = ordinary[1], ordinary[0]
        payload["selection_intent"]["by_slot"]["advancement_skeleton"] = ordinary
        mutated = canonical_json(payload)
        rows[2]["response_text"] = mutated
        rows[2]["response_sha256"] = sha256_bytes(mutated.encode("utf-8"))
        rows[2]["binding"]["transport"]["local_correction"]["applied_response_sha256"] = rows[2]["response_sha256"]
    elif mutation == "broken_link":
        rows[2]["prior_attempt_id"] = "cg1.attempt.missing"
        rows[2]["binding"]["transport"]["local_correction"]["prior_attempt_id"] = "cg1.attempt.missing"
    elif mutation == "provider_called":
        rows[2]["binding"]["transport"]["provider_called"] = True
    elif mutation == "cycle":
        rows[3]["prior_attempt_id"] = rows[3]["attempt_id"]
        rows[3]["binding"]["transport"]["prior_attempt_id"] = rows[3]["attempt_id"]
    elif mutation == "missing_retry_retries":
        rows[3]["binding"]["transport"].pop("automatic_retries")
    elif mutation == "nonzero_retry_retries":
        rows[3]["binding"]["transport"]["automatic_retries"] = 1
    elif mutation == "missing_run_id":
        rows[2].pop("run_id")
    elif mutation == "mismatched_run_id":
        rows[2]["run_id"] = "cg1.run.other"
    elif mutation == "missing_project_id":
        rows[2].pop("project_id")
    elif mutation == "mismatched_project_id":
        rows[2]["project_id"] = "project.other"
    elif mutation == "missing_request_sha256":
        rows[2].pop("request_sha256")
    elif mutation == "mismatched_request_sha256":
        rows[2]["request_sha256"] = "f" * 64

    with pytest.raises(FoundryError) as exc_info:
        CharacterCreationExecutionService._validate_preferred_bounded_fields(
            run,
            json.loads(response_text),
            response_text=response_text,
        )
    assert exc_info.value.code == "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID"


def test_compact_preflight_rejects_repaired_array_when_full_authority_becomes_late():
    run, response_text, _diagnostic, _target = _ordinary_duplicate_repaired_response_context()
    plan = json.loads(response_text)
    expanded_ids = plan["acquisition_intent"]["ordinary_talent_ids"]
    late_id = next(choice_id for choice_id in expanded_ids if choice_id.startswith("TAL_PACK_"))
    envelope = run["request"]["delegated_choice_envelope"]
    authority = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"][late_id]
    availability = envelope["prerequisites_and_availability"]["advancement_skeleton"][late_id]
    authority["minimum_cl"] = 11
    availability["availability"]["minimum_cl"] = 11

    with pytest.raises(FoundryError) as exc_info:
        CharacterCreationExecutionService._validate_preferred_bounded_fields(
            run,
            plan,
            response_text=response_text,
        )
    assert exc_info.value.code == "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID"
    assert any(
        issue.get("reason") == "NOT_PRESENTED_LEGAL_ORDINARY_TALENT"
        and issue.get("proposed") == late_id
        for issue in exc_info.value.details["issues"]
    )


def test_retry_local_build_expands_retained_oversized_duplicates_without_provider(monkeypatch):
    run = _ordinary_duplicate_oversized_run()
    prior_response = _ordinary_duplicate_oversized_prior_response(run)
    diagnostic = _ordinary_duplicate_oversized_diagnostic()
    run.update({
        "status": "NEEDS_REVIEW",
        "response": {
            "exact_response_text": prior_response,
            "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
        },
        "validation": {"last_submission_error": deepcopy(diagnostic)},
        "transport": {"provider_id": "local", "automatic_retries": 0},
        "attempt_history": [{"attempt_id": "cg1.attempt.first", "status": "BLOCKED"}],
    })
    retained_result = {
        **_blocked_result(run, prior_response, provider_id="local", diagnostic_code=diagnostic["code"]),
        "status": "READY_FOR_REVIEW",
    }
    service, apply_calls = _service(monkeypatch, run, [], [retained_result])

    result = service.retry_local_build(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert service.provider.calls == []
    assert len(apply_calls) == 1
    correction = apply_calls[0]["transport"]["local_correction"]
    assert correction["deterministic_server_repair"] is True
    assert correction["provider_called"] is False
    assert correction["prior_response_sha256"] == sha256_bytes(prior_response.encode("utf-8"))
    applied = json.loads(apply_calls[0]["response_text"])
    expanded_ids = applied["acquisition_intent"]["ordinary_talent_ids"]
    assert len(expanded_ids) == 10
    assert len(set(expanded_ids)) == 10
    assert applied["selection_intent"]["by_slot"]["advancement_skeleton"] == expanded_ids


def test_ordinary_duplicate_repair_keeps_redundant_top_level_advancement_exact() -> None:
    run = _ordinary_duplicate_oversized_run()
    prior_payload = json.loads(_ordinary_duplicate_oversized_prior_response(run))
    prior_payload["advancement_skeleton"] = deepcopy(
        prior_payload["acquisition_intent"]["ordinary_talent_ids"]
    )
    prior_response = canonical_json(prior_payload)
    diagnostic = _ordinary_duplicate_oversized_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None

    merged_text, evidence = CharacterCreationExecutionService._merge_ordinary_duplicate_target_response(
        prior_response,
        canonical_json({"option_id": target["option_ids"][0]}),
        target,
    )

    merged = json.loads(merged_text)
    ordinary = merged["acquisition_intent"]["ordinary_talent_ids"]
    assert merged["selection_intent"]["by_slot"]["advancement_skeleton"] == ordinary
    assert merged["advancement_skeleton"] == ordinary
    assert evidence["top_level_advancement_echo_updated"] is True


def test_ordinary_duplicate_prompt_is_compact_and_excludes_retained_response(monkeypatch):
    run = _ordinary_duplicate_run()
    prior_payload = json.loads(_ordinary_duplicate_prior_response(run))
    prior_payload["distinctive_prior_response_token"] = "ORDINARY_DUPLICATE_PRIOR_SECRET"
    prior_response = canonical_json(prior_payload)
    target = _ordinary_duplicate_target(run, prior_response)

    payload = json.loads(
        CharacterCreationExecutionService._provider_correction_prompt(
            run,
            prior_response,
            _ordinary_duplicate_diagnostic(),
            repair_target=target,
        )
    )
    assert payload["prompt_kind"] == "ordinary_duplicate_option_selector"
    assert payload["character_context"]["concept"]["value"] == (
        "A streetwise survivor who trades secrets for food."
    )
    assert payload["server_owned_option_context"]["candidate_summaries"]
    assert payload["response_contract"]["schema"] == target["response_schema"]
    assert "options" not in payload["correction_contract"]["repair_target"]
    assert "candidate_summaries" not in payload["correction_contract"]["repair_target"]
    prompt_text = canonical_json(payload)
    assert "ORDINARY_DUPLICATE_PRIOR_SECRET" not in prompt_text
    assert "prior_response_text" not in prompt_text
    assert len(prompt_text.encode("utf-8")) < 20_000


def test_ordinary_duplicate_merge_changes_only_ordinary_array_and_rejects_unknown_option():
    run = _ordinary_duplicate_run()
    prior_response = _ordinary_duplicate_prior_response(run)
    target = _ordinary_duplicate_target(run, prior_response)
    provider_response = _ordinary_duplicate_response(run, prior_response, "TAL_SAFE_A")
    merged, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        provider_response,
        _ordinary_duplicate_diagnostic(),
        run=run,
        repair_target=target,
        provider_completion_sha256=sha256_bytes(provider_response.encode("utf-8")),
        provider_response_sha256=sha256_bytes(provider_response.encode("utf-8")),
    )
    prior = json.loads(prior_response)
    applied = json.loads(merged)
    assert applied["acquisition_intent"]["ordinary_talent_ids"] == ["TAL_SAFE_A"]
    retained_prior = deepcopy(prior)
    retained_prior["acquisition_intent"] = deepcopy(prior["acquisition_intent"])
    retained_prior["acquisition_intent"]["ordinary_talent_ids"] = ["TAL_SAFE_A"]
    assert applied == retained_prior
    assert evidence["target_kind"] == "ordinary_duplicate"
    assert evidence["selected_ordinary_talent_ids"] == ["TAL_SAFE_A"]
    assert evidence["raw_provider_completion_sha256"] != evidence["applied_response_sha256"]

    with pytest.raises(FoundryError) as exc_info:
        CharacterCreationExecutionService._merge_target_scoped_correction_response(
            prior_response,
            canonical_json({"option_id": "not-server-owned"}),
            _ordinary_duplicate_diagnostic(),
            run=run,
            repair_target=target,
        )
    assert exc_info.value.code == "CG1_LOCAL_CORRECTION_TARGET_INVALID"
    assert json.loads(prior_response)["acquisition_intent"]["ordinary_talent_ids"] == ["TAL_FREE"]


def test_ordinary_duplicate_initial_path_expands_provider_free_and_explicit_path_remains_one_call(monkeypatch):
    run = _ordinary_duplicate_run()
    prior_response = _ordinary_duplicate_prior_response(run)
    provider_response = _ordinary_duplicate_response(run, prior_response, "TAL_SAFE_B")
    first = _blocked_result(run, prior_response, provider_id="local", diagnostic_code="CG1_DELEGATED_DUPLICATE_CHOICE")
    first["validation"]["last_submission_error"] = _ordinary_duplicate_diagnostic()
    second = {
        **_blocked_result(run, provider_response, provider_id="local", automatic_retries=1, diagnostic_code="CG1_DELEGATED_DUPLICATE_CHOICE"),
        "status": "READY_FOR_REVIEW",
    }
    second["validation"]["last_submission_error"] = _ordinary_duplicate_diagnostic()
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(prior_response, provider_id="local"), _receipt(provider_response, provider_id="local")],
        [first, second],
    )
    result = service._run_provider(run["run_id"])
    target = _ordinary_duplicate_target(run, prior_response)
    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    expected_automatic_ids = target["options"][target["option_ids"][0]]["ordinary_talent_ids"]
    assert json.loads(apply_calls[1]["response_text"])["acquisition_intent"]["ordinary_talent_ids"] == expected_automatic_ids
    assert apply_calls[1]["transport"]["local_correction"]["target_kind"] == "ordinary_duplicate"
    assert apply_calls[1]["transport"]["local_correction"]["deterministic_server_repair"] is True
    assert apply_calls[1]["transport"]["local_correction"]["provider_called"] is False
    assert apply_calls[1]["transport"]["automatic_retries"] == 0

    explicit_run = _explicit_review_run(diagnostic_code="CG1_DELEGATED_DUPLICATE_CHOICE")
    explicit_run["request"] = deepcopy(run["request"])
    explicit_run["owner_descriptive_fields"] = deepcopy(run["owner_descriptive_fields"])
    explicit_run["response"] = {
        "exact_response_text": prior_response,
        "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
    }
    explicit_run["validation"]["last_submission_error"] = _ordinary_duplicate_diagnostic()
    corrected = {
        **explicit_run,
        "status": "READY_FOR_REVIEW",
        "response": {
            "exact_response_text": provider_response,
            "response_sha256": sha256_bytes(provider_response.encode("utf-8")),
        },
    }
    explicit_service, explicit_apply_calls = _service(
        monkeypatch,
        explicit_run,
        [_receipt(provider_response, provider_id="local")],
        [corrected],
    )
    explicit_result = explicit_service.retry_local_ai_correction(explicit_run["run_id"])
    assert explicit_result["status"] == "READY_FOR_REVIEW"
    assert len(explicit_service.provider.calls) == 1
    assert explicit_service.provider.calls[0]["response_schema"] == target["response_schema"]
    assert json.loads(explicit_apply_calls[0]["response_text"])["acquisition_intent"]["ordinary_talent_ids"] == ["TAL_SAFE_B"]


def test_repeated_ordinary_duplicate_preserves_one_and_updates_mirror_after_automatic_retry(monkeypatch):
    run = _ordinary_duplicate_required_two_run()
    repeated_id = "TAL_SAFE_A"
    prior_payload = json.loads(
        _ordinary_duplicate_prior_response(run, ordinary_ids=[repeated_id, repeated_id])
    )
    prior_payload["selection_intent"]["by_slot"]["advancement_skeleton"] = [
        repeated_id,
        repeated_id,
    ]
    prior_response = canonical_json(prior_payload)
    diagnostic = {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_DELEGATED_DUPLICATE_CHOICE",
        "message": "Preferred selection IDs may not be silently deduplicated.",
        "details": {
            "choice_ids": [repeated_id, repeated_id],
            "slot_id": "advancement_skeleton",
        },
    }

    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert target["preserved_ordinary_talent_ids"] == [repeated_id]
    assert target["required_count"] == 2
    assert all(
        option["ordinary_talent_ids"].count(repeated_id) == 1
        and len(set(option["ordinary_talent_ids"])) == 2
        for option in target["options"].values()
    )

    option_id = target["option_ids"][0]
    merged_text, _evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        canonical_json({"option_id": option_id}),
        diagnostic,
        run=run,
        repair_target=target,
    )
    merged = json.loads(merged_text)
    corrected_ids = merged["acquisition_intent"]["ordinary_talent_ids"]
    assert corrected_ids == merged["selection_intent"]["by_slot"]["advancement_skeleton"]
    assert corrected_ids.count(repeated_id) == 1
    assert len(set(corrected_ids)) == 2

    explicit_run = _explicit_review_run(
        execution_mode="AUTO_FINALIZE_WHEN_CLEAN",
        diagnostic_code="CG1_DELEGATED_DUPLICATE_CHOICE",
    )
    explicit_run["request"] = deepcopy(run["request"])
    explicit_run["response"] = {
        "exact_response_text": prior_response,
        "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
    }
    explicit_run["validation"]["last_submission_error"] = deepcopy(diagnostic)
    explicit_run["submission_error"] = deepcopy(diagnostic)
    explicit_run["transport"]["automatic_retries"] = 1
    service, _apply_calls = _service(monkeypatch, explicit_run, [], [])

    context = service._explicit_provider_correction_context(explicit_run)
    assert context is not None
    assert context["explicit_target_scoped_after_automatic"] is True
    assert service._action_availability(explicit_run)["retry_local_ai_correction"]["available"] is True


def test_insight_unavailable_target_filters_frozen_candidates_and_preserves_count():
    run = _insight_unavailable_run()
    prior_response = _insight_unavailable_prior_response(run)
    target = _insight_unavailable_target(run, prior_response)

    assert target["required_count"] == 1
    assert target["candidate_ids"] == ["INS_PATH", "INS_SAFE"]
    assert len(target["options"]) == 2
    assert target["response_schema"]["additionalProperties"] is False
    assert target["response_schema"]["required"] == ["option_id"]
    assert target["response_schema"]["properties"]["option_id"]["enum"] == target["option_ids"]
    assert all(
        option["insight_priorities"] in (["INS_PATH"], ["INS_SAFE"])
        and len(option["insight_priorities"]) == target["required_count"]
        for option in target["options"].values()
    )
    assert "INS_BAD" not in target["candidate_ids"]
    assert "INS_HIGH" not in target["candidate_ids"]
    assert "INS_BLOCKED" not in target["candidate_ids"]
    assert "INS_UNAVAILABLE" not in target["candidate_ids"]
    assert {row["id"] for row in target["candidate_summaries"]} == set(target["candidate_ids"])


def test_insight_unavailable_prompt_is_compact_and_excludes_retained_response(monkeypatch):
    run = _insight_unavailable_run()
    prior_payload = json.loads(_insight_unavailable_prior_response(run))
    prior_payload["distinctive_prior_response_token"] = "INSIGHT_UNAVAILABLE_PRIOR_SECRET"
    prior_response = canonical_json(prior_payload)
    target = _insight_unavailable_target(run, prior_response)

    payload = json.loads(
        CharacterCreationExecutionService._provider_correction_prompt(
            run,
            prior_response,
            _insight_unavailable_diagnostic(),
            repair_target=target,
        )
    )
    assert payload["prompt_kind"] == "insight_unavailable_option_selector"
    assert payload["character_context"]["concept"]["value"] == (
        "A patient toolmaker seeking forgotten techniques."
    )
    assert payload["server_owned_option_context"]["required_count"] == 1
    assert payload["response_contract"]["schema"] == target["response_schema"]
    prompt_text = canonical_json(payload)
    assert "INSIGHT_UNAVAILABLE_PRIOR_SECRET" not in prompt_text
    assert "prior_response_text" not in prompt_text
    assert len(prompt_text.encode("utf-8")) < 20_000


def test_insight_unavailable_merge_changes_only_priority_array_and_rejects_unknown_option():
    run = _insight_unavailable_run()
    prior_response = _insight_unavailable_prior_response(run)
    target = _insight_unavailable_target(run, prior_response)
    provider_response = _insight_unavailable_response(run, prior_response, 0)
    merged, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        provider_response,
        _insight_unavailable_diagnostic(),
        run=run,
        repair_target=target,
        provider_completion_sha256=sha256_bytes(provider_response.encode("utf-8")),
        provider_response_sha256=sha256_bytes(provider_response.encode("utf-8")),
    )
    prior = json.loads(prior_response)
    applied = json.loads(merged)
    selected_ids = target["options"][target["option_ids"][0]]["insight_priorities"]
    expected = deepcopy(prior)
    expected["selection_intent"]["by_slot"]["insight_priorities"] = selected_ids
    assert applied == expected
    assert evidence["target_kind"] == "insight_unavailable"
    assert evidence["selected_insight_priority_ids"] == selected_ids
    assert evidence["raw_provider_completion_sha256"] != evidence["applied_response_sha256"]

    for malformed_response in (
        canonical_json({}),
        canonical_json({"option_id": target["option_ids"][0], "extra": True}),
        canonical_json({"option_id": "not-server-owned"}),
    ):
        with pytest.raises(FoundryError) as exc_info:
            CharacterCreationExecutionService._merge_target_scoped_correction_response(
                prior_response,
                malformed_response,
                _insight_unavailable_diagnostic(),
                run=run,
                repair_target=target,
            )
        assert exc_info.value.code == "CG1_LOCAL_CORRECTION_TARGET_INVALID"
    assert json.loads(prior_response)["selection_intent"]["by_slot"]["insight_priorities"] == ["INS_BAD"]


def test_insight_unavailable_automatic_run_is_retained_and_explicit_path_reuses_opaque_target(monkeypatch):
    run = _insight_unavailable_run()
    prior_response = _insight_unavailable_prior_response(run)
    provider_response = _insight_unavailable_response(run, prior_response, 1)
    first = {**run, **_blocked_result(
        run,
        prior_response,
        provider_id="local",
        diagnostic_code="CG1_DELEGATED_CHOICE_UNAVAILABLE",
    )}
    first["validation"]["last_submission_error"] = _insight_unavailable_diagnostic()
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(prior_response, provider_id="local")],
        [first],
    )
    result = service._run_provider(run["run_id"])
    target = _insight_unavailable_target(run, prior_response)
    # e67e4e9e: the automatic run keeps the failed response; only the owner's
    # explicit action may spend the one correction call.
    assert result == first
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 1
    expected_ids = target["options"][target["option_ids"][1]]["insight_priorities"]

    explicit_run = _explicit_review_run(diagnostic_code="CG1_DELEGATED_CHOICE_UNAVAILABLE")
    explicit_run["request"] = deepcopy(run["request"])
    explicit_run["owner_descriptive_fields"] = deepcopy(run["owner_descriptive_fields"])
    explicit_run["response"] = {
        "exact_response_text": prior_response,
        "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
    }
    explicit_run["validation"]["last_submission_error"] = _insight_unavailable_diagnostic()
    corrected = {
        **explicit_run,
        "status": "READY_FOR_REVIEW",
        "response": {
            "exact_response_text": provider_response,
            "response_sha256": sha256_bytes(provider_response.encode("utf-8")),
        },
    }
    explicit_service, explicit_apply_calls = _service(
        monkeypatch,
        explicit_run,
        [_receipt(provider_response, provider_id="local")],
        [corrected],
    )
    explicit_result = explicit_service.retry_local_ai_correction(explicit_run["run_id"])
    assert explicit_result["status"] == "READY_FOR_REVIEW"
    assert len(explicit_service.provider.calls) == 1
    assert explicit_service.provider.calls[0]["response_schema"] == target["response_schema"]
    assert json.loads(explicit_apply_calls[0]["response_text"])["selection_intent"]["by_slot"]["insight_priorities"] == expected_ids
    assert explicit_apply_calls[0]["transport"]["local_correction"]["target_kind"] == "insight_unavailable"


def test_free_talent_sphere_mismatch_derives_one_legal_deterministic_mapping_and_preserves_fields():
    run = _free_talent_sphere_run()
    prior_response = _free_talent_sphere_prior_response(run)
    diagnostic = _free_talent_sphere_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert target["target_kind"] == "free_talent_sphere_server_repair"
    assert target["selected_sphere_ids"] == ["sphere.scoundrel"]
    assert target["required_count"] == 1
    assert target["selection_limits"]["final_min"] == 0
    assert target["selection_limits"]["final_max"] is None

    merged, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        "",
        diagnostic,
        run=run,
        repair_target=target,
    )
    before = json.loads(prior_response)
    after = json.loads(merged)
    assert after["selection_intent"]["by_slot"]["sphere_priorities"] == ["sphere.scoundrel"]
    before["selection_intent"]["by_slot"]["sphere_priorities"] = ["sphere.scoundrel"]
    assert after == before
    assert evidence["provider_called"] is False
    assert evidence["deterministic_server_repair"] is True
    assert evidence["raw_provider_completion_sha256"] is None
    assert evidence["applied_response_sha256"] == sha256_bytes(merged.encode("utf-8"))


def test_free_talent_sphere_mismatch_explicit_and_automatic_paths_make_no_provider_call(monkeypatch):
    run = _free_talent_sphere_run()
    prior_response = _free_talent_sphere_prior_response(run)
    diagnostic = _free_talent_sphere_diagnostic()

    first = _blocked_result(
        run,
        prior_response,
        provider_id="local",
        diagnostic_code=diagnostic["code"],
    )
    first["validation"]["last_submission_error"] = diagnostic
    corrected_response = json.loads(prior_response)
    corrected_response["selection_intent"]["by_slot"]["sphere_priorities"] = ["sphere.scoundrel"]
    corrected_response = canonical_json(corrected_response)
    second = _blocked_result(
        run,
        corrected_response,
        provider_id="local",
        automatic_retries=0,
        diagnostic_code=diagnostic["code"],
    )
    second["status"] = "READY_FOR_REVIEW"
    second["validation"]["last_submission_error"] = diagnostic
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(prior_response, provider_id="local")],
        [first, second],
    )
    result = service._run_provider(run["run_id"])
    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 2
    assert result["transport"]["automatic_retries"] == 0
    assert json.loads(apply_calls[1]["response_text"])["selection_intent"]["by_slot"]["sphere_priorities"] == ["sphere.scoundrel"]
    assert apply_calls[1]["transport"]["provider_called"] is False
    assert apply_calls[1]["transport"]["local_correction"]["deterministic_server_repair"] is True

    explicit_run = _explicit_review_run(diagnostic_code=diagnostic["code"])
    explicit_run["request"] = deepcopy(run["request"])
    explicit_run["owner_descriptive_fields"] = deepcopy(run["owner_descriptive_fields"])
    explicit_run["response"] = {
        "exact_response_text": prior_response,
        "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
    }
    explicit_run["validation"]["last_submission_error"] = diagnostic
    explicit_service, explicit_apply_calls = _service(
        monkeypatch,
        explicit_run,
        [],
        [{**explicit_run, "status": "READY_FOR_REVIEW"}],
    )
    explicit_result = explicit_service.retry_local_ai_correction(explicit_run["run_id"])
    assert explicit_result["status"] == "READY_FOR_REVIEW"
    assert explicit_service.provider.calls == []
    assert len(explicit_apply_calls) == 1
    assert explicit_apply_calls[0]["transport"]["provider_called"] is False
    assert explicit_apply_calls[0]["transport"]["local_correction"]["explicit"] is True
    assert json.loads(explicit_apply_calls[0]["response_text"])["selection_intent"]["by_slot"]["sphere_priorities"] == ["sphere.scoundrel"]


def test_free_talent_sphere_mismatch_is_exact_and_fails_closed_for_ambiguity_or_generic_shape():
    run = _free_talent_sphere_run()
    prior_response = _free_talent_sphere_prior_response(run)
    diagnostic = _free_talent_sphere_diagnostic()
    for bad_diagnostic in (
        {**diagnostic, "details": {**diagnostic["details"], "sphere_ids": ["sphere.scoundrel"]}},
        {**diagnostic, "details": {**diagnostic["details"], "extra": "unexpected"}},
        {**diagnostic, "code": "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID"},
    ):
        assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
            bad_diagnostic,
            run=run,
            prior_response=prior_response,
        ) is None

    conflicting = json.loads(prior_response)
    conflicting["selection_intent"]["by_slot"]["sphere_priorities"] = ["sphere.other"]
    assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=canonical_json(conflicting),
    ) is None

    ambiguous = json.loads(prior_response)
    ambiguous["acquisition_intent"]["sphere_free_talent_pairs"].append(
        {"sphere_id": "sphere.other", "talent_id": "TAL_OTHER"}
    )
    assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=canonical_json(ambiguous),
    ) is None

    no_authority = deepcopy(run)
    del no_authority["request"]["delegated_choice_envelope"]["choices_by_slot"]["sphere_priorities"]["sphere.scoundrel"]
    assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=no_authority,
        prior_response=prior_response,
    ) is None


def test_free_talent_sphere_repair_rejects_negative_or_inverted_frozen_bounds():
    run = _free_talent_sphere_run()
    prior_response = _free_talent_sphere_prior_response(run)
    diagnostic = _free_talent_sphere_diagnostic()
    cases = []
    for field, value in (("final_min", -1), ("owner_lock_min", -1)):
        broken = deepcopy(run)
        broken["request"]["delegated_choice_envelope"]["selection_limits_by_slot"]["sphere_priorities"][field] = value
        cases.append(broken)
    broken = deepcopy(run)
    limits = broken["request"]["delegated_choice_envelope"]["selection_limits_by_slot"]["sphere_priorities"]
    limits["final_min"] = 1
    limits["final_max"] = 0
    cases.append(broken)
    broken = deepcopy(run)
    limits = broken["request"]["delegated_choice_envelope"]["selection_limits_by_slot"]["sphere_priorities"]
    limits["owner_lock_min"] = 1
    limits["owner_lock_max"] = 0
    cases.append(broken)
    broken = deepcopy(run)
    broken["request"]["stage1_prompt"]["envelope"]["decision_slots"][0]["min_selections"] = -1
    cases.append(broken)
    broken = deepcopy(run)
    slot = broken["request"]["stage1_prompt"]["envelope"]["decision_slots"][0]
    slot["min_selections"] = 1
    slot["max_selections"] = 0
    cases.append(broken)
    for malformed in cases:
        assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
            diagnostic,
            run=malformed,
            prior_response=prior_response,
        ) is None


def test_free_talent_not_legal_target_filters_background_only_sphere_and_builds_compact_prompt():
    run = _free_talent_not_legal_run()
    prior_response = _free_talent_sphere_prior_response(run) + " "  # distinctive retained-only evidence
    diagnostic = _free_talent_not_legal_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert target["target_kind"] == "free_talent_not_legal"
    assert target["explicit_only"] is True
    assert target["expected_pair_count"] == 1
    assert target["candidate_summaries"]
    assert all(
        option["sphere_id"] == "sphere.legal" and option["talent_id"] == "TAL_LEGAL"
        for option in target["options"].values()
    )
    assert target["response_schema"]["additionalProperties"] is False
    assert target["response_schema"]["properties"]["option_id"]["enum"] == target["option_ids"]
    prompt = CharacterCreationExecutionService._provider_correction_prompt(
        run,
        prior_response,
        diagnostic,
        prior_response_sha256=sha256_bytes(prior_response.encode("utf-8")),
        repair_target=target,
    )
    assert "distinctive retained-only evidence" not in prompt
    for internal_value in ("sphere.legal", "TAL_LEGAL", "sphere.scoundrel", "TAL_FREE"):
        assert internal_value not in prompt
    for internal_key in ("options", "failing_pair", "validator_diagnostic", "repair_target"):
        assert f'"{internal_key}"' not in prompt
    prompt_payload = json.loads(prompt)
    assert prompt_payload["allowed_option_ids"] == target["option_ids"]
    assert prompt_payload["presented_choices"][0]["option_id"] in target["option_ids"]
    assert prompt_payload["presented_choices"][0]["sphere_name"] == "Legal Sphere"
    assert prompt_payload["presented_choices"][0]["talent_name"] == "Legal Free Talent"
    assert "option_id" in prompt
    assert len(prompt.encode("utf-8")) <= PROVIDER_PROMPT_HARD_CAP_BYTES


def test_free_talent_not_legal_shortlist_filters_route_kind_before_two_per_sphere_cap():
    run = _free_talent_not_legal_run()
    _add_route_legal_free_talent_candidate(
        run,
        "sphere.ordered",
        "TAL_Z_LEGAL",
        sphere_name="Ordered Sphere",
        talent_name="Late Legal Talent",
    )
    envelope = run["request"]["delegated_choice_envelope"]
    for talent_id in ("TAL_A_ORDINARY", "TAL_B_ORDINARY"):
        envelope["choices_by_slot"]["advancement_skeleton"][talent_id] = {
            "choice_id": talent_id,
            "content_type": "talent",
            "authority": "canonical",
            "publication_state": "published",
            "acquisition_channels": ["ordinary-talent"],
            "availability": {"minimum_cl": 1, "realm_rules": {}, "source_cl": {}, "suppression": {}},
            "prerequisites": [],
            "incompatibilities": [],
            "parent_relationships": [{"record_id": "sphere.ordered", "relation": "dependency"}],
            "name": talent_id,
        }
        envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"].append(talent_id)
        envelope["offered_choice_ids_by_slot"]["advancement_skeleton"].append(talent_id)
        envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"][talent_id] = {
            "authority_complete": True,
            "allowed_kinds": ["ordinary_talent_acquisition"],
            "allowed_channels": ["ordinary-talent"],
            "owning_canonical_sphere_id": "sphere.ordered",
            "minimum_cl": 1,
            "free_sphere_talent_eligible": False,
        }

    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        _free_talent_not_legal_diagnostic(),
        run=run,
        prior_response=_free_talent_sphere_prior_response(run),
    )

    assert target is not None
    assert any(
        option == {"sphere_id": "sphere.ordered", "talent_id": "TAL_Z_LEGAL"}
        for option in target["options"].values()
    )
    assert not any(
        option["talent_id"] in {"TAL_A_ORDINARY", "TAL_B_ORDINARY"}
        for option in target["options"].values()
    )


def test_free_talent_not_legal_shortlist_skips_explicit_false_or_prerequisite_rows_before_cap():
    run = _free_talent_not_legal_run()
    _add_route_legal_free_talent_candidate(
        run,
        "sphere.complete",
        "TAL_Z_COMPLETE",
        sphere_name="Complete Sphere",
        talent_name="Late Complete Talent",
    )
    envelope = run["request"]["delegated_choice_envelope"]
    authority_by_choice = envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]
    for index, talent_id in enumerate(("TAL_A_EXPLICIT_FALSE", "TAL_B_PREREQ")):
        source_row = {
            "choice_id": talent_id,
            "content_type": "talent",
            "authority": "canonical",
            "publication_state": "published",
            "acquisition_channels": ["ai-bootstrap-free-cl1-talent"],
            "availability": {"minimum_cl": 1, "realm_rules": {}, "source_cl": {}, "suppression": {}},
            "prerequisites": [] if index == 0 else [{"record_id": "tianxia.talent.unmet"}],
            "incompatibilities": [],
            "parent_relationships": [{"record_id": "sphere.complete", "relation": "dependency"}],
            "name": talent_id,
        }
        envelope["choices_by_slot"]["advancement_skeleton"][talent_id] = source_row
        envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"].append(talent_id)
        envelope["offered_choice_ids_by_slot"]["advancement_skeleton"].append(talent_id)
        authority_by_choice[talent_id] = {
            "authority_complete": True,
            "allowed_kinds": ["ai_bootstrap_talent_acquisition"],
            "allowed_channels": ["ai-bootstrap-free-cl1-talent"],
            "owning_canonical_sphere_id": "sphere.complete",
            "minimum_cl": 1,
            "free_sphere_talent_eligible": False if index == 0 else True,
        }

    # The frozen authority may omit the legacy compatibility flag.  Missing is
    # allowed by the canonical validator; it must not consume the cap as an
    # invalid row or be excluded from the scoped repair target.
    authority_by_choice["TAL_Z_COMPLETE"].pop("free_sphere_talent_eligible", None)

    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        _free_talent_not_legal_diagnostic(),
        run=run,
        prior_response=_free_talent_sphere_prior_response(run),
    )

    assert target is not None
    assert any(
        option == {"sphere_id": "sphere.complete", "talent_id": "TAL_Z_COMPLETE"}
        for option in target["options"].values()
    )
    assert not any(
        option["talent_id"] in {"TAL_A_EXPLICIT_FALSE", "TAL_B_PREREQ"}
        for option in target["options"].values()
    )


def test_free_talent_not_legal_target_unavailable_fails_closed_without_provider_or_response_loss(monkeypatch):
    run = _free_talent_not_legal_run()
    envelope = run["request"]["delegated_choice_envelope"]
    envelope["choices_by_slot"]["sphere_priorities"].pop("sphere.legal")
    envelope["choices_by_slot"]["advancement_skeleton"].pop("TAL_LEGAL")
    for slot_id, choice_id in (("sphere_priorities", "sphere.legal"), ("advancement_skeleton", "TAL_LEGAL")):
        envelope["allowed_choice_ids_by_slot"][slot_id].remove(choice_id)
        envelope["offered_choice_ids_by_slot"][slot_id].remove(choice_id)
        envelope["typed_choice_authority_by_slot"][slot_id]["stage2_authority_by_choice"].pop(choice_id)
    prior_response = _free_talent_sphere_prior_response(run)
    diagnostic = _free_talent_not_legal_diagnostic()
    run.update({
        "status": "NEEDS_REVIEW",
        "response": {
            "exact_response_text": prior_response,
            "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
        },
        "validation": {"last_submission_error": diagnostic},
        "transport": {"provider_id": "local", "automatic_retries": 0},
        "final_plan": {},
        "final_revision": None,
        "commit": {},
        "canonical_intent_hash": None,
        "materialized_plan_sha256": None,
        "attempt_history": [{"attempt_id": "cg1.attempt.first", "status": "BLOCKED"}],
    })
    service, _apply_calls = _service(monkeypatch, run, [], [])
    recorded = []
    service._record_explicit_provider_correction_failure = lambda run_id, **kwargs: (
        recorded.append((run_id, kwargs)) or deepcopy(run)
    )

    result = service.retry_local_ai_correction(run["run_id"])

    assert service.provider.calls == []
    assert result["response"]["exact_response_text"] == prior_response
    assert recorded[0][1]["provider_called"] is False
    assert recorded[0][1]["error"].code == "CG1_LOCAL_CORRECTION_TARGET_UNAVAILABLE"


def test_explicit_scoped_correction_recovers_one_proof_bound_prior_response(monkeypatch):
    run = _free_talent_not_legal_run()
    prior_response = _free_talent_sphere_prior_response(run)
    diagnostic = _free_talent_not_legal_diagnostic()
    bad_response = canonical_json({"request_sha256": run["request"]["request_sha256"]})
    prior_attempt_id = "cg1.attempt.24"
    latest_attempt_id = "cg1.attempt.25"
    request_sha256 = run["request"]["request_sha256"]
    run.update({
        "status": "NEEDS_REVIEW",
        "response": {
            "exact_response_text": bad_response,
            "response_sha256": sha256_bytes(bad_response.encode("utf-8")),
        },
        "validation": {
            "last_submission_error": {
                "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
                "code": "CG1_PLAN_SCHEMA_INVALID",
                "message": "The scoped correction response was not a complete plan.",
            },
        },
        "transport": {"provider_id": "local", "automatic_retries": 1},
        "final_plan": {},
        "final_revision": None,
        "commit": {},
        "canonical_intent_hash": None,
        "materialized_plan_sha256": None,
    })
    run["attempt_history"] = [
        {
            "attempt_id": prior_attempt_id,
            "run_id": run["run_id"],
            "project_id": run["project_id"],
            "request_sha256": request_sha256,
            "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
            "response_text": prior_response,
            "action_type": "REQUEST_CREATED",
            "status": "BLOCKED",
        },
        {
            "attempt_id": latest_attempt_id,
            "run_id": run["run_id"],
            "project_id": run["project_id"],
            "request_sha256": request_sha256,
            "response_sha256": sha256_bytes(bad_response.encode("utf-8")),
            "response_text": bad_response,
            "action_type": "LOCAL_PROVIDER_CORRECTION",
            "status": "BLOCKED",
            "prior_attempt_id": prior_attempt_id,
            "binding": {
                "submitted_request_sha256": None,
                "active_request_sha256": request_sha256,
                "transport": {
                    "complete_request_sha256": request_sha256,
                    "local_correction": {
                        "explicit": True,
                        "provider_id": "local",
                        "prior_attempt_id": prior_attempt_id,
                        "prior_response_sha256": sha256_bytes(prior_response.encode("utf-8")),
                        "validator_diagnostic": diagnostic,
                    },
                },
            },
            "validation": {"last_submission_error": run["validation"]["last_submission_error"]},
        },
    ]
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    corrected = canonical_json({"option_id": target["option_ids"][0]})
    applied = deepcopy(run)
    applied["status"] = "READY_FOR_REVIEW"
    service, apply_calls = _service(monkeypatch, run, [_receipt(corrected, provider_id="local")], [applied])
    service._latest_attempt_id = lambda run_id: latest_attempt_id

    result = service.retry_local_ai_correction(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 1
    assert apply_calls[0]["kwargs"]["prior_attempt_id"] == latest_attempt_id
    applied_payload = json.loads(apply_calls[0]["response_text"])
    prior_payload = json.loads(prior_response)
    prior_payload["acquisition_intent"]["sphere_free_talent_pairs"] = applied_payload["acquisition_intent"]["sphere_free_talent_pairs"]
    assert applied_payload == prior_payload


def test_explicit_scoped_correction_rejects_tampered_one_hop_recovery(monkeypatch):
    run = _free_talent_not_legal_run()
    prior_response = _free_talent_sphere_prior_response(run)
    diagnostic = _free_talent_not_legal_diagnostic()
    bad_response = canonical_json({"request_sha256": run["request"]["request_sha256"]})
    request_sha256 = run["request"]["request_sha256"]
    run.update({
        "status": "NEEDS_REVIEW",
        "response": {
            "exact_response_text": bad_response,
            "response_sha256": sha256_bytes(bad_response.encode("utf-8")),
        },
        "validation": {"last_submission_error": {"code": "CG1_PLAN_SCHEMA_INVALID"}},
        "transport": {"provider_id": "local", "automatic_retries": 1},
        "final_plan": {}, "final_revision": None, "commit": {},
        "canonical_intent_hash": None, "materialized_plan_sha256": None,
    })
    run["attempt_history"] = [
        {
            "attempt_id": "cg1.attempt.24",
            "run_id": run["run_id"], "project_id": run["project_id"],
            "request_sha256": request_sha256,
            "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
            "response_text": prior_response,
        },
        {
            "attempt_id": "cg1.attempt.25",
            "run_id": run["run_id"], "project_id": run["project_id"],
            "request_sha256": request_sha256,
            "response_sha256": sha256_bytes(bad_response.encode("utf-8")),
            "response_text": bad_response,
            "action_type": "LOCAL_PROVIDER_CORRECTION", "status": "BLOCKED",
            "prior_attempt_id": "cg1.attempt.24",
            "binding": {
                "submitted_request_sha256": "f" * 64,
                "active_request_sha256": request_sha256,
                "transport": {"local_correction": {
                    "explicit": True, "provider_id": "local",
                    "prior_attempt_id": "cg1.attempt.24",
                    "prior_response_sha256": sha256_bytes(prior_response.encode("utf-8")),
                    "validator_diagnostic": diagnostic,
                }},
            },
            "validation": {"last_submission_error": {"code": "CG1_PLAN_SCHEMA_INVALID"}},
        },
    ]
    service, _apply_calls = _service(monkeypatch, run, [], [])

    with pytest.raises(FoundryError) as exc_info:
        service.retry_local_ai_correction(run["run_id"])

    assert exc_info.value.code == "CG1_LOCAL_AI_CORRECTION_UNAVAILABLE"
    assert service.provider.calls == []


def test_free_talent_not_legal_target_caps_large_legal_catalog_after_sealed_shortlist():
    run = _free_talent_not_legal_run()
    for index in range(140):
        sphere_id = f"sphere.bulk.{index:03d}"
        _add_route_legal_free_talent_candidate(
            run,
            sphere_id,
            f"TAL_BULK_{index:03d}_A",
            sphere_name=f"Bulk Sphere {index:03d}",
            talent_name=f"Bulk Talent A {index:03d}",
        )
        _add_route_legal_free_talent_candidate(
            run,
            sphere_id,
            f"TAL_BULK_{index:03d}_B",
            sphere_name=f"Bulk Sphere {index:03d}",
            talent_name=f"Bulk Talent B {index:03d}",
        )
    prior_response = _free_talent_sphere_prior_response(run)
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        _free_talent_not_legal_diagnostic(),
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert 0 < len(target["option_ids"]) <= 256
    assert len(target["option_ids"]) == 256
    assert all(
        option["sphere_id"].startswith("sphere.bulk.") or option["sphere_id"] == "sphere.legal"
        for option in target["options"].values()
    )


def test_free_talent_not_legal_excludes_retained_sphere_or_talent_reuse_at_target_and_merge():
    run = _free_talent_not_legal_run()
    _add_route_legal_free_talent_candidate(
        run,
        "sphere.alt",
        "TAL_ALT",
        sphere_name="Alternate Sphere",
        talent_name="Alternate Talent",
    )
    prior_payload = json.loads(_free_talent_sphere_prior_response(run))
    prior_payload["acquisition_intent"]["sphere_free_talent_pairs"] = [
        {"sphere_id": "sphere.scoundrel", "talent_id": "TAL_FREE"},
        {"sphere_id": "sphere.legal", "talent_id": "TAL_LEGAL"},
    ]
    prior_response = canonical_json(prior_payload)
    diagnostic = _free_talent_not_legal_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    assert target["options"]
    assert all(
        option["sphere_id"] != "sphere.legal" and option["talent_id"] != "TAL_LEGAL"
        for option in target["options"].values()
    )
    assert any(
        option == {"sphere_id": "sphere.alt", "talent_id": "TAL_ALT"}
        for option in target["options"].values()
    )
    for option in (
        {"sphere_id": "sphere.legal", "talent_id": "TAL_ALT"},
        {"sphere_id": "sphere.alt", "talent_id": "TAL_LEGAL"},
    ):
        malicious = deepcopy(target)
        malicious_id = "ftp_malicious_reuse"
        malicious["options"][malicious_id] = option
        with pytest.raises(FoundryError) as exc_info:
            CharacterCreationExecutionService._merge_target_scoped_correction_response(
                prior_response,
                canonical_json({"option_id": malicious_id}),
                diagnostic,
                run=run,
                repair_target=malicious,
            )
        assert exc_info.value.code == "CG1_LOCAL_CORRECTION_TARGET_INVALID"
        assert exc_info.value.details["reason"] in {
            "replacement_sphere_reuses_retained_pair",
            "replacement_talent_reuses_retained_pair",
        }


def test_free_talent_not_legal_merge_replaces_only_failing_pair_and_rejects_invalid_option():
    run = _free_talent_not_legal_run()
    prior_payload = json.loads(_free_talent_sphere_prior_response(run))
    prior_payload["unrelated_retained_field"]["must_remain"].append("preserve")
    prior_response = canonical_json(prior_payload)
    diagnostic = _free_talent_not_legal_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    option_id = target["option_ids"][0]
    merged, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        canonical_json({"option_id": option_id}),
        diagnostic,
        run=run,
        repair_target=target,
        provider_completion_sha256="c" * 64,
        provider_response_sha256="d" * 64,
    )
    before = json.loads(prior_response)
    after = json.loads(merged)
    assert after["acquisition_intent"]["sphere_free_talent_pairs"] == [
        {"sphere_id": "sphere.legal", "talent_id": "TAL_LEGAL"},
    ]
    before["acquisition_intent"]["sphere_free_talent_pairs"] = after["acquisition_intent"]["sphere_free_talent_pairs"]
    assert after == before
    assert evidence["target_kind"] == "free_talent_not_legal"
    assert evidence["raw_provider_completion_sha256"] == sha256_bytes(canonical_json({"option_id": option_id}).encode("utf-8"))
    assert evidence["provider_completion_sha256"] == "c" * 64
    assert evidence["provider_response_sha256"] == "d" * 64
    assert evidence["applied_response_sha256"] == sha256_bytes(merged.encode("utf-8"))
    for invalid in (
        canonical_json({"option_id": "unknown"}),
        canonical_json({"option_id": option_id, "extra": True}),
        "{}",
    ):
        with pytest.raises(FoundryError) as exc_info:
            CharacterCreationExecutionService._merge_target_scoped_correction_response(
                prior_response,
                invalid,
                diagnostic,
                run=run,
                repair_target=target,
            )
        assert exc_info.value.code == "CG1_LOCAL_CORRECTION_TARGET_INVALID"


def test_free_talent_not_legal_target_is_explicit_only_and_explicit_call_uses_strict_schema(monkeypatch):
    run = _free_talent_not_legal_run()
    prior_response = _free_talent_sphere_prior_response(run)
    diagnostic = _free_talent_not_legal_diagnostic()
    first = _blocked_result(run, prior_response, provider_id="local", diagnostic_code=diagnostic["code"])
    first["validation"]["last_submission_error"] = diagnostic
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt("initial", provider_id="local")],
        [first],
    )
    result = service._run_provider(run["run_id"])
    assert result["status"] == "NEEDS_REVIEW"
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 1

    explicit_run = _explicit_review_run(diagnostic_code=diagnostic["code"])
    explicit_run["request"] = deepcopy(run["request"])
    explicit_run["owner_descriptive_fields"] = deepcopy(run.get("owner_descriptive_fields") or {})
    explicit_run["response"] = {
        "exact_response_text": prior_response,
        "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
    }
    explicit_run["validation"]["last_submission_error"] = diagnostic
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=explicit_run,
        prior_response=prior_response,
    )
    assert target is not None
    corrected = canonical_json({"option_id": target["option_ids"][0]})
    explicit_service, explicit_apply_calls = _service(
        monkeypatch,
        explicit_run,
        [_receipt(corrected, provider_id="local")],
        [{**explicit_run, "status": "READY_FOR_REVIEW"}],
    )
    explicit_result = explicit_service.retry_local_ai_correction(explicit_run["run_id"])
    assert explicit_result["status"] == "READY_FOR_REVIEW"
    assert len(explicit_service.provider.calls) == 1
    assert explicit_service.provider.calls[0]["response_schema"] == target["response_schema"]
    assert len(explicit_apply_calls) == 1
    applied = json.loads(explicit_apply_calls[0]["response_text"])
    assert applied["acquisition_intent"]["sphere_free_talent_pairs"] == [
        {"sphere_id": "sphere.legal", "talent_id": "TAL_LEGAL"},
    ]


def test_generic_unavailable_or_malformed_insight_diagnostic_stays_fail_closed():
    run = _insight_unavailable_run()
    prior_response = _insight_unavailable_prior_response(run)
    diagnostic = _insight_unavailable_diagnostic()
    diagnostic["details"]["slot_id"] = "item_priorities"
    assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    ) is None
    diagnostic = _insight_unavailable_diagnostic()
    diagnostic["details"]["extra"] = "not part of exact shape"
    assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    ) is None


def test_generic_duplicate_shape_stays_fail_closed_without_target_scoped_merge():
    run = _ordinary_duplicate_run()
    prior_response = _ordinary_duplicate_prior_response(run)
    generic_duplicate = _ordinary_duplicate_diagnostic()
    generic_duplicate["details"] = {
        "ordinary_talent_ids": ["TAL_FREE", "TAL_FREE"],
    }
    assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
        generic_duplicate,
        run=run,
        prior_response=prior_response,
    ) is None


def test_local_correction_attempt_is_accepted_by_attempt_history_schema(fresh_db):
    project_id = "project.local-correction-history"
    run_id = "cg1.run.local-correction-history"
    request_sha256 = "r" * 64
    project_json = canonical_json({
        "project_id": project_id,
        "working_name": "Local correction history",
        "revision": 0,
        "content_lock": {"lock_hash": "lock.local-correction-history"},
    })
    with fresh_db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(
                project_id,working_name,status,revision,created_at,updated_at,
                target_factory_version,target_candidate_schema_version,target_gm_screen_version,
                catalog_build_hash,quality_target,project_json,compatibility_projection_status,
                compile_status,consumer_verification_status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                project_id,
                "Local correction history",
                "draft",
                0,
                "now",
                "now",
                "x",
                "x",
                "x",
                None,
                "x",
                project_json,
                "x",
                "x",
                "x",
            ),
        )
        conn.execute(
            """INSERT INTO character_creation_runs(
                run_id,project_id,starting_revision,execution_mode,idempotency_key,
                request_json,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                project_id,
                0,
                "STANDARD_API",
                "local-correction-history-key",
                canonical_json({"request_sha256": request_sha256}),
                "WAITING_FOR_RESPONSE",
                "now",
                "now",
            ),
        )

    service = object.__new__(CharacterCreationExecutionService)
    service.db = fresh_db
    attempt_id = service._append_attempt(
        {
            "run_id": run_id,
            "project_id": project_id,
            "request": {"request_sha256": request_sha256},
        },
        action_type="LOCAL_PROVIDER_CORRECTION",
        status="BLOCKED",
        response_text='{"path":"missing"}',
    )

    with fresh_db.connection() as conn:
        row = conn.execute(
            "SELECT action_type,status FROM character_creation_attempt_history WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
    assert row["action_type"] == "LOCAL_PROVIDER_CORRECTION"
    assert row["status"] == "BLOCKED"
    with pytest.raises(sqlite3.IntegrityError):
        with fresh_db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_attempt_history SET status=? WHERE attempt_id=?",
                ("MUTATED", attempt_id),
            )


@pytest.mark.parametrize(
    "receipts",
    [
        # Each sequence is what one of the former automatic contract-retry
        # tests fed the provider; only its first entry is ever consumed now.
        [_contract_error("e" * 64), _receipt('{"good":"corrected"}', provider_id="local")],
        [_contract_error("f" * 64), _receipt('{"still":"invalid"}', provider_id="local")],
        [_contract_error("a" * 64, reason="first empty content"), _contract_error("b" * 64, reason="second empty content")],
        [_contract_error("c" * 64), _receipt('{"changed":"provider"}', provider_id="custom")],
    ],
    ids=["empty_then_corrected", "empty_then_invalid", "empty_twice", "empty_then_provider_changed"],
)
def test_local_contract_failure_never_spends_an_automatic_retry(monkeypatch, receipts):
    # e67e4e9e removed the automatic Local AI contract retry: a response that
    # cannot enter the JSON validator falls back after one provider call,
    # with no retry, no compile and no change to the frozen request.
    run = _run()
    original_request = deepcopy(run["request"])
    service, apply_calls = _service(monkeypatch, run, receipts, [])
    fallback_calls = []

    def fallback(run_value, error, **kwargs):
        fallback_calls.append((run_value, error, kwargs))
        return {
            "status": "WAITING_FOR_RESPONSE",
            "execution_mode": "MANUAL_CHAT",
            "transport": {"automatic_retries": kwargs.get("automatic_retries", 0)},
        }

    service._provider_fallback = fallback
    result = service._run_provider(run["run_id"])

    assert result["status"] == "WAITING_FOR_RESPONSE"
    assert len(service.provider.calls) == 1
    assert service.provider.calls[0]["purpose"] != "character_creation_local_correction"
    assert apply_calls == []
    assert len(fallback_calls) == 1
    assert fallback_calls[0][1].code == "AI_PROVIDER_RESPONSE_CONTRACT_INVALID"
    assert fallback_calls[0][2].get("automatic_retries", 0) == 0
    assert "attempt_evidence" not in fallback_calls[0][2]
    assert result["transport"]["automatic_retries"] == 0
    assert run["request"] == original_request


def test_local_network_error_never_retries(monkeypatch):
    run = _run()
    service, apply_calls = _service(monkeypatch, run, [_network_error()], [])
    fallback_calls = []
    service._provider_fallback = lambda run_value, error, **kwargs: (
        fallback_calls.append((run_value, error, kwargs))
        or {"status": "WAITING_FOR_RESPONSE", "transport": {"automatic_retries": kwargs.get("automatic_retries", 0)}}
    )

    result = service._run_provider(run["run_id"])

    assert result["status"] == "WAITING_FOR_RESPONSE"
    assert len(service.provider.calls) == 1
    assert apply_calls == []
    assert fallback_calls[0][1].code == "AI_PROVIDER_NETWORK_ERROR"
    assert set(fallback_calls[0][2]) == {"timing_receipt"}
    assert fallback_calls[0][2]["timing_receipt"]["schema"] == "TianxiaFoundry.CharacterCreationTimingReceipt.v1"
    assert result["transport"]["automatic_retries"] == 0


def test_local_correction_failure_remains_needs_review_and_does_not_mutate(monkeypatch):
    run = _run()
    first_response = '{"bad":"first"}'
    last_response = '{"bad":"still-invalid"}'
    first = {**run, **_blocked_result(run, first_response, provider_id="lemonade")}
    automatic_service, automatic_apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(first_response, provider_id="lemonade")],
        [first],
        provider_id="lemonade",
    )
    retained_result = automatic_service._run_provider(run["run_id"])
    assert retained_result == first
    assert len(automatic_service.provider.calls) == 1
    assert len(automatic_apply_calls) == 1
    assert retained_result["transport"]["automatic_retries"] == 0

    retained = _retained_for_explicit_correction(run, first)
    second = _blocked_result(retained, last_response, provider_id="lemonade")
    service, apply_calls = _service(
        monkeypatch,
        retained,
        [_receipt(last_response, provider_id="lemonade")],
        [second],
        provider_id="lemonade",
    )
    result = service.retry_local_ai_correction(retained["run_id"])

    assert result["status"] == "NEEDS_REVIEW"
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 1
    assert apply_calls[0]["kwargs"]["action_type"] == "LOCAL_PROVIDER_CORRECTION"
    assert result["response"]["exact_response_text"] == last_response
    assert result["final_plan"] == {}


def test_nonlocal_invalid_response_never_auto_retries(monkeypatch):
    run = _run()
    first_response = '{"bad":"cloud"}'
    first = _blocked_result(run, first_response, provider_id="custom")
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(first_response, provider_id="custom")],
        [first],
    )
    result = service._run_provider(run["run_id"])

    assert result is not None
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 1
    assert apply_calls[0]["kwargs"].get("action_type") is None
    assert result["transport"]["automatic_retries"] == 0


def test_explicit_local_correction_uses_one_call_and_links_retained_evidence(monkeypatch):
    run = _explicit_review_run()
    original_request = deepcopy(run["request"])
    corrected_response = '{"path":"corrected"}'
    corrected = {
        **run,
        "status": "READY_FOR_REVIEW",
        "response": {
            "exact_response_text": corrected_response,
            "response_sha256": sha256_bytes(corrected_response.encode("utf-8")),
        },
    }
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(corrected_response, provider_id="local")],
        [corrected],
    )

    result = service.retry_local_ai_correction(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    call = service.provider.calls[0]
    assert call["purpose"] == "character_creation_local_correction"
    correction = json.loads(call["prompt_text"])["correction_contract"]
    assert correction["prior_response_text"] == run["response"]["exact_response_text"]
    assert correction["validator_diagnostic"]["code"] == "CG1_METHOD_PATH_INCOMPATIBLE"
    assert len(apply_calls) == 1
    assert apply_calls[0]["kwargs"]["action_type"] == "LOCAL_PROVIDER_CORRECTION"
    assert apply_calls[0]["kwargs"]["prior_attempt_id"] == "cg1.attempt.first"
    assert apply_calls[0]["transport"]["local_correction"]["explicit"] is True
    assert run["request"] == original_request


@pytest.mark.parametrize(
    ("execution_mode", "provider_id", "diagnostic_code"),
    [
        ("MANUAL_CHAT", "local", "CG1_METHOD_PATH_INCOMPATIBLE"),
        ("STANDARD_API", "custom", "CG1_METHOD_PATH_INCOMPATIBLE"),
        ("STANDARD_API", "local", "CG1_STAGE2_INVALID"),
    ],
)
def test_explicit_local_correction_unavailable_makes_zero_calls(
    monkeypatch,
    execution_mode,
    provider_id,
    diagnostic_code,
):
    run = _explicit_review_run(
        provider_id=provider_id,
        execution_mode=execution_mode,
        diagnostic_code=diagnostic_code,
    )
    service, apply_calls = _service(monkeypatch, run, [], [])

    with pytest.raises(FoundryError) as exc_info:
        service.retry_local_ai_correction(run["run_id"])

    assert exc_info.value.code == "CG1_LOCAL_AI_CORRECTION_UNAVAILABLE"
    assert service.provider.calls == []
    assert apply_calls == []


def test_explicit_local_correction_availability_is_instance_aware(monkeypatch):
    run = _explicit_review_run()
    service, _apply_calls = _service(monkeypatch, run, [], [])
    assert service._action_availability(run)["retry_local_ai_correction"]["available"] is True

    local_auto = deepcopy(run)
    local_auto["execution_mode"] = "AUTO_FINALIZE_WHEN_CLEAN"
    assert service._action_availability(local_auto)["retry_local_ai_correction"]["available"] is True

    manual = deepcopy(run)
    manual["execution_mode"] = "MANUAL_CHAT"
    assert service._action_availability(manual)["retry_local_ai_correction"]["available"] is False


def test_local_auto_method_required_is_eligible_for_bounded_correction(monkeypatch):
    run = _explicit_review_run(
        execution_mode="AUTO_FINALIZE_WHEN_CLEAN",
        diagnostic_code="CG1_DELEGATED_METHOD_REQUIRED",
    )
    service, _apply_calls = _service(monkeypatch, run, [], [])

    context = service._explicit_provider_correction_context(run)

    assert context is not None
    assert context["diagnostic"]["code"] == "CG1_DELEGATED_METHOD_REQUIRED"
    assert service._provider_correction_eligible(run, run, "local") is not None


def test_explicit_correction_cannot_spend_a_second_provider_call_after_automatic_retry(monkeypatch):
    run = _explicit_review_run(
        execution_mode="AUTO_FINALIZE_WHEN_CLEAN",
        diagnostic_code="CG1_BOUNDED_DECISION_REQUIRED",
    )
    run["validation"]["last_submission_error"] = _ambiguous_path_diagnostic()
    run["submission_error"] = deepcopy(run["validation"]["last_submission_error"])
    run["transport"]["automatic_retries"] = 1
    service, apply_calls = _service(monkeypatch, run, [], [])

    assert service._explicit_provider_correction_context(run) is None
    assert service._action_availability(run)["retry_local_ai_correction"]["available"] is False
    with pytest.raises(FoundryError) as exc_info:
        service.retry_local_ai_correction(run["run_id"])

    assert exc_info.value.code == "CG1_LOCAL_AI_CORRECTION_UNAVAILABLE"
    assert service.provider.calls == []
    assert apply_calls == []


def test_local_auto_correction_can_continue_with_proof_bound_deterministic_repair(monkeypatch):
    run = _explicit_review_run(
        execution_mode="AUTO_FINALIZE_WHEN_CLEAN",
        diagnostic_code="CG1_DELEGATED_FREE_TALENT_NOT_LEGAL",
    )
    corrected_response = '{"corrected":"response"}'
    corrected_sha256 = sha256_bytes(corrected_response.encode("utf-8"))
    diagnostic = deepcopy(run["validation"]["last_submission_error"])
    request_sha256 = run["request"]["request_sha256"]
    prior_attempt_id = "cg1.attempt.original"
    latest_attempt_id = "cg1.attempt.correction"
    run["response"] = {
        "exact_response_text": corrected_response,
        "response_sha256": corrected_sha256,
    }
    run["attempt_history"] = [
        {"attempt_id": prior_attempt_id, "status": "BLOCKED"},
        {
            "attempt_id": latest_attempt_id,
            "run_id": run["run_id"],
            "project_id": run["project_id"],
            "action_type": "LOCAL_PROVIDER_CORRECTION",
            "status": "BLOCKED",
            "request_sha256": request_sha256,
            "response_sha256": corrected_sha256,
            "prior_attempt_id": prior_attempt_id,
            "binding": {
                "active_request_sha256": request_sha256,
                "transport": {
                    "complete_request_sha256": request_sha256,
                    "local_correction": {
                        "explicit": True,
                        "status": "RETAINED_FOR_VALIDATION",
                        "provider_id": "local",
                        "prior_attempt_id": prior_attempt_id,
                        "prior_response_sha256": "a" * 64,
                        "validator_diagnostic": {"code": "CG1_DELEGATED_METHOD_REQUIRED"},
                    },
                },
            },
            "error": deepcopy(diagnostic),
        },
    ]
    service, _apply_calls = _service(monkeypatch, run, [], [])

    context = service._explicit_provider_correction_context(run)

    assert context is not None
    assert context["deterministic_only"] is True
    assert context["response_text"] == corrected_response
    assert context["diagnostic"]["code"] == "CG1_DELEGATED_FREE_TALENT_NOT_LEGAL"
    assert service._action_availability(run)["retry_local_ai_correction"]["available"] is True

    monkeypatch.setattr(
        CharacterCreationExecutionService,
        "_provider_target_scoped_repair_target",
        staticmethod(lambda *_args, **_kwargs: {"target_kind": "free_talent_not_legal"}),
    )
    failures = []

    def record_failure(_run_id, **kwargs):
        failures.append(kwargs)
        return {"status": "NEEDS_REVIEW"}

    service._record_explicit_provider_correction_failure = record_failure
    result = service.retry_local_ai_correction(run["run_id"])

    assert result["status"] == "NEEDS_REVIEW"
    assert service.provider.calls == []
    assert failures[0]["provider_called"] is False
    assert failures[0]["error"].code == "CG1_LOCAL_CORRECTION_PROVIDER_BOUND_EXHAUSTED"


def test_explicit_local_correction_allows_provider_free_retry_lineage(monkeypatch):
    run = _explicit_review_run()
    # Retry Local Build intentionally records no provider identity.  The
    # explicit action asks the currently selected Local AI, so missing legacy
    # lineage is acceptable while a present mismatch remains rejected.
    run["transport"].pop("provider_id")
    service, _apply_calls = _service(monkeypatch, run, [], [])

    context = service._explicit_provider_correction_context(run)

    assert context is not None
    assert context["provider_id"] == "local"
    assert service._action_availability(run)["retry_local_ai_correction"]["available"] is True

    mismatched = deepcopy(run)
    mismatched["transport"]["provider_id"] = "custom"
    assert service._explicit_provider_correction_context(mismatched) is None


def test_explicit_local_correction_failure_keeps_retained_response(monkeypatch):
    run = _explicit_review_run()
    service, _apply_calls = _service(monkeypatch, run, [_network_error()], [])
    recorded = []

    def record_failure(run_id, **kwargs):
        recorded.append((run_id, kwargs))
        return deepcopy(run)

    service._record_explicit_provider_correction_failure = record_failure
    result = service.retry_local_ai_correction(run["run_id"])

    assert len(service.provider.calls) == 1
    assert result["response"]["exact_response_text"] == run["response"]["exact_response_text"]
    assert recorded[0][1]["provider_called"] is True
    assert recorded[0][1]["prior_response"] == run["response"]["exact_response_text"]

def test_unavailable_insight_priority_correction_never_falls_back_to_full_response_retry():
    diagnostic = {
        "code": "CG1_DELEGATED_CHOICE_UNAVAILABLE",
        "details": {"slot_id": "insight_priorities", "choice_id": "INS_NO_SAFE_TARGET"},
    }
    assert CharacterCreationExecutionService._provider_correction_requires_target(diagnostic) is True
    assert CharacterCreationExecutionService._provider_correction_requires_target({
        **diagnostic,
        "details": {"slot_id": "item_priorities", "choice_id": "ITEM"},
    }) is False


def _bounded_field_cleanup_run() -> dict:
    run = _run()
    run["request"]["bounded_choice_contract"] = {
        "schema": "TianxiaFoundry.BoundedChoiceContract.v1",
        "fields": {
            "ability_scores": {"type": "point_buy_scores"},
            "background_ability": "source-backed ability",
            "ability_score_changes_by_milestone_id": "source-backed ASI deltas",
            "path_progression_by_cl": "source-backed Path IDs",
        },
    }
    return run


def _bounded_field_cleanup_response(run: dict, *, value: object = None) -> str:
    return canonical_json({
        "schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
        "request_sha256": run["request"]["request_sha256"],
        "selection_intent": {"by_slot": {}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": [],
            "insight_occurrences": [],
        },
        "bounded_choices": {
            "ability_scores": {"STR": 15},
            "background_ability": "INT",
            "ability_score_changes_by_milestone_id": {},
            "path_progression_by_cl": {},
            "ability_scores_by_milestone_id": {} if value is None else value,
        },
        "owner_descriptive_fields": {
            "identity": {"name": "Retained name"},
            "concept": "Retained concept",
        },
    })


def _bounded_field_cleanup_diagnostic(fields: list[str] | None = None) -> dict:
    return {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_PREFERRED_RESPONSE_BOUNDED_FIELD_INVALID",
        "message": "The preferred response supplied a bounded field not advertised by the sealed request.",
        "details": {"fields": fields or ["ability_scores_by_milestone_id"]},
    }


def test_bounded_field_cleanup_removes_only_empty_alias_and_keeps_bound_values():
    run = _bounded_field_cleanup_run()
    prior_response = _bounded_field_cleanup_response(run)
    diagnostic = _bounded_field_cleanup_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )

    assert target is not None
    assert target["target_kind"] == "bounded_field_cleanup"
    assert target["fields"] == ["ability_scores_by_milestone_id"]
    assert "ability_scores_by_milestone_id" not in target["advertised_bounded_choice_keys"]
    merged, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        "",
        diagnostic,
        run=run,
        repair_target=target,
    )
    prior = json.loads(prior_response)
    applied = json.loads(merged)
    assert "ability_scores_by_milestone_id" not in applied["bounded_choices"]
    assert applied["bounded_choices"]["ability_scores"] == prior["bounded_choices"]["ability_scores"]
    assert applied["bounded_choices"]["background_ability"] == prior["bounded_choices"]["background_ability"]
    assert applied["bounded_choices"]["ability_score_changes_by_milestone_id"] == prior["bounded_choices"]["ability_score_changes_by_milestone_id"]
    assert evidence["deterministic_server_repair"] is True
    assert evidence["provider_called"] is False
    assert evidence["removed_fields"] == ["ability_scores_by_milestone_id"]
    assert evidence["raw_provider_completion_sha256"] is None


def test_bounded_field_cleanup_initial_provider_flow_uses_one_call_and_zero_retries(monkeypatch):
    run = _bounded_field_cleanup_run()
    prior_response = _bounded_field_cleanup_response(run)
    diagnostic = _bounded_field_cleanup_diagnostic()
    first = _blocked_result(
        run,
        prior_response,
        provider_id="local",
        diagnostic_code=diagnostic["code"],
    )
    first["validation"]["last_submission_error"] = deepcopy(diagnostic)
    second = {
        **_blocked_result(
            run,
            prior_response,
            provider_id="local",
            diagnostic_code=diagnostic["code"],
        ),
        "status": "READY_FOR_REVIEW",
    }
    second["validation"]["last_submission_error"] = deepcopy(diagnostic)
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(prior_response, provider_id="local")],
        [first, second],
    )

    result = service._run_provider(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 2
    assert apply_calls[1]["transport"]["automatic_retries"] == 0
    correction = apply_calls[1]["transport"]["local_correction"]
    assert correction["target_kind"] == "bounded_field_cleanup"
    assert correction["deterministic_server_repair"] is True
    assert correction["provider_called"] is False
    assert json.loads(apply_calls[1]["response_text"])["bounded_choices"].get(
        "ability_scores_by_milestone_id"
    ) is None


def test_retry_local_build_applies_bounded_field_cleanup_without_provider(monkeypatch):
    run = _bounded_field_cleanup_run()
    prior_response = _bounded_field_cleanup_response(run)
    diagnostic = _bounded_field_cleanup_diagnostic()
    run.update({
        "status": "NEEDS_REVIEW",
        "response": {
            "exact_response_text": prior_response,
            "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
        },
        "validation": {"last_submission_error": deepcopy(diagnostic)},
        "transport": {"provider_id": "local", "automatic_retries": 0},
        "attempt_history": [{"attempt_id": "cg1.attempt.first", "status": "BLOCKED"}],
    })
    retained_result = {
        **_blocked_result(run, prior_response, provider_id="local", diagnostic_code=diagnostic["code"]),
        "status": "READY_FOR_REVIEW",
    }
    service, apply_calls = _service(monkeypatch, run, [], [retained_result])

    result = service.retry_local_build(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert service.provider.calls == []
    assert len(apply_calls) == 1
    correction = apply_calls[0]["transport"]["local_correction"]
    assert correction["target_kind"] == "bounded_field_cleanup"
    assert correction["provider_called"] is False
    assert "ability_scores_by_milestone_id" not in json.loads(
        apply_calls[0]["response_text"]
    )["bounded_choices"]


def test_bounded_field_cleanup_fails_closed_for_nonempty_or_unbound_cases():
    base_run = _bounded_field_cleanup_run()
    base_response = _bounded_field_cleanup_response(base_run)
    diagnostic = _bounded_field_cleanup_diagnostic()
    cases: list[tuple[str, dict, str]] = []

    nonempty_run = _bounded_field_cleanup_run()
    cases.append(("nonempty", nonempty_run, _bounded_field_cleanup_response(nonempty_run, value={"milestone": 1})))

    advertised_run = _bounded_field_cleanup_run()
    advertised_run["request"]["bounded_choice_contract"]["fields"]["ability_scores_by_milestone_id"] = "advertised"
    cases.append(("advertised", advertised_run, _bounded_field_cleanup_response(advertised_run)))

    malformed_run = _bounded_field_cleanup_run()
    malformed_payload = json.loads(_bounded_field_cleanup_response(malformed_run))
    malformed_payload["bounded_choices"] = []
    cases.append(("malformed", malformed_run, canonical_json(malformed_payload)))

    incomplete_run = _bounded_field_cleanup_run()
    incomplete_run["request"].pop("bounded_choice_contract")
    cases.append(("incomplete", incomplete_run, base_response))

    for name, run, response in cases:
        selected_diagnostic = deepcopy(diagnostic)
        if name == "mismatched":
            selected_diagnostic["code"] = "CG1_PREFERRED_RESPONSE_SHAPE_INVALID"
        assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
            selected_diagnostic,
            run=run,
            prior_response=response,
        ) is None

    nested = _bounded_field_cleanup_diagnostic(["bounded_choices.ability_scores_by_milestone_id"])
    assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
        nested,
        run=base_run,
        prior_response=base_response,
    ) is None
    mismatched = deepcopy(diagnostic)
    mismatched["code"] = "CG1_PREFERRED_RESPONSE_SHAPE_INVALID"
    assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
        mismatched,
        run=base_run,
        prior_response=base_response,
    ) is None


def test_compact_provider_contract_states_exact_bounded_keys_without_alias_text():
    run = _bounded_field_cleanup_run()
    payload = _provider_payload(run, cue_limit=0, display_limit=0)
    contract = payload["response_contract"]
    expected = [
        "ability_score_changes_by_milestone_id",
        "ability_scores",
        "background_ability",
        "path_progression_by_cl",
    ]
    assert contract["allowed_bounded_choice_keys"] == expected
    assert set(contract["response_template"]["bounded_choices"]) == set(expected)
    assert "ability_scores_by_milestone_id" not in contract["response_template"]["bounded_choices"]
    instructions = " ".join(payload["instructions"])
    assert "only these exact sealed-request keys" in instructions
    assert "never rename keys or invent new ones" in instructions
    assert "aliases such as" not in instructions
    assert "aliases such as" not in contract["bounded_choice_representation"]


def test_compact_provider_payload_fails_closed_for_unsupported_sealed_bounded_key():
    run = _bounded_field_cleanup_run()
    future_key = "future_source_backed_choice"
    run["request"]["bounded_choice_contract"]["fields"][future_key] = {
        "type": "future_authority",
    }

    with pytest.raises(FoundryError) as error:
        _provider_payload(run, cue_limit=0, display_limit=0)

    assert error.value.code == "CG1_PROVIDER_BOUNDED_FIELD_UNSUPPORTED"
    assert error.value.details == {"fields": [future_key]}


def _batched_singleton_path_run() -> dict:
    run = _run()
    run["request"]["delegated_choice_envelope"] = {
        "frozen_owner_target_cl": {"value": 5},
        "allowed_choice_ids_by_slot": {
            "path_choice": [
                "body_refining",
                "qi_cultivation",
                "spirit_awakening",
                "future.path",
            ],
        },
        "path_progression_choices": [
            {"cl": 1, "path_ids": ["body_refining"]},
            {"cl": 2, "path_ids": ["qi_cultivation"]},
            {"cl": 3, "path_ids": ["spirit_awakening"]},
            {"cl": 4, "path_ids": ["body_refining", "qi_cultivation"]},
            {"cl": 5, "path_ids": []},
            {"cl": 99, "path_ids": ["future.path"]},
        ],
    }
    return run


def test_singleton_path_progression_requires_frozen_request_authority():
    run = _run()
    prior_response = _target_scoped_prior_response(run)
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        _singleton_path_diagnostic(),
        run=run,
        prior_response=prior_response,
    )

    assert target is not None
    assert target.get("target_kind") != "bounded_path_progression_singleton"


def test_singleton_path_progression_batches_missing_frozen_singletons_and_preserves_existing():
    run = _batched_singleton_path_run()
    prior_response = _target_scoped_prior_response(run)
    diagnostic = _singleton_path_diagnostic()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )

    assert target is not None
    assert target["target_kind"] == "bounded_path_progression_singleton"
    assert target["reported_cl"] == 1
    assert target["batch_filled_path_progression_by_cl"] == {
        "1": "body_refining",
        "3": "spirit_awakening",
    }
    assert target["batch_available_path_ids_by_cl"] == {
        "1": ["body_refining"],
        "3": ["spirit_awakening"],
    }
    assert "2" not in target["batch_filled_path_progression_by_cl"]
    assert "4" not in target["batch_filled_path_progression_by_cl"]
    assert "5" not in target["batch_filled_path_progression_by_cl"]
    assert "99" not in target["batch_filled_path_progression_by_cl"]
    assert target["response_schema"]["properties"]["bounded_choices"]["properties"][
        "path_progression_by_cl"
    ]["required"] == ["1", "3"]

    corrected_response, merge_evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        canonical_json({
            "bounded_choices": {
                "path_progression_by_cl": {
                    "1": "body_refining",
                    "3": "spirit_awakening",
                },
            },
        }),
        diagnostic,
        run=run,
        repair_target=target,
    )
    corrected = json.loads(corrected_response)
    assert corrected["bounded_choices"]["path_progression_by_cl"] == {
        "1": "body_refining",
        "2": "body_refining",
        "3": "spirit_awakening",
    }
    assert merge_evidence["reported_cl"] == 1
    assert merge_evidence["batch_filled_path_progression_by_cl"] == {
        "1": "body_refining",
        "3": "spirit_awakening",
    }


@pytest.mark.parametrize(
    "mutation",
    ["reported_multiple", "reported_missing", "malformed_allowed_authority", "boolean_cl"],
)
def test_batched_singleton_path_progression_fails_closed_for_unproven_frozen_authority(mutation):
    run = _batched_singleton_path_run()
    diagnostic = _singleton_path_diagnostic()
    if mutation == "reported_multiple":
        run["request"]["delegated_choice_envelope"]["path_progression_choices"][0]["path_ids"] = [
            "body_refining",
            "qi_cultivation",
        ]
    elif mutation == "reported_missing":
        run["request"]["delegated_choice_envelope"]["path_progression_choices"] = [
            row
            for row in run["request"]["delegated_choice_envelope"]["path_progression_choices"]
            if row["cl"] != 1
        ]
    elif mutation == "malformed_allowed_authority":
        run["request"]["delegated_choice_envelope"]["allowed_choice_ids_by_slot"]["path_choice"] = [
            "body_refining",
            "body_refining",
        ]
    else:
        diagnostic["details"]["cl"] = True

    prior_response = _target_scoped_prior_response(run)
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    if mutation == "boolean_cl":
        assert target is None
        return
    assert target is not None
    assert target.get("target_kind") != "bounded_path_progression_singleton"


def _empty_path_progression_cleanup_response(
    run: dict,
    *,
    progression: dict[str, object] | None = None,
) -> str:
    payload = json.loads(_target_scoped_prior_response(run))
    payload["bounded_choices"]["path_progression_by_cl"] = progression or {
        "1": "body_refining",
        "2": "body_refining",
        **{str(cl): [] for cl in range(3, 11)},
    }
    return canonical_json(payload)


_EMPTY_PATH_REQUESTED_PATH_UNSET = object()


def _empty_path_progression_cleanup_diagnostic(
    *,
    cl: object = 3,
    requested_path: object = _EMPTY_PATH_REQUESTED_PATH_UNSET,
    available_path_ids: list[str] | None = None,
) -> dict:
    details = {
        "cl": cl,
        "requested_path": (
            []
            if requested_path is _EMPTY_PATH_REQUESTED_PATH_UNSET
            else requested_path
        ),
    }
    if available_path_ids is not None:
        details["available_path_ids"] = available_path_ids
    return {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_BOUNDED_DECISION_REQUIRED",
        "message": "The retained Path progression placeholder is empty.",
        "details": details,
    }


def test_empty_path_progression_cleanup_removes_all_placeholders_without_selecting_path():
    run = _run()
    prior_response = _empty_path_progression_cleanup_response(run)
    diagnostic = _empty_path_progression_cleanup_diagnostic(
        available_path_ids=["body_refining", "qi_cultivation"],
    )

    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )

    assert target is not None
    assert target["target_kind"] == "bounded_path_progression_empty_cleanup"
    assert target["reported_cl"] == 3
    assert target["removed_cl_keys"] == [str(cl) for cl in range(3, 11)]
    assert "available_path_ids" not in target

    applied_response, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        "",
        diagnostic,
        run=run,
        repair_target=target,
    )
    prior = json.loads(prior_response)
    applied = json.loads(applied_response)
    assert applied["bounded_choices"]["path_progression_by_cl"] == {
        "1": "body_refining",
        "2": "body_refining",
    }
    prior["bounded_choices"].pop("path_progression_by_cl")
    applied["bounded_choices"].pop("path_progression_by_cl")
    assert applied == prior
    assert evidence["deterministic_server_repair"] is True
    assert evidence["provider_called"] is False
    assert evidence["reported_cl"] == 3
    assert evidence["removed_cl_keys"] == [str(cl) for cl in range(3, 11)]
    assert "selected_path_id" not in evidence
    assert evidence["raw_provider_completion_sha256"] is None
    assert evidence["provider_completion_sha256"] is None
    assert evidence["provider_response_sha256"] is None


def test_empty_path_progression_cleanup_initial_flow_is_one_call_and_provider_free(monkeypatch):
    run = _run()
    prior_response = _empty_path_progression_cleanup_response(run)
    diagnostic = _empty_path_progression_cleanup_diagnostic()
    first = _blocked_result(
        run,
        prior_response,
        provider_id="local",
        diagnostic_code=diagnostic["code"],
    )
    first["validation"]["last_submission_error"] = deepcopy(diagnostic)
    cleaned_response, _ = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        "",
        diagnostic,
        run=run,
    )
    second = {
        **_blocked_result(
            run,
            cleaned_response,
            provider_id="local",
            diagnostic_code=diagnostic["code"],
        ),
        "status": "READY_FOR_REVIEW",
    }
    second["validation"]["last_submission_error"] = deepcopy(diagnostic)
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(prior_response, provider_id="local")],
        [first, second],
    )

    result = service._run_provider(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 2
    assert json.loads(apply_calls[1]["response_text"])["bounded_choices"][
        "path_progression_by_cl"
    ] == {"1": "body_refining", "2": "body_refining"}
    correction_transport = apply_calls[1]["transport"]
    correction = correction_transport["local_correction"]
    assert correction_transport["provider_called"] is False
    assert type(correction_transport["automatic_retries"]) is int
    assert correction_transport["automatic_retries"] == 0
    assert type(correction["automatic_retries"]) is int
    assert correction["automatic_retries"] == 0
    assert correction["target_kind"] == "bounded_path_progression_empty_cleanup"
    assert correction["deterministic_server_repair"] is True
    assert correction["provider_called"] is False
    assert correction["reported_cl"] == 3
    assert correction["removed_cl_keys"] == [str(cl) for cl in range(3, 11)]
    assert correction["raw_provider_completion_sha256"] is None
    assert correction["raw_provider_response_sha256"] is None
    assert correction["provider_completion_sha256"] is None
    assert correction["provider_response_sha256"] is None


def test_explicit_empty_path_progression_cleanup_is_provider_free_and_zero_retry(monkeypatch):
    run = _explicit_review_run(diagnostic_code="CG1_BOUNDED_DECISION_REQUIRED")
    prior_response = _empty_path_progression_cleanup_response(run)
    diagnostic = _empty_path_progression_cleanup_diagnostic()
    run["response"] = {
        "exact_response_text": prior_response,
        "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
    }
    run["validation"]["last_submission_error"] = deepcopy(diagnostic)
    corrected = {**run, "status": "READY_FOR_REVIEW"}
    service, apply_calls = _service(monkeypatch, run, [], [corrected])

    result = service.retry_local_ai_correction(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert service.provider.calls == []
    assert len(apply_calls) == 1
    correction_transport = apply_calls[0]["transport"]
    correction = correction_transport["local_correction"]
    assert correction_transport["provider_called"] is False
    assert type(correction_transport["automatic_retries"]) is int
    assert correction_transport["automatic_retries"] == 0
    assert type(correction["automatic_retries"]) is int
    assert correction["automatic_retries"] == 0
    assert correction["target_kind"] == "bounded_path_progression_empty_cleanup"
    assert correction["deterministic_server_repair"] is True
    assert correction["provider_called"] is False
    assert correction["raw_provider_completion_sha256"] is None
    assert correction["raw_provider_response_sha256"] is None
    assert correction["provider_completion_sha256"] is None
    assert correction["provider_response_sha256"] is None


def test_retry_local_build_applies_empty_path_progression_cleanup_without_provider(monkeypatch):
    run = _run()
    prior_response = _empty_path_progression_cleanup_response(run)
    diagnostic = _empty_path_progression_cleanup_diagnostic()
    run.update({
        "status": "NEEDS_REVIEW",
        "response": {
            "exact_response_text": prior_response,
            "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
        },
        "validation": {"last_submission_error": deepcopy(diagnostic)},
        "transport": {"provider_id": "local", "automatic_retries": 7},
        "attempt_history": [{"attempt_id": "cg1.attempt.first", "status": "BLOCKED"}],
    })
    cleaned_response, _ = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        "",
        diagnostic,
        run=run,
    )
    retained_result = {
        **_blocked_result(
            run,
            cleaned_response,
            provider_id="local",
            diagnostic_code=diagnostic["code"],
        ),
        "status": "READY_FOR_REVIEW",
    }
    service, apply_calls = _service(monkeypatch, run, [], [retained_result])

    result = service.retry_local_build(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert service.provider.calls == []
    assert len(apply_calls) == 1
    assert json.loads(apply_calls[0]["response_text"])["bounded_choices"][
        "path_progression_by_cl"
    ] == {"1": "body_refining", "2": "body_refining"}
    correction_transport = apply_calls[0]["transport"]
    correction = correction_transport["local_correction"]
    assert correction["target_kind"] == "bounded_path_progression_empty_cleanup"
    assert correction_transport["provider_called"] is False
    assert correction["provider_called"] is False
    assert type(correction_transport["automatic_retries"]) is int
    assert correction_transport["automatic_retries"] == 0
    assert type(correction["automatic_retries"]) is int
    assert correction["automatic_retries"] == 0
    assert correction["reported_cl"] == 3
    assert correction["removed_cl_keys"] == [str(cl) for cl in range(3, 11)]
    assert correction["raw_provider_completion_sha256"] is None
    assert correction["raw_provider_response_sha256"] is None
    assert correction["provider_completion_sha256"] is None
    assert correction["provider_response_sha256"] is None


@pytest.mark.parametrize(
    "mutation",
    ["requested_path_none", "requested_path_string", "requested_path_object", "requested_path_nonempty", "boolean_cl"],
)
def test_empty_path_progression_cleanup_rejects_malformed_diagnostic(mutation):
    run = _run()
    prior_response = _empty_path_progression_cleanup_response(run)
    if mutation == "requested_path_none":
        requested_path = None
    elif mutation == "requested_path_string":
        requested_path = ""
    elif mutation == "requested_path_object":
        requested_path = {}
    elif mutation == "requested_path_nonempty":
        requested_path = ["body_refining"]
    else:
        requested_path = []
    diagnostic = _empty_path_progression_cleanup_diagnostic(
        cl=True if mutation == "boolean_cl" else 3,
        requested_path=requested_path,
    )
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )

    assert target is None


@pytest.mark.parametrize("current_value", [{}, None, "body_refining", ["body_refining"]])
def test_empty_path_progression_cleanup_rejects_nonempty_or_malformed_current_value(current_value):
    run = _run()
    prior_response = _empty_path_progression_cleanup_response(
        run,
        progression={
            "1": "body_refining",
            "2": "body_refining",
            "3": current_value,
            "4": [],
        },
    )
    diagnostic = _empty_path_progression_cleanup_diagnostic()

    assert CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    ) is None


def _advancement_choice_run(*, insight: bool = False) -> tuple[dict, str, dict]:
    milestone_id = "path.body.feature.ability_score_improvement_or_cultivation_insight.cl4"
    field = f"bounded_choices.ability_score_changes_by_milestone_id.{milestone_id}"
    allowed_kinds = (
        ["cultivation_insight_acquisition"]
        if insight
        else ["ability_score_change"]
    )
    envelope = {
        "frozen_owner_target_cl": {"value": 4},
        "owner_locks": {"by_slot": {"path_choice": ["path.body"]}},
        "allowed_choice_ids_by_slot": {"path_choice": ["path.body"]},
        "choices_by_slot": {},
        "typed_choice_authority_by_slot": {},
        "advancement_choice_milestones": [{
            "milestone_id": milestone_id,
            "path_id": "path.body",
            "feature_record_id": "feature.asi-or-insight",
            "cl": 4,
            "allowed_kinds": allowed_kinds,
        }],
        "path_progression_choices": [{"cl": 4, "path_ids": ["path.body"]}],
    }
    run = _run()
    run["request"]["delegated_choice_envelope"] = envelope
    run["owner_decision_authority"] = {
        milestone_id: {
            "allowed_kinds": allowed_kinds,
            "ability_change": {
                "allowed_cls": [4],
                "allowed_deltas": [2],
                "allowed_abilities": ["CON"],
                "budget": 2,
                "cap": 20,
            },
        },
    }
    if insight:
        insight_id = "insight.inner-flame"
        envelope["allowed_choice_ids_by_slot"]["insight_priorities"] = [insight_id]
        envelope["choices_by_slot"]["insight_priorities"] = {
            insight_id: {
                "choice_id": insight_id,
                "name": "Inner Flame",
                "description": "A focused inner cultivation gain.",
            },
        }
        envelope["typed_choice_authority_by_slot"]["insight_priorities"] = {
            "stage2_authority_by_choice": {
                insight_id: {
                    "allowed_cls": [4],
                    "repeatability": {"mode": "nonrepeatable", "maximum": 1},
                    "ability_change": {
                        "allowed_abilities": ["WIS"],
                        "amount": 1,
                        "cap": 20,
                    },
                },
            },
        }
        envelope["prerequisites_and_availability"] = {
            "insight_priorities": {
                insight_id: {
                    "availability": {"minimum_cl": 1},
                    "prerequisites": [],
                    "incompatibilities": [],
                },
            },
        }
    prior_response = canonical_json({
        "schema": DELEGATED_RESPONSE_SCHEMA,
        "request_sha256": run["request"]["request_sha256"],
        "selection_intent": {"by_slot": {"path_choice": ["path.body"]}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": [],
            "insight_occurrences": [{
                "milestone_id": "other.milestone",
                "insight_id": "insight.other",
                "parameters": {"ability": "DEX"},
            }],
        },
        "bounded_choices": {
            "ability_scores": {
                "STR": 10,
                "DEX": 10,
                "CON": 10,
                "INT": 10,
                "WIS": 10,
                "CHA": 10,
            },
            "ability_score_changes_by_milestone_id": {
                "other.milestone": {"deltas": {"DEX": 1}},
            },
            "path_progression_by_cl": {"4": "path.body"},
        },
        "owner_descriptive_fields": {
            "identity": {"name": "Scratch"},
            "concept": "A patient body cultivator.",
        },
        "unrelated_retained_field": {
            "ordered": ["must", "remain"],
            "nested": {"byte_stable": True},
        },
    })
    diagnostic = {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_BOUNDED_DECISION_REQUIRED",
        "message": "Resolve the missing Advancement Choice.",
        "details": {
            "field": field,
            "milestone_id": milestone_id,
            "effective_cl": 4,
            "allowed_resolutions": [
                "ability_score_change",
                "cultivation_insight_acquisition",
            ],
        },
    }
    return run, prior_response, diagnostic


@pytest.mark.parametrize("insight", [False, True])
def test_advancement_choice_target_is_compact_opaque_and_hash_bound(insight):
    run, prior_response, diagnostic = _advancement_choice_run(insight=insight)
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )

    assert target is not None
    assert target["target_kind"] == "advancement_choice"
    assert target["field"] == diagnostic["details"]["field"]
    assert target["milestone_id"] == diagnostic["details"]["milestone_id"]
    assert target["request_sha256"] == run["request"]["request_sha256"]
    assert target["prior_response_sha256"] == sha256_bytes(prior_response.encode("utf-8"))
    assert target["option_ids"]
    assert all(option_id.startswith("adv_") for option_id in target["option_ids"])
    assert all(
        target["options"][option_id]["value"]["milestone_id"] == target["milestone_id"]
        for option_id in target["option_ids"]
    )

    prompt = CharacterCreationExecutionService._provider_correction_prompt(
        run,
        prior_response,
        diagnostic,
        prior_response_sha256=target["prior_response_sha256"],
        repair_target=target,
    )
    prompt_payload = json.loads(prompt)
    assert len(prompt.encode("utf-8")) < 10_000
    assert prior_response not in prompt
    assert "prior_response_text" not in prompt_payload
    assert "options" not in prompt_payload["correction_contract"]
    assert prompt_payload["correction_contract"]["minimal_response_shape"] == {
        "option_id": "one opaque ID from option_ids",
    }
    assert prompt_payload["authority"]["automatic_retries"] == 0
    if insight:
        assert "insight.inner-flame" not in prompt


@pytest.mark.parametrize("insight", [False, True])
def test_advancement_choice_merge_changes_only_the_target_milestone(insight):
    run, prior_response, diagnostic = _advancement_choice_run(insight=insight)
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    provider_response = canonical_json({"option_id": target["option_ids"][0]})

    merged_response, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        provider_response,
        diagnostic,
        run=run,
        repair_target=target,
    )
    before = json.loads(prior_response)
    after = json.loads(merged_response)
    target_milestone = target["milestone_id"]
    before_bounded = before.pop("bounded_choices")
    after_bounded = after.pop("bounded_choices")
    before_acquisition = before.pop("acquisition_intent")
    after_acquisition = after.pop("acquisition_intent")
    assert after == before
    bounded_siblings_before = {
        key: value
        for key, value in before_bounded.items()
        if key != "ability_score_changes_by_milestone_id"
    }
    bounded_siblings_after = {
        key: value
        for key, value in after_bounded.items()
        if key != "ability_score_changes_by_milestone_id"
    }
    assert bounded_siblings_after == bounded_siblings_before
    acquisition_siblings_before = {
        key: value
        for key, value in before_acquisition.items()
        if key != "insight_occurrences"
    }
    acquisition_siblings_after = {
        key: value
        for key, value in after_acquisition.items()
        if key != "insight_occurrences"
    }
    assert acquisition_siblings_after == acquisition_siblings_before
    before_ability_changes = before_bounded["ability_score_changes_by_milestone_id"]
    after_ability_changes = after_bounded["ability_score_changes_by_milestone_id"]
    assert {
        key: value
        for key, value in after_ability_changes.items()
        if key != target_milestone
    } == {
        key: value
        for key, value in before_ability_changes.items()
        if key != target_milestone
    }
    before_insight_occurrences = before_acquisition["insight_occurrences"]
    after_insight_occurrences = after_acquisition["insight_occurrences"]
    assert [
        occurrence
        for occurrence in after_insight_occurrences
        if isinstance(occurrence, dict) and occurrence.get("milestone_id") != target_milestone
    ] == [
        occurrence
        for occurrence in before_insight_occurrences
        if isinstance(occurrence, dict) and occurrence.get("milestone_id") != target_milestone
    ]
    if insight:
        assert after_bounded["ability_score_changes_by_milestone_id"] == {
            "other.milestone": {"deltas": {"DEX": 1}},
        }
        assert after_acquisition["insight_occurrences"] == [{
            "milestone_id": "other.milestone",
            "insight_id": "insight.other",
            "parameters": {"ability": "DEX"},
        }, {
            "milestone_id": target_milestone,
            "insight_id": "insight.inner-flame",
            "parameters": {"ability": "WIS"},
        }]
    else:
        assert after_bounded["ability_score_changes_by_milestone_id"] == {
            "other.milestone": {"deltas": {"DEX": 1}},
            target_milestone: {"deltas": {"CON": 2}},
        }
        assert after_acquisition == before_acquisition
    assert evidence["selected_option_id"] == target["option_ids"][0]
    assert evidence["selected_kind"] == target["options"][target["option_ids"][0]]["kind"]


def test_explicit_advancement_choice_correction_uses_one_compact_call_and_zero_retries(monkeypatch):
    run, prior_response, diagnostic = _advancement_choice_run()
    run.update({
        "status": "NEEDS_REVIEW",
        "response": {
            "exact_response_text": prior_response,
            "response_sha256": sha256_bytes(prior_response.encode("utf-8")),
        },
        "validation": {"last_submission_error": deepcopy(diagnostic)},
        "transport": {
            "provider_id": "local",
            "provider_called": True,
            "automatic_retries": 0,
        },
        "final_plan": {},
        "final_revision": None,
        "commit": {},
        "canonical_intent_hash": None,
        "materialized_plan_sha256": None,
        "attempt_history": [{"attempt_id": "cg1.attempt.first", "status": "BLOCKED"}],
    })
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    correction = canonical_json({"option_id": target["option_ids"][0]})
    corrected_result = {
        **_blocked_result(run, correction, provider_id="local", diagnostic_code=diagnostic["code"]),
        "status": "READY_FOR_REVIEW",
    }
    service, apply_calls = _service(
        monkeypatch,
        run,
        [_receipt(correction, provider_id="local")],
        [corrected_result],
    )
    result = service.retry_local_ai_correction(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert len(service.provider.calls) == 1
    assert len(apply_calls) == 1
    call = service.provider.calls[0]
    prompt_payload = json.loads(call["prompt_text"])
    assert call["response_schema"] == target["response_schema"]
    assert prompt_payload["authority"]["automatic_retries"] == 0
    assert apply_calls[0]["transport"]["automatic_retries"] == 0
    assert json.loads(apply_calls[0]["response_text"])["bounded_choices"][
        "ability_score_changes_by_milestone_id"
    ][target["milestone_id"]] == {"deltas": {"CON": 2}}


@pytest.mark.parametrize("mutation", [
    "unknown_option",
    "extra_field",
    "duplicate_option_key",
    "request_hash",
    "prior_hash",
    "server_option",
    "option_summary",
    "stale_diagnostic",
])
def test_advancement_choice_merge_fails_closed_for_malformed_or_stale_lineage(mutation):
    run, prior_response, diagnostic = _advancement_choice_run()
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    option_id = target["option_ids"][0]
    provider_response = canonical_json({"option_id": option_id})
    mutated_target = deepcopy(target)
    if mutation == "unknown_option":
        provider_response = canonical_json({"option_id": "adv_unknown"})
    elif mutation == "extra_field":
        provider_response = canonical_json({"option_id": option_id, "extra": True})
    elif mutation == "duplicate_option_key":
        provider_response = '{"option_id":"' + option_id + '","option_id":"' + option_id + '"}'
    elif mutation == "request_hash":
        mutated_target["request_sha256"] = "f" * 64
    elif mutation == "prior_hash":
        mutated_target["prior_response_sha256"] = "f" * 64
    elif mutation == "server_option":
        mutated_target["options"][option_id]["milestone_id"] = "other.milestone"
    elif mutation == "option_summary":
        mutated_target["option_summaries"][0]["display_name"] = "forged"
    else:
        diagnostic = deepcopy(diagnostic)
        diagnostic["details"]["milestone_id"] = "other.milestone"

    with pytest.raises(FoundryError) as rejected:
        CharacterCreationExecutionService._merge_target_scoped_correction_response(
            prior_response,
            provider_response,
            diagnostic,
            run=run,
            repair_target=mutated_target,
        )
    assert rejected.value.code == "CG1_LOCAL_CORRECTION_TARGET_INVALID"


def _schema_recovery_run(*, original_code: str = "CG1_BOUNDED_DECISION_REQUIRED") -> tuple[dict, str, str, str]:
    run = _run()
    prior_response = canonical_json({
        "schema": DELEGATED_RESPONSE_SCHEMA,
        "request_sha256": run["request"]["request_sha256"],
        "retained": {"exact": True},
    })
    malformed_response = canonical_json({
        "schema": "TianxiaFoundry.LocalProviderCorrection.v1",
        "request_sha256": run["request"]["request_sha256"],
        "response": {"not": "a complete plan"},
    })
    request_sha256 = run["request"]["request_sha256"]
    prior_attempt_id = "cg1.attempt.five"
    latest_attempt_id = "cg1.attempt.six"
    prior_response_sha256 = sha256_bytes(prior_response.encode("utf-8"))
    malformed_sha256 = sha256_bytes(malformed_response.encode("utf-8"))
    original_diagnostic = {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": original_code,
        "message": "The original retained response had one bounded blocker.",
        "details": {"milestone_id": "m.cl4"},
    }
    run.update({
        "status": "NEEDS_REVIEW",
        "response": {
            "exact_response_text": malformed_response,
            "response_sha256": malformed_sha256,
        },
        "validation": {
            "last_submission_error": {
                "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
                "code": "CG1_PLAN_SCHEMA_INVALID",
                "message": "The correction response was not a complete plan.",
            },
        },
        "transport": {
            "mode": run["execution_mode"],
            "provider_called": True,
            "provider_id": "local",
            "automatic_retries": 1,
            "complete_request_sha256": request_sha256,
        },
        "attempt_history": [
            {
                "attempt_id": prior_attempt_id,
                "run_id": run["run_id"],
                "project_id": run["project_id"],
                "request_sha256": request_sha256,
                "response_sha256": prior_response_sha256,
                "response_text": prior_response,
                "action_type": "RETRY_LOCAL_BUILD",
                "status": "BLOCKED",
            },
            {
                "attempt_id": latest_attempt_id,
                "run_id": run["run_id"],
                "project_id": run["project_id"],
                "request_sha256": request_sha256,
                "response_sha256": malformed_sha256,
                "response_text": malformed_response,
                "action_type": "LOCAL_PROVIDER_CORRECTION",
                "status": "BLOCKED",
                "prior_attempt_id": prior_attempt_id,
                "binding": {
                    "submitted_request_sha256": None,
                    "active_request_sha256": request_sha256,
                    "transport": {
                        "mode": run["execution_mode"],
                        "provider_called": True,
                        "provider_id": "local",
                        "complete_request_sha256": request_sha256,
                        "local_correction": {
                            "attempted": True,
                            "explicit": True,
                            "status": "RETAINED_FOR_VALIDATION",
                            "provider_id": "local",
                            "prior_attempt_id": prior_attempt_id,
                            "prior_response_sha256": prior_response_sha256,
                            "validator_diagnostic": original_diagnostic,
                        },
                    },
                },
                "validation": {
                    "last_submission_error": {
                        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
                        "code": "CG1_PLAN_SCHEMA_INVALID",
                    },
                },
            },
        ],
    })
    return run, prior_response, prior_attempt_id, latest_attempt_id


def _schema_recovery_stale_advancement_echo_context() -> tuple[dict, str]:
    """Build a recovery leaf over the retained ordinary-repair proof chain."""
    run, recovered_response, diagnostic, _target = _ordinary_duplicate_repaired_response_context()
    history = deepcopy(run["attempt_history"])
    stale_ids = _ordinary_duplicate_oversized_ids()

    def stale_echo(response: str) -> str:
        payload = json.loads(response)
        payload["advancement_skeleton"] = deepcopy(stale_ids)
        return canonical_json(payload)

    ordinary_response = stale_echo(history[1]["response_text"])
    ordinary_hash = sha256_bytes(ordinary_response.encode("utf-8"))
    history[1]["response_text"] = ordinary_response
    history[1]["response_sha256"] = ordinary_hash
    history[1]["binding"]["transport"]["local_correction"]["applied_response_sha256"] = ordinary_hash

    bounded_response = stale_echo(history[2]["response_text"])
    bounded_hash = sha256_bytes(bounded_response.encode("utf-8"))
    history[2]["response_text"] = bounded_response
    history[2]["response_sha256"] = bounded_hash
    bounded_marker = history[2]["binding"]["transport"]["local_correction"]
    bounded_marker["prior_response_sha256"] = ordinary_hash
    bounded_marker["applied_response_sha256"] = bounded_hash

    history[3]["response_text"] = bounded_response
    history[3]["response_sha256"] = bounded_hash
    recovered_response = bounded_response
    recovered_hash = bounded_hash
    request_sha256 = run["request"]["request_sha256"]
    malformed_response = canonical_json({
        "schema": "TianxiaFoundry.LocalProviderCorrection.v1",
        "request_sha256": request_sha256,
        "response": {"not": "a complete plan"},
    })
    malformed_hash = sha256_bytes(malformed_response.encode("utf-8"))
    retry_attempt_id = history[3]["attempt_id"]
    latest_attempt_id = "cg1.attempt.recovery-leaf"
    latest_diagnostic = {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_PLAN_SCHEMA_INVALID",
        "message": "The correction response was not a complete plan.",
        "details": {},
    }
    latest_transport = {
        "mode": run["execution_mode"],
        "provider_called": True,
        "provider_id": "local",
        "automatic_retries": 0,
        "transfer": "retry_local_build",
        "submitted_request_sha256": request_sha256,
        "prior_attempt_id": retry_attempt_id,
        "complete_request_sha256": request_sha256,
        "purpose": "character_creation_local_correction",
        "local_correction": {
            "attempted": True,
            "explicit": True,
            "status": "FAILED",
            "provider_id": "local",
            "provider_called": True,
            "prior_attempt_id": retry_attempt_id,
            "prior_response_sha256": recovered_hash,
            "validator_diagnostic": deepcopy(diagnostic),
        },
    }
    history.append({
        "attempt_id": latest_attempt_id,
        "run_id": run["run_id"],
        "project_id": run["project_id"],
        "ordinal": 6,
        "action_type": "LOCAL_PROVIDER_CORRECTION",
        "status": "BLOCKED",
        "request_sha256": request_sha256,
        "response_sha256": malformed_hash,
        "response_text": malformed_response,
        "prior_attempt_id": retry_attempt_id,
        "binding": {
            "submitted_request_sha256": request_sha256,
            "active_request_sha256": request_sha256,
            "transport": latest_transport,
        },
        "error": latest_diagnostic,
    })
    run["attempt_history"] = history
    run["response"] = {
        "exact_response_text": malformed_response,
        "response_sha256": malformed_hash,
    }
    run["validation"] = {"last_submission_error": latest_diagnostic}
    run["status"] = "NEEDS_REVIEW"
    run["transport"] = {
        "mode": run["execution_mode"],
        "provider_called": False,
        "automatic_retries": 0,
        "transfer": "retry_local_build",
        "submitted_request_sha256": request_sha256,
        "prior_attempt_id": latest_attempt_id,
        "provider_id": "local",
        "local_recovery": {
            "schema": "TianxiaFoundry.LocalProviderRecoveryReceipt.v1",
            "provider_called": False,
            "automatic_retries": 0,
            "recovered_from_attempt_id": latest_attempt_id,
            "restored_attempt_id": retry_attempt_id,
            "request_sha256": request_sha256,
            "prior_response_sha256": recovered_hash,
            "original_diagnostic": deepcopy(diagnostic),
        },
    }
    return run, recovered_response


def _append_persisted_recovery_attempt(run: dict, response_text: str) -> None:
    request_sha256 = run["request"]["request_sha256"]
    recovery_transport = deepcopy(run["transport"])
    recovery_attempt_id = run["attempt_history"][-1]["attempt_id"]
    recovery_transport["prior_attempt_id"] = recovery_attempt_id
    recovery_diagnostic = {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_PREFERRED_RESPONSE_SHAPE_INVALID",
        "message": "A stale top-level advancement echo is not a canonical mirror.",
        "details": {"field": "advancement_skeleton", "canonical_mirror": False},
    }
    run["attempt_history"].append({
        "attempt_id": "cg1.attempt.recovery-replay",
        "run_id": run["run_id"],
        "project_id": run["project_id"],
        "ordinal": 7,
        "action_type": "RETRY_LOCAL_BUILD",
        "status": "BLOCKED",
        "request_sha256": request_sha256,
        "response_sha256": sha256_bytes(response_text.encode("utf-8")),
        "response_text": response_text,
        "prior_attempt_id": recovery_attempt_id,
        "binding": {
            "submitted_request_sha256": request_sha256,
            "active_request_sha256": request_sha256,
            "transport": recovery_transport,
        },
        "error": recovery_diagnostic,
    })
    run["response"] = {
        "exact_response_text": response_text,
        "response_sha256": sha256_bytes(response_text.encode("utf-8")),
    }
    run["validation"] = {"last_submission_error": recovery_diagnostic}


def _append_ordinary_recovery_retry(
    run: dict,
    response_text: str,
    *,
    attempt_id: str,
    ordinal: int,
) -> None:
    request_sha256 = run["request"]["request_sha256"]
    prior_attempt_id = run["attempt_history"][-1]["attempt_id"]
    retry_transport = {
        "mode": run["execution_mode"],
        "provider_called": False,
        "automatic_retries": 0,
        "transfer": "retry_local_build",
        "submitted_request_sha256": request_sha256,
        "prior_attempt_id": prior_attempt_id,
    }
    run["attempt_history"].append({
        "attempt_id": attempt_id,
        "run_id": run["run_id"],
        "project_id": run["project_id"],
        "ordinal": ordinal,
        "action_type": "RETRY_LOCAL_BUILD",
        "status": "BLOCKED",
        "request_sha256": request_sha256,
        "response_sha256": sha256_bytes(response_text.encode("utf-8")),
        "response_text": response_text,
        "prior_attempt_id": prior_attempt_id,
        "binding": {
            "submitted_request_sha256": request_sha256,
            "active_request_sha256": request_sha256,
            "transport": retry_transport,
        },
        "error": deepcopy(run["validation"]["last_submission_error"]),
    })
    run["transport"] = retry_transport
    run["response"] = {
        "exact_response_text": response_text,
        "response_sha256": sha256_bytes(response_text.encode("utf-8")),
    }


def _append_persisted_advancement_choice_attempt_ten(run: dict) -> tuple[str, dict]:
    """Append the real recovery-suffix shape followed by attempt-10 choice merge."""
    choice_run, _prior_choice_response, choice_diagnostic = _advancement_choice_run()
    envelope = run["request"]["delegated_choice_envelope"]
    choice_envelope = choice_run["request"]["delegated_choice_envelope"]
    for key in ("advancement_choice_milestones", "path_progression_choices"):
        envelope[key] = deepcopy(choice_envelope[key])
    run["owner_decision_authority"] = deepcopy(choice_run["owner_decision_authority"])

    # The recovered ordinary response retains the stale top-level echo, while
    # the Advancement Choice containers are present and still unresolved.
    for row in run["attempt_history"][:4]:
        payload = json.loads(row["response_text"])
        payload.setdefault("bounded_choices", {})[
            "ability_score_changes_by_milestone_id"
        ] = {}
        payload.setdefault("acquisition_intent", {})["insight_occurrences"] = []
        response_text = canonical_json(payload)
        row["response_text"] = response_text
        row["response_sha256"] = sha256_bytes(response_text.encode("utf-8"))
    for index, row in enumerate(run["attempt_history"][:4]):
        marker = (
            row.get("binding", {}).get("transport", {}).get("local_correction")
            if isinstance(row.get("binding"), dict)
            else None
        )
        if isinstance(marker, dict):
            marker["applied_response_sha256"] = row["response_sha256"]
            if index:
                marker["prior_response_sha256"] = run["attempt_history"][index - 1]["response_sha256"]
    recovered_response = run["attempt_history"][3]["response_text"]
    recovered_hash = run["attempt_history"][3]["response_sha256"]
    malformed_row = run["attempt_history"][4]
    malformed_row["binding"]["transport"]["local_correction"]["prior_response_sha256"] = recovered_hash
    run["transport"]["local_recovery"]["prior_response_sha256"] = recovered_hash

    _append_persisted_recovery_attempt(run, recovered_response)
    _append_ordinary_recovery_retry(
        run,
        recovered_response,
        attempt_id="cg1.attempt.recovery-retry-eight",
        ordinal=8,
    )
    _append_ordinary_recovery_retry(
        run,
        recovered_response,
        attempt_id="cg1.attempt.recovery-retry-nine",
        ordinal=9,
    )

    prior_response = run["attempt_history"][-1]["response_text"]
    prior_hash = run["attempt_history"][-1]["response_sha256"]
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        choice_diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    provider_response = canonical_json({"option_id": target["option_ids"][0]})
    provider_completion_sha256 = sha256_bytes(provider_response.encode("utf-8"))
    provider_response_sha256 = "b" * 64
    applied_response, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        provider_response,
        choice_diagnostic,
        run=run,
        repair_target=target,
        provider_completion_sha256=provider_completion_sha256,
        provider_response_sha256=provider_response_sha256,
    )
    request_sha256 = run["request"]["request_sha256"]
    marker = {
        **evidence,
        "attempted": True,
        "explicit": True,
        "status": "RETAINED_FOR_VALIDATION",
        "provider_id": "local",
        "prior_attempt_id": run["attempt_history"][-1]["attempt_id"],
        "prior_response_sha256": prior_hash,
        "validator_diagnostic": deepcopy(choice_diagnostic),
    }
    correction_transport = {
        "mode": run["execution_mode"],
        "provider_called": True,
        "provider_id": "local",
        "automatic_retries": 0,
        "complete_request_sha256": request_sha256,
        "prior_attempt_id": run["attempt_history"][-1]["attempt_id"],
        "provider_completion_sha256": provider_completion_sha256,
        "provider_response_sha256": provider_response_sha256,
        "local_correction": marker,
    }
    applied_hash = sha256_bytes(applied_response.encode("utf-8"))
    run["attempt_history"].append({
        "attempt_id": "cg1.attempt.local-provider-correction-ten",
        "run_id": run["run_id"],
        "project_id": run["project_id"],
        "ordinal": 10,
        "action_type": "LOCAL_PROVIDER_CORRECTION",
        "status": "BLOCKED",
        "request_sha256": request_sha256,
        "response_sha256": applied_hash,
        "response_text": applied_response,
        "prior_attempt_id": run["attempt_history"][-1]["attempt_id"],
        "binding": {
            "submitted_request_sha256": None,
            "active_request_sha256": request_sha256,
            "transport": correction_transport,
        },
        "error": {
            "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
            "code": "CG1_PREFERRED_RESPONSE_SHAPE_INVALID",
            "message": "A stale top-level advancement echo is not a canonical mirror.",
            "details": {"field": "advancement_skeleton", "canonical_mirror": False},
        },
    })
    run["transport"] = deepcopy(correction_transport)
    run["response"] = {
        "exact_response_text": applied_response,
        "response_sha256": applied_hash,
    }
    run["validation"] = {"last_submission_error": deepcopy(run["attempt_history"][-1]["error"])}
    run["status"] = "NEEDS_REVIEW"
    _append_ordinary_recovery_retry(
        run,
        applied_response,
        attempt_id="cg1.attempt.recovery-retry-eleven",
        ordinal=11,
    )
    return applied_response, target


def _append_persisted_advancement_choice_attempt_twelve(run: dict) -> str:
    """Model the production attempt-10 node followed by exact retries 11/12."""
    applied_response, _target = _append_persisted_advancement_choice_attempt_ten(run)
    _append_ordinary_recovery_retry(
        run,
        applied_response,
        attempt_id="cg1.attempt.recovery-retry-twelve",
        ordinal=12,
    )
    return applied_response


def _append_persisted_advancement_choice_attempt_fifteen(run: dict) -> tuple[str, dict, str, str]:
    """Model CL4 and CL8 target-only provider corrections with exact retries."""
    applied_response = _append_persisted_advancement_choice_attempt_twelve(run)
    _append_ordinary_recovery_retry(
        run,
        applied_response,
        attempt_id="cg1.attempt.recovery-retry-thirteen",
        ordinal=13,
    )

    envelope = run["request"]["delegated_choice_envelope"]
    cl4_row = deepcopy(envelope["advancement_choice_milestones"][0])
    cl4_milestone_id = cl4_row["milestone_id"]
    cl8_milestone_id = cl4_milestone_id.rsplit(".cl4", 1)[0] + ".cl8"
    cl8_row = deepcopy(cl4_row)
    cl8_row.update({"milestone_id": cl8_milestone_id, "cl": 8})
    envelope["advancement_choice_milestones"].append(cl8_row)
    envelope["path_progression_choices"].append({"cl": 8, "path_ids": ["path.body"]})

    cl8_authority = deepcopy(run["owner_decision_authority"][cl4_milestone_id])
    cl8_authority["ability_change"]["allowed_cls"] = [8]
    run["owner_decision_authority"][cl8_milestone_id] = cl8_authority
    cl8_diagnostic = {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_BOUNDED_DECISION_REQUIRED",
        "message": "Resolve the missing Advancement Choice.",
        "details": {
            "field": f"bounded_choices.ability_score_changes_by_milestone_id.{cl8_milestone_id}",
            "milestone_id": cl8_milestone_id,
            "effective_cl": 8,
            "allowed_resolutions": [
                "ability_score_change",
                "cultivation_insight_acquisition",
            ],
        },
    }
    prior_row = run["attempt_history"][-1]
    prior_response = prior_row["response_text"]
    prior_hash = prior_row["response_sha256"]
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        cl8_diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    provider_response = canonical_json({"option_id": target["option_ids"][0]})
    provider_completion_sha256 = sha256_bytes(provider_response.encode("utf-8"))
    provider_response_sha256 = "d" * 64
    applied_response, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        provider_response,
        cl8_diagnostic,
        run=run,
        repair_target=target,
        provider_completion_sha256=provider_completion_sha256,
        provider_response_sha256=provider_response_sha256,
    )
    request_sha256 = run["request"]["request_sha256"]
    correction_attempt_id = "cg1.attempt.local-provider-correction-fourteen"
    marker = {
        **evidence,
        "attempted": True,
        "explicit": True,
        "status": "RETAINED_FOR_VALIDATION",
        "provider_id": "local",
        "prior_attempt_id": prior_row["attempt_id"],
        "prior_response_sha256": prior_hash,
        "validator_diagnostic": deepcopy(cl8_diagnostic),
    }
    correction_transport = {
        "mode": run["execution_mode"],
        "provider_called": True,
        "provider_id": "local",
        "automatic_retries": 0,
        "complete_request_sha256": request_sha256,
        "prior_attempt_id": prior_row["attempt_id"],
        "provider_completion_sha256": provider_completion_sha256,
        "provider_response_sha256": provider_response_sha256,
        "local_correction": marker,
    }
    applied_hash = sha256_bytes(applied_response.encode("utf-8"))
    run["attempt_history"].append({
        "attempt_id": correction_attempt_id,
        "run_id": run["run_id"],
        "project_id": run["project_id"],
        "ordinal": 14,
        "action_type": "LOCAL_PROVIDER_CORRECTION",
        "status": "BLOCKED",
        "request_sha256": request_sha256,
        "response_sha256": applied_hash,
        "response_text": applied_response,
        "prior_attempt_id": prior_row["attempt_id"],
        "binding": {
            "submitted_request_sha256": None,
            "active_request_sha256": request_sha256,
            "transport": correction_transport,
        },
        "error": {
            "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
            "code": "CG1_PREFERRED_RESPONSE_SHAPE_INVALID",
            "message": "A stale top-level advancement echo is not a canonical mirror.",
            "details": {"field": "advancement_skeleton", "canonical_mirror": False},
        },
    })
    run["transport"] = deepcopy(correction_transport)
    run["response"] = {"exact_response_text": applied_response, "response_sha256": applied_hash}
    run["validation"] = {"last_submission_error": deepcopy(run["attempt_history"][-1]["error"])}
    run["status"] = "NEEDS_REVIEW"
    _append_ordinary_recovery_retry(
        run,
        applied_response,
        attempt_id="cg1.attempt.recovery-retry-fifteen",
        ordinal=15,
    )
    return applied_response, target, cl4_milestone_id, cl8_milestone_id


def _productionize_persisted_advancement_history(run: dict) -> None:
    """Remove the fixture-only retained field before finalize-path checks."""
    history = run["attempt_history"]
    for row in history:
        response_text = row.get("response_text")
        try:
            payload = json.loads(response_text) if isinstance(response_text, str) else None
        except (TypeError, ValueError):
            payload = None
        if not isinstance(payload, dict) or "unrelated_retained_field" not in payload:
            continue
        payload.pop("unrelated_retained_field")
        response_text = canonical_json(payload)
        row["response_text"] = response_text
        row["response_sha256"] = sha256_bytes(response_text.encode("utf-8"))

    rows_by_id = {
        row.get("attempt_id"): row
        for row in history
        if isinstance(row, dict) and isinstance(row.get("attempt_id"), str)
    }
    for row in history:
        binding = row.get("binding") if isinstance(row.get("binding"), dict) else None
        transport = binding.get("transport") if isinstance(binding, dict) else None
        marker = transport.get("local_correction") if isinstance(transport, dict) else None
        if isinstance(marker, dict):
            marker["applied_response_sha256"] = row.get("response_sha256")
            parent = rows_by_id.get(row.get("prior_attempt_id"))
            if isinstance(parent, dict):
                marker["prior_response_sha256"] = parent.get("response_sha256")
        recovery = transport.get("local_recovery") if isinstance(transport, dict) else None
        if isinstance(recovery, dict):
            restored = rows_by_id.get(recovery.get("restored_attempt_id"))
            if isinstance(restored, dict):
                recovery["prior_response_sha256"] = restored.get("response_sha256")

    latest = history[-1]
    run["response"] = {
        "exact_response_text": latest["response_text"],
        "response_sha256": latest["response_sha256"],
    }
    recovery = run.get("transport", {}).get("local_recovery")
    if isinstance(recovery, dict):
        restored = rows_by_id.get(recovery.get("restored_attempt_id"))
        if isinstance(restored, dict):
            recovery["prior_response_sha256"] = restored.get("response_sha256")


def _append_persisted_advancement_choice_attempt_seventeen(
    run: dict,
) -> tuple[str, dict, str, str, str]:
    """Model a ready attempt-17 CL12 correction after CL4 and CL8."""
    applied_response, _target, cl4_milestone_id, cl8_milestone_id = (
        _append_persisted_advancement_choice_attempt_fifteen(run)
    )
    _productionize_persisted_advancement_history(run)
    applied_response = run["response"]["exact_response_text"]
    _append_ordinary_recovery_retry(
        run,
        applied_response,
        attempt_id="cg1.attempt.recovery-retry-sixteen",
        ordinal=16,
    )

    envelope = run["request"]["delegated_choice_envelope"]
    cl4_row = next(
        row
        for row in envelope["advancement_choice_milestones"]
        if row.get("milestone_id") == cl4_milestone_id
    )
    cl12_milestone_id = cl4_milestone_id.rsplit(".cl4", 1)[0] + ".cl12"
    cl12_row = deepcopy(cl4_row)
    cl12_row.update({"milestone_id": cl12_milestone_id, "cl": 12})
    envelope["advancement_choice_milestones"].append(cl12_row)
    envelope["path_progression_choices"].append({"cl": 12, "path_ids": ["path.body"]})

    cl12_authority = deepcopy(run["owner_decision_authority"][cl4_milestone_id])
    cl12_authority["ability_change"]["allowed_cls"] = [12]
    run["owner_decision_authority"][cl12_milestone_id] = cl12_authority
    cl12_diagnostic = {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_BOUNDED_DECISION_REQUIRED",
        "message": "Resolve the missing Advancement Choice.",
        "details": {
            "field": f"bounded_choices.ability_score_changes_by_milestone_id.{cl12_milestone_id}",
            "milestone_id": cl12_milestone_id,
            "effective_cl": 12,
            "allowed_resolutions": [
                "ability_score_change",
                "cultivation_insight_acquisition",
            ],
        },
    }
    prior_row = run["attempt_history"][-1]
    prior_response = prior_row["response_text"]
    prior_hash = prior_row["response_sha256"]
    target = CharacterCreationExecutionService._provider_target_scoped_repair_target(
        cl12_diagnostic,
        run=run,
        prior_response=prior_response,
    )
    assert target is not None
    provider_response = canonical_json({"option_id": target["option_ids"][0]})
    provider_completion_sha256 = sha256_bytes(provider_response.encode("utf-8"))
    provider_response_sha256 = "e" * 64
    applied_response, evidence = CharacterCreationExecutionService._merge_target_scoped_correction_response(
        prior_response,
        provider_response,
        cl12_diagnostic,
        run=run,
        repair_target=target,
        provider_completion_sha256=provider_completion_sha256,
        provider_response_sha256=provider_response_sha256,
    )
    request_sha256 = run["request"]["request_sha256"]
    marker = {
        **evidence,
        "attempted": True,
        "explicit": True,
        "status": "RETAINED_FOR_VALIDATION",
        "provider_id": "local",
        "prior_attempt_id": prior_row["attempt_id"],
        "prior_response_sha256": prior_hash,
        "validator_diagnostic": deepcopy(cl12_diagnostic),
    }
    correction_transport = {
        "mode": run["execution_mode"],
        "provider_called": True,
        "provider_id": "local",
        "automatic_retries": 0,
        "complete_request_sha256": request_sha256,
        "prior_attempt_id": prior_row["attempt_id"],
        "provider_completion_sha256": provider_completion_sha256,
        "provider_response_sha256": provider_response_sha256,
        "local_correction": marker,
    }
    applied_hash = sha256_bytes(applied_response.encode("utf-8"))
    error = {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": "CG1_PREFERRED_RESPONSE_SHAPE_INVALID",
        "message": "A stale top-level advancement echo is not a canonical mirror.",
        "details": {"field": "advancement_skeleton", "canonical_mirror": False},
    }
    run["attempt_history"].append({
        "attempt_id": "cg1.attempt.local-provider-correction-seventeen",
        "run_id": run["run_id"],
        "project_id": run["project_id"],
        "ordinal": 17,
        "action_type": "LOCAL_PROVIDER_CORRECTION",
        "status": "READY_FOR_REVIEW",
        "request_sha256": request_sha256,
        "response_sha256": applied_hash,
        "response_text": applied_response,
        "prior_attempt_id": prior_row["attempt_id"],
        "binding": {
            "submitted_request_sha256": None,
            "active_request_sha256": request_sha256,
            "transport": correction_transport,
        },
        "validation": {"last_submission_error": deepcopy(error)},
        "error": error,
    })
    run["transport"] = deepcopy(correction_transport)
    run["response"] = {"exact_response_text": applied_response, "response_sha256": applied_hash}
    run["validation"] = {"last_submission_error": deepcopy(error)}
    run["status"] = "READY_FOR_REVIEW"
    run["quality"] = {"status": "CLEAN"}
    return applied_response, target, cl4_milestone_id, cl8_milestone_id, cl12_milestone_id


class _HistoricalAdvancementCatalog:
    """Small source-backed authority stand-in for the production-shaped test."""

    def __init__(self, _db):
        pass

    def project_locked_path_feature_catalog_record(self, path_id: str, feature_id: str) -> dict:
        assert path_id == "path.body"
        assert feature_id == "feature.asi-or-insight"
        return {
            "compatibility": {
                "factory": {
                    "stage2_authority": {
                        "allowed_kinds": ["ability_score_change"],
                        "ability_change": {
                            "allowed_cls": [4, 8, 12],
                            "allowed_deltas": [2],
                            "allowed_abilities": ["CON"],
                            "budget": 2,
                            "cap": 20,
                        },
                    },
                },
            },
        }


def _historical_authority_service(monkeypatch):
    monkeypatch.setattr(
        character_creation_service,
        "NonSphereAuthorityService",
        _HistoricalAdvancementCatalog,
    )
    service = object.__new__(CharacterCreationExecutionService)
    service.db = object()
    return service


def test_recovery_reuses_only_retained_stale_advancement_echo_lineage():
    run, recovered_response = _schema_recovery_stale_advancement_echo_context()
    run["validation"]["automatic_correction"] = deepcopy(
        run["attempt_history"][1]["binding"]["transport"]["local_correction"]
    )

    proof = CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        recovered_response,
    )
    assert proof is not None
    assert proof["marker"]["target_kind"] == "ordinary_duplicate"
    assert CharacterCreationExecutionService._proven_stale_server_repair_advancement_echo(
        run,
        recovered_response,
    ) is True
    # _apply_response keeps the latest exact text in its scratch snapshot
    # while overlaying the recovered hash for compilation; the same proof
    # must hold for that in-memory projection as well.
    run["response"]["response_sha256"] = sha256_bytes(recovered_response.encode("utf-8"))
    assert CharacterCreationExecutionService._proven_stale_server_repair_advancement_echo(
        run,
        recovered_response,
    ) is True
    validated = CharacterCreationExecutionService._validated_repaired_ordinary_context(
        run,
        json.loads(recovered_response),
        recovered_response,
    )
    assert validated is not None
    assert validated["ordinary_talent_ids"] == json.loads(recovered_response)["acquisition_intent"]["ordinary_talent_ids"]


def test_persisted_recovery_attempt_seven_reuses_stale_echo_lineage():
    run, recovered_response = _schema_recovery_stale_advancement_echo_context()
    _append_persisted_recovery_attempt(run, recovered_response)

    proof = CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        recovered_response,
    )
    assert proof is not None
    assert proof["marker"]["target_kind"] == "ordinary_duplicate"
    assert CharacterCreationExecutionService._proven_stale_server_repair_advancement_echo(
        run,
        recovered_response,
    ) is True


def test_historical_exact_retry_suffix_reuses_persisted_attempt_seven_receipt():
    run, recovered_response = _schema_recovery_stale_advancement_echo_context()
    _append_persisted_recovery_attempt(run, recovered_response)
    _append_ordinary_recovery_retry(
        run,
        recovered_response,
        attempt_id="cg1.attempt.recovery-retry-eight",
        ordinal=8,
    )
    _append_ordinary_recovery_retry(
        run,
        recovered_response,
        attempt_id="cg1.attempt.recovery-retry-nine",
        ordinal=9,
    )

    proof = CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        recovered_response,
    )
    assert proof is not None
    assert proof["marker"]["target_kind"] == "ordinary_duplicate"
    assert CharacterCreationExecutionService._proven_stale_server_repair_advancement_echo(
        run,
        recovered_response,
    ) is True


def test_advancement_choice_attempt_ten_is_an_exact_target_only_provenance_intermediate():
    run, applied_response = _schema_recovery_stale_advancement_echo_context()
    applied_response, target = _append_persisted_advancement_choice_attempt_ten(run)
    prior_response = run["attempt_history"][-3]["response_text"]
    prior_payload = json.loads(prior_response)
    applied_payload = json.loads(applied_response)

    assert run["attempt_history"][-2]["attempt_id"] == "cg1.attempt.local-provider-correction-ten"
    assert run["attempt_history"][-1]["attempt_id"] == "cg1.attempt.recovery-retry-eleven"
    assert run["transport"]["prior_attempt_id"] == "cg1.attempt.local-provider-correction-ten"
    assert "provider_called" not in run["attempt_history"][-2]["binding"]["transport"]["local_correction"]
    assert "effective_cl" not in run["attempt_history"][-2]["binding"]["transport"]["local_correction"]
    assert applied_payload["bounded_choices"][
        "ability_score_changes_by_milestone_id"
    ][target["milestone_id"]] == {"deltas": {"CON": 2}}
    assert applied_payload["acquisition_intent"] == prior_payload["acquisition_intent"]
    assert applied_payload["advancement_skeleton"] == prior_payload["advancement_skeleton"]
    proof = CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        applied_response,
    )
    assert proof is not None
    assert proof["marker"]["target_kind"] == "ordinary_duplicate"


def test_persisted_attempt_twelve_recovers_historical_advancement_authority_without_provider(
    monkeypatch,
):
    run, _ = _schema_recovery_stale_advancement_echo_context()
    applied_response = _append_persisted_advancement_choice_attempt_twelve(run)
    # Production public projections derive this view; it is not persisted in
    # the request or attempt rows after the current blocker becomes a stale
    # response-shape diagnostic.
    run.pop("owner_decision_authority", None)
    service = _historical_authority_service(monkeypatch)
    run["owner_decision_authority"] = service._owner_decision_authority(run)

    assert list(run["owner_decision_authority"]) == [
        "path.body.feature.ability_score_improvement_or_cultivation_insight.cl4",
    ]
    proof = CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        applied_response,
    )
    assert proof is not None
    assert proof["advancement_choice_marker"]["selected_option_id"].startswith("adv_")
    assert CharacterCreationExecutionService._proven_stale_server_repair_advancement_echo(
        run,
        applied_response,
    ) is True
    assert run["transport"]["provider_called"] is False
    assert run["transport"]["automatic_retries"] == 0


def test_persisted_attempt_fifteen_recovers_ordered_multiple_advancement_authorities_without_provider(
    monkeypatch,
):
    run, _ = _schema_recovery_stale_advancement_echo_context()
    applied_response, _target, cl4_milestone_id, cl8_milestone_id = (
        _append_persisted_advancement_choice_attempt_fifteen(run)
    )
    run.pop("owner_decision_authority", None)
    service = _historical_authority_service(monkeypatch)
    run["owner_decision_authority"] = service._owner_decision_authority(run)

    assert list(run["owner_decision_authority"]) == [cl4_milestone_id, cl8_milestone_id]
    diagnostics = CharacterCreationExecutionService._historical_advancement_choice_diagnostics(run)
    assert [diagnostic["details"]["milestone_id"] for diagnostic in diagnostics] == [
        cl4_milestone_id,
        cl8_milestone_id,
    ]
    proof = CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        applied_response,
    )
    assert proof is not None
    assert [marker["milestone_id"] for marker in proof["advancement_choice_markers"]] == [
        cl4_milestone_id,
        cl8_milestone_id,
    ]
    assert proof["advancement_choice_marker"]["milestone_id"] == cl8_milestone_id
    assert CharacterCreationExecutionService._proven_stale_server_repair_advancement_echo(
        run,
        applied_response,
    ) is True
    assert run["transport"]["provider_called"] is False
    assert run["transport"]["automatic_retries"] == 0


def test_ready_attempt_seventeen_finalize_revalidation_reuses_all_proven_advancement_lineage(
    monkeypatch,
):
    run, _ = _schema_recovery_stale_advancement_echo_context()
    response, _target, cl4_milestone_id, cl8_milestone_id, cl12_milestone_id = (
        _append_persisted_advancement_choice_attempt_seventeen(run)
    )
    run.pop("owner_decision_authority", None)
    service = _historical_authority_service(monkeypatch)
    run["owner_decision_authority"] = service._owner_decision_authority(run)

    assert run["status"] == "READY_FOR_REVIEW"
    assert run["quality"]["status"] == "CLEAN"
    assert list(run["owner_decision_authority"]) == [
        cl4_milestone_id,
        cl8_milestone_id,
        cl12_milestone_id,
    ]
    allow_stale_echo = service._proven_stale_server_repair_advancement_echo(
        run,
        response,
    )
    assert allow_stale_echo is True
    assert run["response"]["response_sha256"] == sha256_bytes(response.encode("utf-8"))

    # This is the exact response-schema revalidation performed by finalize;
    # it must use the retained proof without changing the approved bytes.
    plan, _raw = service._parse_plan(
        response,
        expected_project_id=run["project_id"],
        expected_project_revision=run["starting_revision"],
        allow_proven_stale_advancement_echo=allow_stale_echo,
    )
    assert "advancement_skeleton" not in plan
    assert plan["bounded_choices"]["ability_score_changes_by_milestone_id"] == {
        cl4_milestone_id: {"deltas": {"CON": 2}},
        cl8_milestone_id: {"deltas": {"CON": 2}},
        cl12_milestone_id: {"deltas": {"CON": 2}},
    }


def test_ready_attempt_seventeen_finalize_revalidation_rejects_tampered_marker(
    monkeypatch,
):
    run, _ = _schema_recovery_stale_advancement_echo_context()
    response, _target, _cl4_milestone_id, _cl8_milestone_id, _cl12_milestone_id = (
        _append_persisted_advancement_choice_attempt_seventeen(run)
    )
    latest_marker = run["attempt_history"][-1]["binding"]["transport"]["local_correction"]
    latest_marker["provider_response_sha256"] = "f" * 64
    run.pop("owner_decision_authority", None)
    service = _historical_authority_service(monkeypatch)
    run["owner_decision_authority"] = service._owner_decision_authority(run)

    assert run["owner_decision_authority"] == {}
    assert service._proven_stale_server_repair_advancement_echo(run, response) is False
    with pytest.raises(FoundryError) as rejected:
        service._parse_plan(
            response,
            expected_project_id=run["project_id"],
            expected_project_revision=run["starting_revision"],
            allow_proven_stale_advancement_echo=False,
        )
    assert rejected.value.code == "CG1_PREFERRED_RESPONSE_SHAPE_INVALID"
    assert rejected.value.details == {
        "field": "advancement_skeleton",
        "canonical_mirror": False,
    }


@pytest.mark.parametrize("mutation", [
    "duplicate_milestone",
    "reordered_targets",
    "physical_row_swap",
    "ordinal_tamper",
    "intervening_correction",
    "non_target_rehash",
    "provider_free_suffix",
])
def test_persisted_attempt_fifteen_rejects_multiple_advancement_lineage_tampering(
    mutation,
    monkeypatch,
):
    run, _ = _schema_recovery_stale_advancement_echo_context()
    applied_response, _target, cl4_milestone_id, cl8_milestone_id = (
        _append_persisted_advancement_choice_attempt_fifteen(run)
    )
    run.pop("owner_decision_authority", None)
    correction = run["attempt_history"][-2]
    retry = run["attempt_history"][-1]
    if mutation == "duplicate_milestone":
        correction["binding"]["transport"]["local_correction"]["milestone_id"] = cl4_milestone_id
    elif mutation == "reordered_targets":
        first_correction = next(
            row for row in run["attempt_history"]
            if row.get("action_type") == "LOCAL_PROVIDER_CORRECTION"
            and isinstance(row.get("binding"), dict)
            and row["binding"].get("transport", {}).get("local_correction", {}).get("target_kind")
            == "advancement_choice"
            and row["binding"]["transport"]["local_correction"].get("milestone_id") == cl4_milestone_id
        )
        first_marker = first_correction["binding"]["transport"]["local_correction"]
        second_marker = correction["binding"]["transport"]["local_correction"]
        first_marker["milestone_id"], second_marker["milestone_id"] = (
            second_marker["milestone_id"],
            first_marker["milestone_id"],
        )
    elif mutation == "physical_row_swap":
        first_index = next(
            index
            for index, row in enumerate(run["attempt_history"])
            if row.get("action_type") == "LOCAL_PROVIDER_CORRECTION"
            and isinstance(row.get("binding"), dict)
            and row["binding"].get("transport", {}).get("local_correction", {}).get("milestone_id")
            == cl4_milestone_id
        )
        second_index = next(
            index
            for index, row in enumerate(run["attempt_history"])
            if row.get("action_type") == "LOCAL_PROVIDER_CORRECTION"
            and isinstance(row.get("binding"), dict)
            and row["binding"].get("transport", {}).get("local_correction", {}).get("milestone_id")
            == cl8_milestone_id
        )
        run["attempt_history"][first_index], run["attempt_history"][second_index] = (
            run["attempt_history"][second_index],
            run["attempt_history"][first_index],
        )
    elif mutation == "ordinal_tamper":
        correction["ordinal"] = correction["ordinal"] + 1
    elif mutation == "intervening_correction":
        intervening = deepcopy(run["attempt_history"][-3])
        intervening["attempt_id"] = "cg1.attempt.intervening-between-advancement-choices"
        intervening["ordinal"] = 14
        intervening["action_type"] = "IMPORT_RESPONSE"
        intervening["prior_attempt_id"] = run["attempt_history"][-3]["attempt_id"]
        intervening["binding"]["transport"]["prior_attempt_id"] = intervening["prior_attempt_id"]
        correction["prior_attempt_id"] = intervening["attempt_id"]
        correction["binding"]["transport"]["prior_attempt_id"] = intervening["attempt_id"]
        correction["binding"]["transport"]["local_correction"]["prior_attempt_id"] = intervening["attempt_id"]
        run["attempt_history"].insert(-2, intervening)
    elif mutation == "non_target_rehash":
        payload = json.loads(applied_response)
        payload["acquisition_intent"]["ordinary_talent_ids"][0] = "TAMPERED"
        changed = canonical_json(payload)
        changed_hash = sha256_bytes(changed.encode("utf-8"))
        correction["response_text"] = changed
        correction["response_sha256"] = changed_hash
        correction["binding"]["transport"]["local_correction"]["applied_response_sha256"] = changed_hash
        retry["response_text"] = changed
        retry["response_sha256"] = changed_hash
        run["response"] = {"exact_response_text": changed, "response_sha256": changed_hash}
        applied_response = changed
    else:
        retry["binding"]["transport"]["provider_called"] = True

    service = _historical_authority_service(monkeypatch)
    run["owner_decision_authority"] = service._owner_decision_authority(run)
    assert run["owner_decision_authority"] == {}
    assert CharacterCreationExecutionService._historical_advancement_choice_diagnostics(run) == []
    assert CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        applied_response,
    ) is None
    assert CharacterCreationExecutionService._proven_stale_server_repair_advancement_echo(
        run,
        applied_response,
    ) is False


@pytest.mark.parametrize("mutation", [
    "selected_option",
    "wrong_provider",
    "intervening_row",
    "wrong_hash",
    "disconnected_sibling",
    "non_target_rehash",
])
def test_persisted_attempt_twelve_rejects_historical_advancement_authority_tampering(
    mutation,
    monkeypatch,
):
    run, _ = _schema_recovery_stale_advancement_echo_context()
    applied_response = _append_persisted_advancement_choice_attempt_twelve(run)
    run.pop("owner_decision_authority", None)
    service = _historical_authority_service(monkeypatch)
    correction = run["attempt_history"][-3]
    if mutation == "selected_option":
        correction["binding"]["transport"]["local_correction"]["selected_option_id"] = "adv_unknown"
    elif mutation == "wrong_provider":
        correction["binding"]["transport"]["provider_id"] = "remote"
    elif mutation == "intervening_row":
        intervening = deepcopy(run["attempt_history"][-2])
        intervening["attempt_id"] = "cg1.attempt.intervening-between-choice-and-retry"
        intervening["ordinal"] = 11
        intervening["action_type"] = "IMPORT_RESPONSE"
        run["attempt_history"].insert(-2, intervening)
    elif mutation == "disconnected_sibling":
        sibling = deepcopy(correction)
        sibling["attempt_id"] = "cg1.attempt.disconnected-advancement-sibling"
        sibling["ordinal"] = 10
        run["attempt_history"].insert(-3, sibling)
    elif mutation == "non_target_rehash":
        payload = json.loads(applied_response)
        payload["acquisition_intent"]["ordinary_talent_ids"][0] = "TAMPERED"
        changed = canonical_json(payload)
        changed_hash = sha256_bytes(changed.encode("utf-8"))
        correction["response_text"] = changed
        correction["response_sha256"] = changed_hash
        correction["binding"]["transport"]["local_correction"]["applied_response_sha256"] = changed_hash
        for row in run["attempt_history"][-2:]:
            row["response_text"] = changed
            row["response_sha256"] = changed_hash
        run["response"] = {"exact_response_text": changed, "response_sha256": changed_hash}
        applied_response = changed
    else:
        correction["binding"]["transport"]["local_correction"]["applied_response_sha256"] = "f" * 64

    run["owner_decision_authority"] = service._owner_decision_authority(run)
    assert run["owner_decision_authority"] == {}
    assert CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        applied_response,
    ) is None
    assert CharacterCreationExecutionService._proven_stale_server_repair_advancement_echo(
        run,
        applied_response,
    ) is False


@pytest.mark.parametrize("mutation", [
    "prior_hash",
    "request_hash",
    "provider_called",
    "marker_provider_called",
    "automatic_retries",
    "unknown_option",
    "non_target_array",
    "stale_echo",
    "target_milestone",
])
def test_advancement_choice_attempt_ten_rejects_tampered_or_non_target_lineage(mutation):
    run, applied_response = _schema_recovery_stale_advancement_echo_context()
    applied_response, target = _append_persisted_advancement_choice_attempt_ten(run)
    row = run["attempt_history"][-2]
    retry_row = run["attempt_history"][-1]
    transport = row["binding"]["transport"]
    marker = transport["local_correction"]
    if mutation == "prior_hash":
        marker["prior_response_sha256"] = "f" * 64
    elif mutation == "request_hash":
        marker["request_sha256"] = "f" * 64
    elif mutation == "provider_called":
        transport["provider_called"] = False
    elif mutation == "marker_provider_called":
        marker["provider_called"] = False
    elif mutation == "automatic_retries":
        transport["automatic_retries"] = 1
    elif mutation == "unknown_option":
        marker["selected_option_id"] = "adv_unknown"
    elif mutation == "non_target_array":
        payload = json.loads(applied_response)
        payload["acquisition_intent"]["ordinary_talent_ids"][0] = "TAMPERED"
        changed = canonical_json(payload)
        row["response_text"] = changed
        row["response_sha256"] = sha256_bytes(changed.encode("utf-8"))
        marker["applied_response_sha256"] = row["response_sha256"]
        run["response"] = {
            "exact_response_text": changed,
            "response_sha256": row["response_sha256"],
        }
        retry_row["response_text"] = changed
        retry_row["response_sha256"] = row["response_sha256"]
        applied_response = changed
    elif mutation == "stale_echo":
        payload = json.loads(applied_response)
        payload["advancement_skeleton"] = ["forged-stale-echo"]
        changed = canonical_json(payload)
        row["response_text"] = changed
        row["response_sha256"] = sha256_bytes(changed.encode("utf-8"))
        marker["applied_response_sha256"] = row["response_sha256"]
        run["response"] = {
            "exact_response_text": changed,
            "response_sha256": row["response_sha256"],
        }
        retry_row["response_text"] = changed
        retry_row["response_sha256"] = row["response_sha256"]
        applied_response = changed
    else:
        marker["milestone_id"] = "other.milestone"

    assert CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        applied_response,
    ) is None


@pytest.mark.parametrize("mutation", [
    "wrong_action",
    "intervening_row",
    "wrong_hash",
    "wrong_prior",
])
def test_historical_recovery_retry_suffix_rejects_tampering(mutation):
    run, recovered_response = _schema_recovery_stale_advancement_echo_context()
    _append_persisted_recovery_attempt(run, recovered_response)
    _append_ordinary_recovery_retry(
        run,
        recovered_response,
        attempt_id="cg1.attempt.recovery-retry-eight",
        ordinal=8,
    )
    attempt_eight = run["attempt_history"][-1]
    if mutation == "wrong_action":
        attempt_eight["action_type"] = "IMPORT_RESPONSE"
    elif mutation == "intervening_row":
        intervening = deepcopy(attempt_eight)
        intervening["attempt_id"] = "cg1.attempt.intervening"
        intervening["ordinal"] = 9
        intervening["action_type"] = "IMPORT_RESPONSE"
        intervening["prior_attempt_id"] = attempt_eight["attempt_id"]
        intervening["binding"]["transport"]["prior_attempt_id"] = attempt_eight["attempt_id"]
        run["attempt_history"].append(intervening)
        _append_ordinary_recovery_retry(
            run,
            recovered_response,
            attempt_id="cg1.attempt.recovery-retry-nine",
            ordinal=10,
        )
    elif mutation == "wrong_hash":
        attempt_eight["response_sha256"] = "f" * 64
    else:
        attempt_eight["prior_attempt_id"] = run["attempt_history"][0]["attempt_id"]

    assert CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        recovered_response,
    ) is None
    assert CharacterCreationExecutionService._proven_stale_server_repair_advancement_echo(
        run,
        recovered_response,
    ) is False


@pytest.mark.parametrize("mutation", [
    "attempt_seven_parent",
    "attempt_seven_receipt",
    "attempt_seven_leaf_hash",
])
def test_persisted_recovery_attempt_seven_rejects_tampered_lineage(mutation):
    run, recovered_response = _schema_recovery_stale_advancement_echo_context()
    _append_persisted_recovery_attempt(run, recovered_response)
    attempt_seven = run["attempt_history"][-1]
    if mutation == "attempt_seven_parent":
        attempt_seven["prior_attempt_id"] = run["attempt_history"][0]["attempt_id"]
    elif mutation == "attempt_seven_receipt":
        attempt_seven["binding"]["transport"]["local_recovery"]["prior_response_sha256"] = "f" * 64
    else:
        attempt_seven["response_sha256"] = "f" * 64

    assert CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        recovered_response,
    ) is None
    assert CharacterCreationExecutionService._proven_stale_server_repair_advancement_echo(
        run,
        recovered_response,
    ) is False


@pytest.mark.parametrize("mutation", [
    "wrong_restored_attempt",
    "intervening_row",
    "tampered_leaf_text",
    "tampered_leaf_hash",
    "tampered_recovery_hash",
    "tampered_recovery_diagnostic",
])
def test_recovery_stale_advancement_echo_lineage_rejects_wrong_or_tampered_receipts(mutation):
    run, recovered_response = _schema_recovery_stale_advancement_echo_context()
    recovery = run["transport"]["local_recovery"]
    if mutation == "wrong_restored_attempt":
        recovery["restored_attempt_id"] = run["attempt_history"][1]["attempt_id"]
    elif mutation == "intervening_row":
        intervening = deepcopy(run["attempt_history"][0])
        intervening["attempt_id"] = "cg1.attempt.intervening"
        intervening["ordinal"] = 6
        run["attempt_history"].insert(-1, intervening)
    elif mutation == "tampered_leaf_text":
        run["attempt_history"][-1]["response_text"] = canonical_json({
            "schema": "TianxiaFoundry.TamperedLeaf.v1",
        })
    elif mutation == "tampered_leaf_hash":
        run["attempt_history"][-1]["response_sha256"] = "f" * 64
    elif mutation == "tampered_recovery_hash":
        recovery["prior_response_sha256"] = "f" * 64
    else:
        recovery["original_diagnostic"] = {
            "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
            "code": "CG1_STAGE2_INVALID",
            "details": {},
        }

    assert CharacterCreationExecutionService._ordinary_repair_provenance_chain(
        run,
        recovered_response,
    ) is None
    assert CharacterCreationExecutionService._proven_stale_server_repair_advancement_echo(
        run,
        recovered_response,
    ) is False


@pytest.mark.parametrize("route", ["guided", "import", "provider"])
def test_retry_local_build_without_correction_lineage_replays_exact_response(monkeypatch, route):
    run = _explicit_review_run(diagnostic_code="CG1_DELEGATED_AUTHORITY_CONFLICT")
    if route == "guided":
        run["execution_mode"] = "AUTO_FINALIZE_WHEN_CLEAN"
        run["request"]["controller_route"] = character_creation_service.DETERMINISTIC_CREATIVE_CONTROLLER
        run["transport"] = {"provider_called": True, "purpose": "dcc_linear_step"}
        run["attempt_history"][-1]["action_type"] = "DCC_LINEAR_WALK"
    elif route == "import":
        run["transport"] = {"provider_called": False, "transfer": "import_response"}
        run["attempt_history"][-1]["action_type"] = "IMPORT_RESPONSE"
    else:
        run["transport"]["provider_id"] = "custom"
        run["attempt_history"][-1]["action_type"] = "PROVIDER_RESPONSE"
    response_text = run["response"]["exact_response_text"]
    original = deepcopy(run)
    service, apply_calls = _service(monkeypatch, run, [], [{"status": "READY_FOR_REVIEW"}], provider_id="custom")
    if route == "guided":
        service.provider.status = lambda: pytest.fail("Guided local replay must not consult the current provider.")

    result = service.retry_local_build(run["run_id"])

    assert result["status"] == "READY_FOR_REVIEW"
    assert service.provider.calls == []
    assert len(apply_calls) == 1
    call = apply_calls[0]
    assert call["response_text"] == response_text
    assert call["kwargs"]["action_type"] == "RETRY_LOCAL_BUILD"
    assert call["kwargs"]["submitted_request_sha256"] == run["request"]["request_sha256"]
    assert call["kwargs"]["prior_attempt_id"] == run["attempt_history"][-1]["attempt_id"]
    assert call["transport"]["provider_called"] is False
    assert call["transport"]["automatic_retries"] == 0
    assert "local_recovery" not in call["transport"]
    assert run == original


def test_retry_local_build_recovers_exact_prior_attempt_without_provider_and_records_lineage(monkeypatch):
    run, prior_response, prior_attempt_id, latest_attempt_id = _schema_recovery_run()
    retained_result = {**_blocked_result(run, prior_response, provider_id="local"), "status": "NEEDS_REVIEW"}
    service, apply_calls = _service(monkeypatch, run, [], [retained_result])
    service._latest_attempt_id = lambda _run_id: latest_attempt_id
    initial_history = deepcopy(run["attempt_history"])

    result = service.retry_local_build(run["run_id"])

    assert result["status"] == "NEEDS_REVIEW"
    assert service.provider.calls == []
    assert len(apply_calls) == 1
    call = apply_calls[0]
    assert call["response_text"] == prior_response
    assert call["kwargs"]["action_type"] == "RETRY_LOCAL_BUILD"
    assert call["kwargs"]["prior_attempt_id"] == latest_attempt_id
    assert call["transport"]["provider_called"] is False
    assert call["transport"]["automatic_retries"] == 0
    recovery = call["transport"]["local_recovery"]
    assert recovery["recovered_from_attempt_id"] == latest_attempt_id
    assert recovery["restored_attempt_id"] == prior_attempt_id
    assert recovery["request_sha256"] == run["request"]["request_sha256"]
    assert recovery["prior_response_sha256"] == sha256_bytes(prior_response.encode("utf-8"))
    assert recovery["original_diagnostic"]["code"] == "CG1_BOUNDED_DECISION_REQUIRED"
    assert run["attempt_history"] == initial_history


@pytest.mark.parametrize("mutation", [
    "stale_revision",
    "wrong_provider",
    "wrong_hash",
    "wrong_parent",
    "missing_response",
    "unallowlisted_diagnostic",
    "missing_complete_request",
        "wrong_action",
        "missing_lineage_binding",
        "nonlocal_provider",
        "stale_parent",
        "intervening_row",
        "leaf_response_tamper",
])
def test_retry_local_build_recovery_rejects_stale_or_tampered_lineage(monkeypatch, mutation):
    run, _prior_response, prior_attempt_id, _latest_attempt_id = _schema_recovery_run()
    if mutation == "stale_revision":
        run["request"]["project_revision"] = run["starting_revision"] + 1
    elif mutation == "wrong_provider":
        run["attempt_history"][-1]["binding"]["transport"]["local_correction"]["provider_id"] = "custom"
    elif mutation == "wrong_hash":
        run["attempt_history"][-1]["binding"]["transport"]["local_correction"]["prior_response_sha256"] = "f" * 64
    elif mutation == "wrong_parent":
        run["attempt_history"][-1]["prior_attempt_id"] = "cg1.attempt.wrong"
    elif mutation == "missing_response":
        run["response"] = {}
    elif mutation == "unallowlisted_diagnostic":
        run["attempt_history"][-1]["binding"]["transport"]["local_correction"]["validator_diagnostic"]["code"] = "CG1_STAGE2_INVALID"
    elif mutation == "missing_complete_request":
        run["attempt_history"][-1]["binding"]["transport"].pop("complete_request_sha256")
    elif mutation == "wrong_action":
        run["attempt_history"][-1]["action_type"] = "IMPORT_RESPONSE"
    elif mutation == "missing_lineage_binding":
        run["attempt_history"][-1].pop("binding")
    elif mutation == "nonlocal_provider":
        run["transport"]["provider_id"] = "custom"
        run["attempt_history"][-1]["binding"]["transport"]["provider_id"] = "custom"
        run["attempt_history"][-1]["binding"]["transport"]["local_correction"]["provider_id"] = "custom"
    elif mutation == "stale_parent":
        stale = deepcopy(run["attempt_history"][0])
        stale["attempt_id"] = "cg1.attempt.stale-parent"
        run["attempt_history"].insert(0, stale)
        run["attempt_history"][-1]["prior_attempt_id"] = stale["attempt_id"]
        run["attempt_history"][-1]["binding"]["transport"]["local_correction"]["prior_attempt_id"] = stale["attempt_id"]
    elif mutation == "intervening_row":
        intervening = deepcopy(run["attempt_history"][0])
        intervening["attempt_id"] = "cg1.attempt.intervening"
        run["attempt_history"].insert(-1, intervening)
    else:
        tampered = canonical_json({"schema": "TianxiaFoundry.TamperedLeaf.v1"})
        run["attempt_history"][-1]["response_text"] = tampered
        run["attempt_history"][-1]["response_sha256"] = sha256_bytes(tampered.encode("utf-8"))
    provider_id = "custom" if mutation in {"wrong_provider", "nonlocal_provider"} else "local"
    service, apply_calls = _service(monkeypatch, run, [], [], provider_id=provider_id)
    service._latest_attempt_id = lambda _run_id: run["attempt_history"][-1]["attempt_id"]

    with pytest.raises(FoundryError) as rejected:
        service.retry_local_build(run["run_id"])
    assert rejected.value.code in {
        "CG1_RETRY_LOCAL_BUILD_RECOVERY_INVALID",
        "CG1_RETRY_LOCAL_BUILD_RESPONSE_MISSING",
        # 80fee3e0: a run with no response text and no digest to recover it.
        "CG1_RETRY_LOCAL_BUILD_RESPONSE_EVIDENCE_INVALID",
    }
    assert service.provider.calls == []
    assert apply_calls == []
