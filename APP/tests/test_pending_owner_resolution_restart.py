from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

import pytest

from app.core import FoundryError, canonical_json, sha256_bytes, sha256_json
from character_creation.delegated_choice_authority import final_plan_sha256
from character_creation.service import CharacterCreationExecutionService


def _fixture() -> tuple[CharacterCreationExecutionService, dict, dict, str, str]:
    """Build a public-safe pending owner batch and its restarted control."""
    service = object.__new__(CharacterCreationExecutionService)
    content_lock_hash = "c" * 64
    envelope = {
        "advancement_choice_milestones": [{
            "milestone_id": "CL4",
            "cl": 4,
            "path_id": "path.synthetic.qi",
            "allowed_kinds": ["cultivation_insight_acquisition"],
        }, {
            "milestone_id": "CL8",
            "cl": 8,
            "path_id": "path.synthetic.qi",
            "allowed_kinds": ["cultivation_insight_acquisition"],
        }],
        "allowed_choice_ids_by_slot": {
            "insight_priorities": ["insight.synthetic.cl4", "insight.synthetic.cl8"],
        },
        "choices_by_slot": {
            "insight_priorities": {
                "insight.synthetic.cl4": {"name": "Synthetic Insight"},
                "insight.synthetic.cl8": {"name": "Synthetic Later Insight"},
            },
        },
        "typed_choice_authority_by_slot": {
            "insight_priorities": {
                "stage2_authority_by_choice": {
                    "insight.synthetic.cl4": {
                        "ability_change": {
                            "allowed_abilities": ["INT"],
                            "amount": 1,
                            "cap": 20,
                        },
                        "allowed_cls": [4],
                    },
                    "insight.synthetic.cl8": {
                        "ability_change": {
                            "allowed_abilities": ["WIS"],
                            "amount": 1,
                            "cap": 20,
                        },
                        "allowed_cls": [8],
                    },
                },
            },
        },
    }
    request = {
        "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v3",
        "project_id": "project.synthetic.pending-restart",
        "content_lock_hash": content_lock_hash,
        "delegated_choice_envelope": envelope,
    }
    request["request_sha256"] = service.request_payload_sha256(request)
    plan = {
        "schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
        "request_sha256": request["request_sha256"],
        "selection_intent": {"by_slot": {}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": [],
            "insight_occurrences": [],
        },
        "bounded_choices": {
            "ability_scores": {"INT": 19, "WIS": 19},
            "ability_score_changes_by_milestone_id": {},
        },
        "owner_descriptive_fields": {
            "identity": {"name": "Synthetic Restart"},
            "concept": "A provider-free pending owner decision fixture.",
        },
    }
    response_text = canonical_json(plan)
    response_sha256 = sha256_bytes(response_text.encode("utf-8"))
    value = {
        "kind": "cultivation_insight_acquisition",
        "milestone_id": "CL4",
        "insight_id": "insight.synthetic.cl4",
        "parameters": {"ability": "INT"},
    }
    run_id = "run.synthetic.pending-restart"
    resolution = {
        "schema": "TianxiaFoundry.OwnerDecisionResolution.v1",
        "decision_id": "cg1.decision.original-cl4",
        "field": "bounded_choices.ability_score_changes_by_milestone_id.CL4",
        "slot_id": None,
        "operation": "set_milestone_choice",
        "target_value": None,
        "value": value,
        "binding": {
            "run_id": run_id,
            "request_sha256": request["request_sha256"],
            "response_sha256": response_sha256,
            "content_lock_hash": content_lock_hash,
            "blocker_sha256": "b" * 64,
        },
    }
    raw_details = {
        "kind": "cultivation_insight_acquisition",
        "milestone_id": "CL4",
    }
    run = {
        "run_id": run_id,
        "project_id": request["project_id"],
        "status": "NEEDS_REVIEW",
        "request": request,
        "response": {
            "exact_response_text": response_text,
            "response_sha256": response_sha256,
        },
        "validation": {"owner_resolutions": [resolution]},
        "blockers": [{
            "code": "CG1_DECISION_MILESTONE_KIND_INVALID",
            "details": raw_details,
        }],
        "owner_decision_authority": {
            "CL4": {
                "ability_change": {
                    "allowed_abilities": ["INT"],
                    "amount": 1,
                    "cap": 20,
                },
                "allowed_kinds": ["cultivation_insight_acquisition"],
            },
            "CL8": {
                "ability_change": {
                    "allowed_abilities": ["WIS"],
                    "amount": 1,
                    "cap": 20,
                },
                "allowed_kinds": ["cultivation_insight_acquisition"],
            },
        },
    }
    run["validation"]["owner_resolution_batch"] = service._owner_resolution_batch_marker(
        [resolution], response_sha256=response_sha256, status="PENDING"
    )
    run["validation"]["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256(
        [resolution]
    )
    current_decision_id = service._owner_decision_id(
        run,
        field="owner decision",
        slot_id=None,
        operation="set_milestone_choice",
        blocker_sha256=sha256_json(raw_details),
    )
    return service, run, value, current_decision_id, response_text


class _SyntheticTransaction:
    def __init__(self, store: "_SyntheticRunStore") -> None:
        self.store = store

    def __enter__(self) -> sqlite3.Connection:
        self.store.connection.execute("BEGIN")
        return self.store.connection

    def __exit__(self, exc_type, _exc_value, _traceback) -> None:
        if exc_type is None:
            self.store.connection.commit()
        else:
            self.store.connection.rollback()


class _SyntheticRunStore:
    """Tiny public-safe SQLite store for service lifecycle tests."""

    def __init__(self, run: dict) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE character_creation_runs(
                run_id TEXT PRIMARY KEY,
                project_id TEXT,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                validation_json TEXT NOT NULL,
                dry_run_json TEXT NOT NULL,
                blockers_json TEXT NOT NULL,
                status TEXT NOT NULL,
                transport_json TEXT NOT NULL,
                owner_descriptive_fields_json TEXT NOT NULL,
                owner_decision TEXT,
                updated_at TEXT
            )
            """
        )
        self.connection.execute(
            """
            INSERT INTO character_creation_runs(
                run_id, project_id, request_json, response_json, validation_json,
                dry_run_json, blockers_json, status, transport_json,
                owner_descriptive_fields_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            self._row_values(run),
        )
        self.connection.commit()

    @staticmethod
    def _row_values(run: dict) -> tuple:
        return (
            run["run_id"],
            run.get("project_id"),
            canonical_json(run.get("request") or {}),
            canonical_json(run.get("response") or {}),
            canonical_json(run.get("validation") or {}),
            canonical_json(run.get("dry_run") or {}),
            canonical_json(run.get("blockers") or []),
            run.get("status") or "NEEDS_REVIEW",
            canonical_json(run.get("transport") or {}),
            canonical_json(run.get("owner_descriptive_fields") or {}),
        )

    def transaction(self) -> _SyntheticTransaction:
        return _SyntheticTransaction(self)

    def get(self, run_id: str) -> dict:
        row = self.connection.execute(
            "SELECT * FROM character_creation_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise AssertionError(f"missing synthetic run {run_id}")
        return {
            "run_id": row["run_id"],
            "project_id": row["project_id"],
            "request": json.loads(row["request_json"]),
            "response": json.loads(row["response_json"]),
            "validation": json.loads(row["validation_json"]),
            "dry_run": json.loads(row["dry_run_json"]),
            "blockers": json.loads(row["blockers_json"]),
            "status": row["status"],
            "transport": json.loads(row["transport_json"]),
            "owner_descriptive_fields": json.loads(row["owner_descriptive_fields_json"]),
        }


def _synthetic_diagnostic(code: str, details: dict) -> dict:
    return {
        "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
        "code": code,
        "message": "Synthetic bounded compile failure.",
        "details": deepcopy(details),
        "stage": "LEGALITY",
        "category": "LEGALITY",
        "boundary": "LEGALITY",
        "json_parsed": True,
        "response_retained": True,
    }


def _synthetic_pre_fix_successor_fixture() -> tuple[
    CharacterCreationExecutionService,
    _SyntheticRunStore,
    dict,
    dict,
    dict,
    str,
]:
    """Create the pre-fix CL4-pending/CL8-blocked durable shape."""
    service, run, _cl4_value, _old_decision_id, response_text = _fixture()
    diagnostic = _synthetic_diagnostic("CG1_BOUNDED_DECISION_REQUIRED", _cl8_blocker_details())
    run["validation"]["last_submission_error"] = deepcopy(diagnostic)
    run["blockers"] = [deepcopy(diagnostic)]
    value = {
        "kind": "cultivation_insight_acquisition",
        "milestone_id": "CL8",
        "insight_id": "insight.synthetic.cl8",
        "parameters": {"ability": "WIS"},
    }
    decision_id = service._owner_decision_id(
        run,
        field=_cl8_blocker_details()["field"],
        slot_id=None,
        operation="set_milestone_choice",
        blocker_sha256=sha256_json(_cl8_blocker_details()),
    )
    store = _SyntheticRunStore(run)
    service.db = store
    service.get = store.get
    service._append_attempt = lambda *_args, **_kwargs: None
    return service, store, run, diagnostic, value, decision_id


def _synthetic_owner_failure(
    diagnostic: dict,
) -> tuple[CharacterCreationExecutionService, _SyntheticRunStore, dict, dict]:
    service, run, _value, _decision_id, response_text = _fixture()
    store = _SyntheticRunStore(run)
    service.db = store
    service.get = store.get
    service._append_attempt = lambda *_args, **_kwargs: None
    authorization = service._owner_decision_authorization_for_pending_retry(run, response_text)
    assert authorization is not None
    result = service._record_owner_transition_compile_failure(
        run,
        run_id=run["run_id"],
        response_text=response_text,
        transport={"mode": "STANDARD_API", "provider_called": False},
        action_type="RETRY_LOCAL_BUILD",
        submitted_request_sha256=run["request"]["request_sha256"],
        history_prior_attempt_id=None,
        diagnostic=diagnostic,
        descriptive={},
        proposal_projection={},
        _owner_decision_authorization=authorization,
        incoming_response_sha256=run["response"]["response_sha256"],
    )
    return service, store, result, run


def test_restart_style_control_reuses_exact_pending_insight_without_provider() -> None:
    service, run, value, current_decision_id, _response_text = _fixture()
    persisted_calls: list[dict] = []
    retry_calls: list[dict] = []

    service.get = lambda _run_id: deepcopy(run)

    def persist(_run, resolution, **_kwargs):
        persisted_calls.append(deepcopy(resolution))
        rows = deepcopy(run["validation"]["owner_resolutions"])
        return {
            "state": "PENDING",
            "resolutions": rows,
            "batch_sha256": service._owner_resolution_batch_sha256(rows),
        }

    def retry(_run_id, *, _owner_decision_authorization=None):
        retry_calls.append(deepcopy(_owner_decision_authorization))
        result = deepcopy(run)
        result["validation"]["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            result["validation"]["owner_resolutions"],
            response_sha256=result["response"]["response_sha256"],
            status="APPLIED",
        )
        return result

    service._persist_owner_resolution_pending = persist
    service.retry_local_build = retry
    result = service.resolve_owner_decision(
        run["run_id"],
        decision_id=current_decision_id,
        field="owner decision",
        slot_id=None,
        operation="set_milestone_choice",
        target_value=None,
        value=value,
        request_sha256=run["request"]["request_sha256"],
        response_sha256=run["response"]["response_sha256"],
        content_lock_hash=run["request"]["content_lock_hash"],
    )

    assert len(persisted_calls) == 1
    assert persisted_calls[0]["value"] == value
    assert len(retry_calls) == 1
    assert retry_calls[0]["run_id"] == run["run_id"]
    assert retry_calls[0]["request_sha256"] == run["request"]["request_sha256"]
    assert retry_calls[0]["response_sha256"] == run["response"]["response_sha256"]
    assert retry_calls[0]["resolution_count"] == 1
    assert result["validation"]["owner_resolution_batch"]["status"] == "APPLIED"
    assert run["validation"]["owner_resolution_batch"]["status"] == "PENDING"


@pytest.mark.parametrize("pending", (True, False), ids=("pending-batch", "no-pending-batch"))
def test_generic_retry_never_reconstructs_owner_authority(pending: bool) -> None:
    """Only an already-matched owner control may supply the private capability."""
    service, run, _value, _decision_id, _response_text = _fixture()
    if not pending:
        run["validation"] = {}
    captured: list[dict] = []

    service.get = lambda _run_id: deepcopy(run)
    service._provider_selected_id = lambda: "provider.synthetic.local"
    service._recover_scoped_local_correction_context = lambda *_args, **_kwargs: (False, None)
    service._latest_attempt_id = lambda _run_id: "attempt.synthetic.retry"
    service._legacy_retry_bypass_context = lambda *_args, **_kwargs: None
    service._provider_target_scoped_repair_target = lambda *_args, **_kwargs: None

    def forbidden_authority_reconstruction(*_args, **_kwargs):
        raise AssertionError("generic Retry Local Build must not reconstruct owner authority")

    service._owner_decision_authorization_for_pending_retry = forbidden_authority_reconstruction

    def capture_apply(*_args, **kwargs):
        captured.append(kwargs)
        return {"status": "captured"}

    service._apply_response = capture_apply
    result = service.retry_local_build(run["run_id"])

    assert result == {"status": "captured"}
    assert len(captured) == 1
    assert captured[0]["_owner_decision_authorization"] is None
    assert captured[0]["action_type"] == "RETRY_LOCAL_BUILD"


def _cl8_blocker_details() -> dict:
    return {
        "field": "bounded_choices.ability_score_changes_by_milestone_id.CL8",
        "milestone_id": "CL8",
        "effective_cl": 8,
        "allowed_resolutions": [
            "ability_score_change",
            "cultivation_insight_acquisition",
        ],
    }


def test_authorized_transition_applies_batch_when_next_milestone_blocks() -> None:
    diagnostic = _synthetic_diagnostic(
        "CG1_BOUNDED_DECISION_REQUIRED",
        _cl8_blocker_details(),
    )
    service, store, result, _run = _synthetic_owner_failure(diagnostic)

    rows = result["validation"]["owner_resolutions"]
    expected_marker = service._owner_resolution_batch_marker(
        rows,
        response_sha256=result["response"]["response_sha256"],
        status="APPLIED",
    )
    assert result["validation"]["owner_resolution_batch"] == expected_marker
    assert result["validation"]["owner_resolution_batch_sha256"] == expected_marker["batch_sha256"]
    assert result["blockers"][0]["details"]["milestone_id"] == "CL8"
    assert store.get(result["run_id"])["validation"]["owner_resolution_batch"]["status"] == "APPLIED"


@pytest.mark.parametrize(
    "diagnostic",
    (
        _synthetic_diagnostic("CG1_BOUNDED_DECISION_REQUIRED", {"milestone_id": "CL4"}),
        _synthetic_diagnostic("CG1_STAGE2_INVALID", {"milestone_id": "CL8"}),
        _synthetic_diagnostic("CG1_BOUNDED_DECISION_REQUIRED", {"milestone_id": ""}),
    ),
    ids=("same-milestone", "unrelated-failure", "malformed-milestone"),
)
def test_non_successor_compile_failure_keeps_pending_batch(diagnostic: dict) -> None:
    service, _store, result, _run = _synthetic_owner_failure(diagnostic)
    rows = result["validation"]["owner_resolutions"]
    expected_marker = service._owner_resolution_batch_marker(
        rows,
        response_sha256=result["response"]["response_sha256"],
        status="PENDING",
    )
    assert result["validation"]["owner_resolution_batch"] == expected_marker
    assert result["validation"]["owner_resolution_batch_sha256"] == expected_marker["batch_sha256"]
    assert result["blockers"] == [diagnostic]


def test_applied_batch_exposes_next_milestone_for_new_owner_resolution() -> None:
    diagnostic = _synthetic_diagnostic(
        "CG1_BOUNDED_DECISION_REQUIRED",
        _cl8_blocker_details(),
    )
    service, store, applied, _run = _synthetic_owner_failure(diagnostic)
    details = applied["blockers"][0]["details"]
    value = {
        "kind": "cultivation_insight_acquisition",
        "milestone_id": "CL8",
        "insight_id": "insight.synthetic.cl8",
        "parameters": {"ability": "WIS"},
    }
    decision_id = service._owner_decision_id(
        applied,
        field=details["field"],
        slot_id=None,
        operation="set_milestone_choice",
        blocker_sha256=sha256_json(details),
    )
    retry_calls: list[dict] = []

    def retry(_run_id, *, _owner_decision_authorization=None):
        retry_calls.append(deepcopy(_owner_decision_authorization))
        return store.get(applied["run_id"])

    service.retry_local_build = retry
    result = service.resolve_owner_decision(
        applied["run_id"],
        decision_id=decision_id,
        field=details["field"],
        slot_id=None,
        operation="set_milestone_choice",
        target_value=None,
        value=value,
        request_sha256=applied["request"]["request_sha256"],
        response_sha256=applied["response"]["response_sha256"],
        content_lock_hash=applied["request"]["content_lock_hash"],
    )

    rows = result["validation"]["owner_resolutions"]
    assert len(rows) == 2
    assert rows[-1]["value"] == value
    assert rows[-1]["binding"]["response_sha256"] == applied["response"]["response_sha256"]
    assert result["validation"]["owner_resolution_batch"]["status"] == "PENDING"
    assert len(retry_calls) == 1
    assert retry_calls[0]["resolution_count"] == 2


def test_pre_fix_pending_successor_promotes_then_appends_new_pending_batch() -> None:
    service, store, run, _diagnostic, value, decision_id = _synthetic_pre_fix_successor_fixture()
    retry_calls: list[dict] = []

    def retry(_run_id, *, _owner_decision_authorization=None):
        retry_calls.append(deepcopy(_owner_decision_authorization))
        return store.get(run["run_id"])

    service.retry_local_build = retry
    result = service.resolve_owner_decision(
        run["run_id"],
        decision_id=decision_id,
        field=_cl8_blocker_details()["field"],
        slot_id=None,
        operation="set_milestone_choice",
        target_value=None,
        value=value,
        request_sha256=run["request"]["request_sha256"],
        response_sha256=run["response"]["response_sha256"],
        content_lock_hash=run["request"]["content_lock_hash"],
    )

    persisted = store.get(run["run_id"])
    rows = persisted["validation"]["owner_resolutions"]
    assert len(rows) == 2
    assert rows[0]["value"]["milestone_id"] == "CL4"
    assert rows[1]["value"] == value
    assert persisted["validation"]["owner_resolution_batch"]["status"] == "PENDING"
    assert persisted["blockers"] == [
        {"code": "CG1_BOUNDED_DECISION_REQUIRED", "details": _cl8_blocker_details(),
         "message": "Synthetic bounded compile failure.", "schema": "TianxiaFoundry.CharacterCreationDiagnostic.v2",
         "stage": "LEGALITY", "category": "LEGALITY", "boundary": "LEGALITY",
         "json_parsed": True, "response_retained": True}
    ]
    assert result["validation"]["owner_resolution_batch"]["status"] == "PENDING"
    assert len(retry_calls) == 1
    assert retry_calls[0]["resolution_count"] == 2


@pytest.mark.parametrize(
    "mutation",
    ("wrong-decision", "illegal-value", "wrong-milestone", "ambiguous-blocker"),
)
def test_pre_fix_successor_migration_rejects_forged_or_ambiguous_control(mutation: str) -> None:
    service, store, run, diagnostic, value, decision_id = _synthetic_pre_fix_successor_fixture()
    if mutation == "wrong-decision":
        decision_id += ".stale"
    elif mutation == "illegal-value":
        value = deepcopy(value)
        value["insight_id"] = "insight.synthetic.not-offered"
    elif mutation == "wrong-milestone":
        value = deepcopy(value)
        value["milestone_id"] = "CL4"
    else:
        run["blockers"].append(deepcopy(diagnostic))
        store.connection.execute(
            "UPDATE character_creation_runs SET blockers_json=? WHERE run_id=?",
            (canonical_json(run["blockers"]), run["run_id"]),
        )
        store.connection.commit()
    before = store.get(run["run_id"])
    persist_calls: list[dict] = []
    retry_calls: list[dict] = []

    def forbidden_persist(*args, **kwargs):
        persist_calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError("an invalid successor control must not append a new owner row")

    def forbidden_retry(*args, **kwargs):
        retry_calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError("an invalid successor control must not retry the build")

    service._persist_owner_resolution_pending = forbidden_persist
    service.retry_local_build = forbidden_retry
    with pytest.raises(FoundryError) as exc_info:
        service.resolve_owner_decision(
            run["run_id"],
            decision_id=decision_id,
            field=_cl8_blocker_details()["field"],
            slot_id=None,
            operation="set_milestone_choice",
            target_value=None,
            value=value,
            request_sha256=run["request"]["request_sha256"],
            response_sha256=run["response"]["response_sha256"],
            content_lock_hash=run["request"]["content_lock_hash"],
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "CG1_OWNER_DECISION_AUTHORIZATION_INVALID"
    assert persist_calls == []
    assert retry_calls == []
    assert store.get(run["run_id"]) == before


@pytest.mark.parametrize("mutation", ("bad-marker", "bad-binding", "terminal"))
def test_pre_fix_successor_migration_rejects_invalid_batch_without_promotion(mutation: str) -> None:
    service, store, run, _diagnostic, value, decision_id = _synthetic_pre_fix_successor_fixture()
    if mutation == "bad-marker":
        run["validation"]["owner_resolution_batch_sha256"] = "d" * 64
        store.connection.execute(
            "UPDATE character_creation_runs SET validation_json=? WHERE run_id=?",
            (canonical_json(run["validation"]), run["run_id"]),
        )
        store.connection.commit()
    elif mutation == "bad-binding":
        run["validation"]["owner_resolutions"][0]["binding"]["content_lock_hash"] = "d" * 64
        store.connection.execute(
            "UPDATE character_creation_runs SET validation_json=? WHERE run_id=?",
            (canonical_json(run["validation"]), run["run_id"]),
        )
        store.connection.commit()
    else:
        run["status"] = "CANCELLED"
        store.connection.execute(
            "UPDATE character_creation_runs SET status=? WHERE run_id=?",
            (run["status"], run["run_id"]),
        )
        store.connection.commit()
    before = store.get(run["run_id"])
    with pytest.raises(FoundryError) as exc_info:
        service.resolve_owner_decision(
            run["run_id"],
            decision_id=decision_id,
            field=_cl8_blocker_details()["field"],
            slot_id=None,
            operation="set_milestone_choice",
            target_value=None,
            value=value,
            request_sha256=run["request"]["request_sha256"],
            response_sha256=run["response"]["response_sha256"],
            content_lock_hash=run["request"]["content_lock_hash"],
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code in {
        "CG1_DECISION_TERMINAL",
        "CG1_OWNER_DECISION_AUTHORIZATION_INVALID",
    }
    assert store.get(run["run_id"]) == before


@pytest.mark.parametrize("mutation", ("row-project", "request-project"))
def test_pre_fix_successor_migration_rejects_project_identity_drift(mutation: str) -> None:
    service, store, run, _diagnostic, value, decision_id = _synthetic_pre_fix_successor_fixture()
    if mutation == "row-project":
        store.connection.execute(
            "UPDATE character_creation_runs SET project_id=? WHERE run_id=?",
            ("project.synthetic.other", run["run_id"]),
        )
    else:
        request = deepcopy(run["request"])
        request["project_id"] = "project.synthetic.other"
        store.connection.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(request), run["run_id"]),
        )
    store.connection.commit()
    before = store.get(run["run_id"])
    with pytest.raises(FoundryError) as exc_info:
        service.resolve_owner_decision(
            run["run_id"],
            decision_id=decision_id,
            field=_cl8_blocker_details()["field"],
            slot_id=None,
            operation="set_milestone_choice",
            target_value=None,
            value=value,
            request_sha256=run["request"]["request_sha256"],
            response_sha256=run["response"]["response_sha256"],
            content_lock_hash=run["request"]["content_lock_hash"],
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code in {
        "CG1_DECISION_BINDING_MISMATCH",
        "CG1_OWNER_DECISION_AUTHORIZATION_INVALID",
    }
    assert store.get(run["run_id"]) == before


def test_applied_race_is_idempotent_before_new_successor_resolution() -> None:
    service, store, run, _diagnostic, value, decision_id = _synthetic_pre_fix_successor_fixture()
    original_rows = deepcopy(run["validation"]["owner_resolutions"])
    real_promote = service._promote_owner_resolution_batch_for_restart
    retry_calls: list[dict] = []

    def race_to_applied(*args, **kwargs):
        current = store.get(run["run_id"])
        validation = current["validation"]
        rows = validation["owner_resolutions"]
        validation["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            rows,
            response_sha256=current["response"]["response_sha256"],
            status="APPLIED",
        )
        validation["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256(rows)
        store.connection.execute(
            "UPDATE character_creation_runs SET validation_json=? WHERE run_id=?",
            (canonical_json(validation), run["run_id"]),
        )
        store.connection.commit()
        return real_promote(*args, **kwargs)

    service._promote_owner_resolution_batch_for_restart = race_to_applied
    service.retry_local_build = lambda _run_id, *, _owner_decision_authorization=None: (
        retry_calls.append(deepcopy(_owner_decision_authorization)) or store.get(_run_id)
    )
    result = service.resolve_owner_decision(
        run["run_id"],
        decision_id=decision_id,
        field=_cl8_blocker_details()["field"],
        slot_id=None,
        operation="set_milestone_choice",
        target_value=None,
        value=value,
        request_sha256=run["request"]["request_sha256"],
        response_sha256=run["response"]["response_sha256"],
        content_lock_hash=run["request"]["content_lock_hash"],
    )

    persisted = store.get(run["run_id"])
    assert persisted["validation"]["owner_resolutions"][0] == original_rows[0]
    assert persisted["validation"]["owner_resolutions"][1]["value"] == value
    assert persisted["validation"]["owner_resolution_batch"]["status"] == "PENDING"
    assert result["validation"]["owner_resolutions"][0] == original_rows[0]
    assert len(retry_calls) == 1


@pytest.mark.parametrize("mutation", ("duplicate", "different-value", "wrong-decision"))
def test_valid_pending_batch_rejects_unmatched_control_without_fallthrough(mutation: str) -> None:
    service, run, value, current_decision_id, _response_text = _fixture()
    rows = run["validation"]["owner_resolutions"]
    if mutation == "duplicate":
        duplicate = deepcopy(rows[0])
        duplicate["decision_id"] = "cg1.decision.duplicate-cl4"
        rows.append(duplicate)
        run["validation"]["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            rows,
            response_sha256=run["response"]["response_sha256"],
            status="PENDING",
        )
        run["validation"]["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256(rows)
    elif mutation == "different-value":
        value = deepcopy(value)
        value["insight_id"] = "insight.synthetic.not-offered"
    else:
        current_decision_id = f"{current_decision_id}.stale"
    before = deepcopy(run)

    persisted_calls: list[dict] = []
    retry_calls: list[dict] = []
    service.get = lambda _run_id: deepcopy(run)

    def unexpected_persist(*args, **kwargs):
        persisted_calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError("an unmatched control must not persist a pending resolution")

    def unexpected_retry(*args, **kwargs):
        retry_calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError("an unmatched control must not retry the build")

    service._persist_owner_resolution_pending = unexpected_persist
    service.retry_local_build = unexpected_retry
    with pytest.raises(FoundryError) as exc_info:
        service.resolve_owner_decision(
            run["run_id"],
            decision_id=current_decision_id,
            field="owner decision",
            slot_id=None,
            operation="set_milestone_choice",
            target_value=None,
            value=value,
            request_sha256=run["request"]["request_sha256"],
            response_sha256=run["response"]["response_sha256"],
            content_lock_hash=run["request"]["content_lock_hash"],
        )

    assert exc_info.value.code == "CG1_OWNER_DECISION_AUTHORIZATION_INVALID"
    assert exc_info.value.status_code == 409
    assert persisted_calls == []
    assert retry_calls == []
    assert run == before


@pytest.mark.parametrize(
    "mutation",
    ("wrong_decision", "different_value", "bad_marker", "bad_binding", "duplicate", "empty", "applied", "legacy"),
)
def test_restart_resume_authority_rejects_stale_or_malformed_batches(mutation: str) -> None:
    service, run, value, current_decision_id, response_text = _fixture()
    validation = run["validation"]
    rows = validation["owner_resolutions"]
    if mutation == "wrong_decision":
        current_decision_id += ".stale"
    elif mutation == "different_value":
        value = deepcopy(value)
        value["insight_id"] = "insight.synthetic.other"
    elif mutation == "bad_marker":
        validation["owner_resolution_batch_sha256"] = "d" * 64
    elif mutation == "bad_binding":
        rows[0]["binding"]["content_lock_hash"] = "d" * 64
        validation["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            rows, response_sha256=run["response"]["response_sha256"], status="PENDING"
        )
        validation["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256(rows)
    elif mutation == "duplicate":
        duplicate = deepcopy(rows[0])
        duplicate["decision_id"] = "cg1.decision.duplicate-cl4"
        rows.append(duplicate)
        validation["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            rows, response_sha256=run["response"]["response_sha256"], status="PENDING"
        )
        validation["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256(rows)
    elif mutation == "empty":
        validation["owner_resolutions"] = []
        validation["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            [], response_sha256=run["response"]["response_sha256"], status="PENDING"
        )
        validation["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256([])
    elif mutation == "applied":
        validation["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            rows, response_sha256=run["response"]["response_sha256"], status="APPLIED"
        )
    elif mutation == "legacy":
        validation.pop("owner_resolution_batch")
        validation.pop("owner_resolution_batch_sha256")

    batch_invalid = mutation in {"bad_marker", "bad_binding", "empty", "applied", "legacy"}
    if batch_invalid:
        assert service._owner_decision_authorization_for_pending_retry(run, response_text) is None
    else:
        assert service._owner_decision_authorization_for_pending_retry(run, response_text) is not None
    assert service._owner_resolution_for_restart_control(
        run,
        decision_id=current_decision_id,
        field="owner decision",
        slot_id=None,
        operation="set_milestone_choice",
        target_value=None,
        value=value,
        response_text=response_text,
    ) is None


def _clean_pending_finalization_fixture() -> tuple[
    CharacterCreationExecutionService,
    dict,
    str,
    str,
]:
    service, run, _value, _decision_id, response_text = _fixture()
    run["status"] = "READY_FOR_REVIEW"
    run["quality"] = {"status": "CLEAN"}
    run["blockers"] = []
    run["starting_revision"] = 0
    run["request"]["project_revision"] = 0
    run["request"]["request_sha256"] = service.request_payload_sha256(run["request"])
    for row in run["validation"]["owner_resolutions"]:
        row["binding"]["request_sha256"] = run["request"]["request_sha256"]
    rows = run["validation"]["owner_resolutions"]
    run["validation"]["owner_resolution_batch"] = service._owner_resolution_batch_marker(
        rows,
        response_sha256=run["response"]["response_sha256"],
        status="PENDING",
    )
    run["validation"]["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256(rows)
    parsed_plan = json.loads(response_text)
    run["validation"]["plan_sha256"] = sha256_json(parsed_plan)
    run["final_plan"] = {
        "plan_sha256": sha256_json(parsed_plan),
        "response_sha256": run["response"]["response_sha256"],
        "request_sha256": run["request"]["request_sha256"],
        "immutable_after_validation": True,
    }
    run["final_plan"]["final_plan_sha256"] = final_plan_sha256(run["final_plan"])
    # The fixture intentionally has no owner-facing unresolved rows.  The
    # production finalization gate derives this from the persisted plan; this
    # stub keeps the unit fixture focused on the pending-batch capability.
    service._unresolved_owner_authority = lambda _run: []
    service._revision = lambda _project_id: 0
    service._content_lock_hash = lambda _project_id: run["request"]["content_lock_hash"]
    return service, run, response_text, sha256_json(run["final_plan"])


def test_explicit_finalize_recovers_exact_pending_batch_before_candidate_gate() -> None:
    service, run, response_text, final_plan_identity = _clean_pending_finalization_fixture()
    service.owner_principal = "owner.synthetic"
    stored = deepcopy(run)
    retry_authorizations: list[dict] = []
    suppress_auto_finalize: list[bool] = []

    def get(_run_id: str) -> dict:
        return deepcopy(stored)

    def retry(
        _run_id: str,
        *,
        _owner_decision_authorization=None,
        _suppress_auto_finalize=False,
    ) -> dict:
        retry_authorizations.append(_owner_decision_authorization)
        suppress_auto_finalize.append(_suppress_auto_finalize)
        stored["validation"]["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            stored["validation"]["owner_resolutions"],
            response_sha256=stored["response"]["response_sha256"],
            status="APPLIED",
        )
        stored["validation"]["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256(
            stored["validation"]["owner_resolutions"]
        )
        return deepcopy(stored)

    class ReachedCandidateGate(Exception):
        pass

    service.get = get
    service.retry_local_build = retry
    service._require_owner_decisions_resolved = lambda _run: None
    service._has_delegated_envelope = lambda _run: False
    service._revision = lambda _project_id: 0
    service._content_lock_hash = lambda _project_id: run["request"]["content_lock_hash"]
    service._parse_plan = lambda _text, **_kwargs: (json.loads(response_text), response_text.encode("utf-8"))
    service._apply_owner_resolutions = lambda _run, plan: deepcopy(plan)
    service._approved_candidate_for_finalization = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        ReachedCandidateGate()
    )

    with pytest.raises(ReachedCandidateGate):
        service._finalize_locked(run["run_id"])

    assert len(retry_authorizations) == 1
    assert isinstance(retry_authorizations[0], dict)
    assert retry_authorizations[0]["run_id"] == run["run_id"]
    assert suppress_auto_finalize == [True]
    assert stored["validation"]["owner_resolution_batch"]["status"] == "APPLIED"
    assert sha256_json(stored["final_plan"]) == final_plan_identity
    assert stored["response"]["exact_response_text"] == response_text


@pytest.mark.parametrize("mutation", ("bad_binding", "bad_marker", "duplicate"))
def test_finalization_does_not_retry_malformed_pending_batch(mutation: str) -> None:
    service, run, response_text, final_plan_identity = _clean_pending_finalization_fixture()
    rows = run["validation"]["owner_resolutions"]
    if mutation == "bad_binding":
        rows[0]["binding"]["response_sha256"] = "d" * 64
        run["validation"]["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            rows,
            response_sha256=run["response"]["response_sha256"],
            status="PENDING",
        )
        run["validation"]["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256(rows)
    elif mutation == "bad_marker":
        run["validation"]["owner_resolution_batch_sha256"] = "d" * 64
    else:
        duplicate = deepcopy(rows[0])
        duplicate["decision_id"] = rows[0]["decision_id"]
        rows.append(duplicate)
        run["validation"]["owner_resolution_batch"] = service._owner_resolution_batch_marker(
            rows,
            response_sha256=run["response"]["response_sha256"],
            status="PENDING",
        )
        run["validation"]["owner_resolution_batch_sha256"] = service._owner_resolution_batch_sha256(rows)
    before = deepcopy(run)
    retry_calls: list[object] = []
    service.retry_local_build = lambda *_args, **_kwargs: retry_calls.append(True)

    if mutation == "bad_marker":
        result = service._recover_pending_owner_resolution_for_finalization(
            run,
            response_text=response_text,
            response_sha256=run["response"]["response_sha256"],
            final_plan_identity_sha256=final_plan_identity,
        )
        assert result is run
    else:
        with pytest.raises(FoundryError) as exc_info:
            service._recover_pending_owner_resolution_for_finalization(
                run,
                response_text=response_text,
                response_sha256=run["response"]["response_sha256"],
                final_plan_identity_sha256=final_plan_identity,
            )
        assert exc_info.value.code == "CG1_OWNER_DECISION_AUTHORIZATION_INVALID"
    assert retry_calls == []
    assert run == before


def test_finalization_leaves_already_applied_batch_untouched() -> None:
    service, run, response_text, final_plan_identity = _clean_pending_finalization_fixture()
    rows = run["validation"]["owner_resolutions"]
    run["validation"]["owner_resolution_batch"] = service._owner_resolution_batch_marker(
        rows,
        response_sha256=run["response"]["response_sha256"],
        status="APPLIED",
    )
    before = deepcopy(run)
    retry_calls: list[object] = []
    service.retry_local_build = lambda *_args, **_kwargs: retry_calls.append(True)

    result = service._recover_pending_owner_resolution_for_finalization(
        run,
        response_text=response_text,
        response_sha256=run["response"]["response_sha256"],
        final_plan_identity_sha256=final_plan_identity,
    )

    assert result is run
    assert retry_calls == []
    assert run == before


def test_retry_forwards_auto_finalize_suppression_to_each_apply_branch() -> None:
    service, run, _value, _decision_id, response_text = _fixture()
    service.get = lambda _run_id: deepcopy(run)
    service._latest_attempt_id = lambda _run_id: "attempt.synthetic.current"
    service._provider_selected_id = lambda: None
    service._legacy_retry_bypass_context = lambda *_args, **_kwargs: None
    service._provider_target_scoped_repair_target = lambda *_args, **_kwargs: None
    captured: list[dict] = []

    def apply(*_args, **kwargs):
        captured.append(kwargs)
        return {"captured": True}

    service._apply_response = apply
    service._recover_scoped_local_correction_context = lambda *_args, **_kwargs: (None, None)
    service.retry_local_build(run["run_id"])
    assert captured[-1]["_suppress_auto_finalize"] is False

    recovered = {
        "response_text": response_text,
        "response_sha256": sha256_bytes(response_text.encode("utf-8")),
        "diagnostic": {"code": "CG1_PLAN_JSON_INVALID"},
        "recovered_from_attempt_id": "attempt.synthetic.prior",
        "restored_attempt_id": "attempt.synthetic.restored",
    }
    service._recover_scoped_local_correction_context = lambda *_args, **_kwargs: (True, recovered)
    service.retry_local_build(run["run_id"], _suppress_auto_finalize=True)
    assert captured[-1]["_suppress_auto_finalize"] is True


def test_finalization_recovery_rejects_project_revision_or_lock_change_after_retry() -> None:
    service, run, response_text, final_plan_identity = _clean_pending_finalization_fixture()
    stored = deepcopy(run)
    revision = 0
    content_lock_hash = run["request"]["content_lock_hash"]
    retry_calls: list[dict] = []

    def get(_run_id: str) -> dict:
        return deepcopy(stored)

    def current_revision(_project_id: str) -> int:
        return revision

    def current_content_lock(_project_id: str) -> str:
        return content_lock_hash

    def retry(
        _run_id: str,
        *,
        _owner_decision_authorization=None,
        _suppress_auto_finalize=False,
    ) -> dict:
        nonlocal revision, content_lock_hash
        retry_calls.append(_owner_decision_authorization)
        revision = 1
        content_lock_hash = "d" * 64
        return deepcopy(stored)

    service.get = get
    service._revision = current_revision
    service._content_lock_hash = current_content_lock
    service.retry_local_build = retry

    with pytest.raises(FoundryError) as exc_info:
        service._recover_pending_owner_resolution_for_finalization(
            run,
            response_text=response_text,
            response_sha256=run["response"]["response_sha256"],
            final_plan_identity_sha256=final_plan_identity,
        )

    assert exc_info.value.code == "CG1_OWNER_DECISION_AUTHORIZATION_INVALID"
    assert len(retry_calls) == 1
    assert stored["validation"]["owner_resolution_batch"]["status"] == "PENDING"
