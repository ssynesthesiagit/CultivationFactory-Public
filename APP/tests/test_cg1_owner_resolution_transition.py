from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.core import FoundryError, canonical_json, sha256_bytes
from test_cg1_character_creation_modes import make
import test_cg1_character_creation_modes as _cg1_modes


@pytest.fixture(autouse=True)
def _pinned_cg1_vendor(factory_environment, monkeypatch):
    # make() builds its settings from the cg1 modes module's pinned vendor
    # directory, which that module's own autouse fixture sets only for its
    # own tests; without it start() cannot find the pinned compiler authority.
    monkeypatch.setattr(_cg1_modes, "_PINNED_VENDOR_DIR", Path(factory_environment["settings"].vendor_dir))


FIELD = "insight_priorities"
SLOT = "insight_priorities"
VALUE = "insight.body-as-cauldron"


def _prime_unresolved_owner_decision(svc, db, run):
    details = {
        "field": FIELD,
        "slot_id": SLOT,
        "operation": "add_slot_value",
        "allowed_choice_ids": [VALUE],
    }
    final_plan = deepcopy(run["final_plan"])
    resolution = final_plan.setdefault("resolution", {})
    provenance = resolution.setdefault("provenance", [])
    provenance.append({"field": FIELD, "slot_id": SLOT, "status": "unresolved"})
    blocker = {
        "code": "CG1_OWNER_DECISION_REQUIRED",
        "message": "Choose the unresolved Insight priority.",
        "details": details,
    }
    with db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET final_plan_json=?,blockers_json=?,status='NEEDS_REVIEW',updated_at=? WHERE run_id=?",
            (canonical_json(final_plan), canonical_json([blocker]), run["updated_at"], run["run_id"]),
        )
    return svc.get(run["run_id"]), details


def _decision_args(svc, run, details):
    blocker_sha256 = sha256_bytes(canonical_json(details).encode("utf-8"))
    decision_id = svc._owner_decision_id(
        run,
        field=FIELD,
        slot_id=SLOT,
        operation="add_slot_value",
        blocker_sha256=blocker_sha256,
    )
    return {
        "decision_id": decision_id,
        "field": FIELD,
        "slot_id": SLOT,
        "operation": "add_slot_value",
        "target_value": None,
        "value": VALUE,
        "request_sha256": run["request"]["request_sha256"],
        "response_sha256": run["response"]["response_sha256"],
        "content_lock_hash": run["request"]["content_lock_hash"],
    }


def _install_controlled_compile(svc, calls, *, fail_first=False, before_failure=None, before_return=None):
    def compile_controlled(run, response_text, **kwargs):
        authorized = bool(kwargs.get("owner_resolution_transition_authorized"))
        calls.append(authorized)
        if fail_first and len(calls) == 1:
            if before_failure is not None:
                before_failure(run)
            raise FoundryError("CG1_STAGE2_INVALID", "controlled blocked build")
        plan = json.loads(response_text)
        final_plan = deepcopy(run["final_plan"])
        if authorized or (run.get("validation") or {}).get("owner_resolutions"):
            final_plan.setdefault("resolution", {})["selected_choices_by_slot"] = {SLOT: [VALUE]}
        resolutions = deepcopy((run.get("validation") or {}).get("owner_resolutions") or [])
        response_sha256 = sha256_bytes(response_text.encode("utf-8"))
        batch_sha256 = svc._owner_resolution_batch_sha256(resolutions)
        validation = {
            "valid": True,
            "response_sha256": response_sha256,
            "plan_sha256": sha256_bytes(canonical_json(plan).encode("utf-8")),
            "owner_resolutions": resolutions,
            "owner_resolution_batch": svc._owner_resolution_batch_marker(
                resolutions,
                response_sha256=response_sha256,
                status="APPLIED" if authorized else "PENDING",
            ),
            "owner_resolution_batch_sha256": batch_sha256,
            "response_state": {"exact_response_retained": True, "compiled": True},
        }
        result = {
            "plan": plan,
            "final_plan": final_plan,
            "validation": validation,
            "candidate": {"candidate_identity": "controlled-candidate"},
            "quality": {"status": "CLEAN", "candidate_identity": "controlled-candidate"},
            "warnings": [],
            "raw_sha256": response_sha256,
            "canonical_intent": None,
        }
        if before_return is not None:
            before_return(run, result)
        return result

    svc._validate_and_compile = compile_controlled


def _resolution_from_args(args, details, run_id):
    return {
        "schema": "TianxiaFoundry.OwnerDecisionResolution.v1",
        "decision_id": args["decision_id"],
        "field": args["field"],
        "slot_id": args["slot_id"],
        "operation": args["operation"],
        "target_value": args["target_value"],
        "value": args["value"],
        "binding": {
            "run_id": run_id,
            "request_sha256": args["request_sha256"],
            "response_sha256": args["response_sha256"],
            "content_lock_hash": args["content_lock_hash"],
            "blocker_sha256": sha256_bytes(canonical_json(details).encode("utf-8")),
        },
    }


def _start_primed(tmp_path):
    svc, _, db = make(tmp_path)
    run = svc.start("p", execution_mode="STANDARD_API", idempotency_key="owner-transition-123")
    return svc, db, *_prime_unresolved_owner_decision(svc, db, run)


def test_owner_resolution_transition_applies_same_response_and_is_idempotent(tmp_path):
    svc, db, run, details = _start_primed(tmp_path / "applied")
    calls = []
    _install_controlled_compile(svc, calls)
    args = _decision_args(svc, run, details)

    applied = svc.resolve_owner_decision(run["run_id"], **args)

    assert calls == [True]
    assert applied["final_plan"]["resolution"]["selected_choices_by_slot"][SLOT] == [VALUE]
    marker = applied["validation"]["owner_resolution_batch"]
    assert marker["status"] == "APPLIED"
    assert marker["batch_sha256"] == applied["validation"]["owner_resolution_batch_sha256"]
    attempt_count = len(applied["attempt_history"])

    duplicate = svc.resolve_owner_decision(applied["run_id"], **args)

    assert calls == [True]
    assert len(duplicate["attempt_history"]) == attempt_count
    assert duplicate["validation"]["owner_resolution_batch"]["status"] == "APPLIED"


def test_pending_owner_resolution_duplicate_retries_authorized_build(tmp_path):
    svc, db, run, details = _start_primed(tmp_path / "pending")
    calls = []
    _install_controlled_compile(svc, calls, fail_first=True)
    args = _decision_args(svc, run, details)

    blocked = svc.resolve_owner_decision(run["run_id"], **args)

    assert calls == [True]
    assert blocked["validation"]["owner_resolution_batch"]["status"] == "PENDING"
    assert blocked["validation"]["owner_resolutions"]

    retried = svc.resolve_owner_decision(blocked["run_id"], **args)

    assert calls == [True, True]
    assert retried["validation"]["owner_resolution_batch"]["status"] == "APPLIED"
    assert retried["final_plan"]["resolution"]["selected_choices_by_slot"][SLOT] == [VALUE]


def test_authorized_failure_preserves_newer_pending_batch(tmp_path):
    svc, db, run, details = _start_primed(tmp_path / "failure-newer-pending")
    calls = []
    args = _decision_args(svc, run, details)

    def publish_newer_pending(compiling_run):
        current = svc.get(compiling_run["run_id"])
        current_rows = deepcopy(current["validation"]["owner_resolutions"])
        newer = deepcopy(current_rows[0])
        newer["decision_id"] = "cg1.decision.newer-pending"
        newer["field"] = "item_priorities"
        newer["slot_id"] = "item_priorities"
        newer["value"] = "item.newer"
        newer["binding"]["blocker_sha256"] = "newer-blocker"
        rows = [*current_rows, newer]
        validation = deepcopy(current["validation"])
        validation["owner_resolutions"] = rows
        validation["owner_resolution_batch"] = svc._owner_resolution_batch_marker(
            rows,
            response_sha256=current["response"]["response_sha256"],
            status="PENDING",
        )
        validation["owner_resolution_batch_sha256"] = svc._owner_resolution_batch_sha256(rows)
        with db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_runs SET validation_json=? WHERE run_id=?",
                (canonical_json(validation), run["run_id"]),
            )

    _install_controlled_compile(svc, calls, fail_first=True, before_failure=publish_newer_pending)
    before = svc.get(run["run_id"])

    with pytest.raises(FoundryError) as exc:
        svc.resolve_owner_decision(run["run_id"], **args)

    assert exc.value.code == "CG1_OWNER_DECISION_AUTHORIZATION_INVALID"
    after = svc.get(run["run_id"])
    assert [row["decision_id"] for row in after["validation"]["owner_resolutions"]] == [
        args["decision_id"],
        "cg1.decision.newer-pending",
    ]
    assert after["validation"]["owner_resolution_batch"]["status"] == "PENDING"
    assert "last_submission_error" not in after["validation"]
    assert len(after["attempt_history"]) == len(before["attempt_history"])


def test_authorized_failure_after_applied_race_returns_without_diagnostic_or_attempt(tmp_path):
    svc, db, run, details = _start_primed(tmp_path / "failure-applied")
    calls = []
    args = _decision_args(svc, run, details)

    def publish_applied(compiling_run):
        current = svc.get(compiling_run["run_id"])
        rows = current["validation"]["owner_resolutions"]
        validation = deepcopy(current["validation"])
        validation["owner_resolution_batch"] = svc._owner_resolution_batch_marker(
            rows,
            response_sha256=current["response"]["response_sha256"],
            status="APPLIED",
        )
        validation["owner_resolution_batch_sha256"] = svc._owner_resolution_batch_sha256(rows)
        with db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_runs SET validation_json=? WHERE run_id=?",
                (canonical_json(validation), run["run_id"]),
            )

    _install_controlled_compile(svc, calls, fail_first=True, before_failure=publish_applied)
    before = svc.get(run["run_id"])
    result = svc.resolve_owner_decision(run["run_id"], **args)

    assert calls == [True]
    assert result["validation"]["owner_resolution_batch"]["status"] == "APPLIED"
    assert "last_submission_error" not in result["validation"]
    assert len(result["attempt_history"]) == len(before["attempt_history"])


def test_legacy_exact_resolution_is_promoted_to_pending_then_applied(tmp_path):
    svc, db, run, details = _start_primed(tmp_path / "legacy-marker")
    args = _decision_args(svc, run, details)
    resolution = _resolution_from_args(args, details, run["run_id"])
    validation = deepcopy(run["validation"])
    validation["owner_resolutions"] = [resolution]
    validation.pop("owner_resolution_batch", None)
    validation.pop("owner_resolution_batch_sha256", None)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET validation_json=? WHERE run_id=?",
            (canonical_json(validation), run["run_id"]),
        )
    calls = []
    _install_controlled_compile(svc, calls)

    result = svc.resolve_owner_decision(run["run_id"], **args)

    assert calls == [True]
    assert result["validation"]["owner_resolution_batch"]["status"] == "APPLIED"
    assert result["validation"]["owner_resolution_batch_sha256"] == svc._owner_resolution_batch_sha256([resolution])
    assert all(blocker["code"] != "CG1_FINAL_PLAN_IMMUTABLE" for blocker in result["blockers"])
    assert result["final_plan"]["resolution"]["selected_choices_by_slot"][SLOT] == [VALUE]


def _run_state(svc, run_id):
    view = svc.get(run_id)
    # The public view reports how long building that view took
    # (factory_ui_ready_response, e67e4e9e); it is per-request timing, not run
    # state, and differs between two reads on a loaded machine.
    view["timings"]["phases_ms"].pop("factory_ui_ready_response", None)
    return view


def _assert_markerless_owner_state_rejected(svc, db, run, details, owner_resolutions):
    validation = deepcopy(run["validation"])
    validation["owner_resolutions"] = owner_resolutions
    validation.pop("owner_resolution_batch", None)
    validation.pop("owner_resolution_batch_sha256", None)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET validation_json=? WHERE run_id=?",
            (canonical_json(validation), run["run_id"]),
        )
    before = svc.get(run["run_id"])
    args = _decision_args(svc, before, details)
    before = _run_state(svc, run["run_id"])

    with pytest.raises(FoundryError) as exc:
        svc.resolve_owner_decision(run["run_id"], **args)

    assert exc.value.code == "CG1_OWNER_DECISION_AUTHORIZATION_INVALID"
    assert _run_state(svc, run["run_id"]) == before


def test_markerless_non_list_owner_resolutions_fail_closed_without_mutation(tmp_path):
    svc, db, run, details = _start_primed(tmp_path / "legacy-non-list")

    _assert_markerless_owner_state_rejected(
        svc,
        db,
        run,
        details,
        {"decision_id": "not-a-list"},
    )


def test_markerless_non_dict_owner_resolution_entry_fails_closed_without_mutation(tmp_path):
    svc, db, run, details = _start_primed(tmp_path / "legacy-non-dict")
    args = _decision_args(svc, run, details)
    valid_resolution = _resolution_from_args(args, details, run["run_id"])

    _assert_markerless_owner_state_rejected(
        svc,
        db,
        run,
        details,
        [valid_resolution, "not-a-resolution"],
    )


def test_markerless_duplicate_conflicting_decision_ids_fail_closed_without_mutation(tmp_path):
    svc, db, run, details = _start_primed(tmp_path / "legacy-duplicate-id")
    args = _decision_args(svc, run, details)
    first = _resolution_from_args(args, details, run["run_id"])
    conflicting = deepcopy(first)
    conflicting["value"] = "insight.other-value"

    _assert_markerless_owner_state_rejected(
        svc,
        db,
        run,
        details,
        [first, conflicting],
    )


def test_generic_retry_cannot_replace_plan_for_pending_owner_resolution(tmp_path):
    svc, db, run, details = _start_primed(tmp_path / "generic-retry")
    calls = []
    _install_controlled_compile(svc, calls, fail_first=True)
    args = _decision_args(svc, run, details)

    blocked = svc.resolve_owner_decision(run["run_id"], **args)
    before_plan = deepcopy(blocked["final_plan"])
    generic_retry = svc.retry_local_build(blocked["run_id"])

    assert calls == [True, False]
    assert generic_retry["final_plan"] == before_plan
    assert generic_retry["validation"]["owner_resolution_batch"]["status"] == "PENDING"
    assert generic_retry["blockers"][-1]["code"] == "CG1_FINAL_PLAN_IMMUTABLE"


def test_owner_resolution_transition_keeps_changed_response_immutable(tmp_path):
    svc, _, _ = make(tmp_path / "changed-response")
    run = svc.start("p", execution_mode="STANDARD_API", idempotency_key="owner-change-123")
    changed = json.loads(run["response"]["exact_response_text"])
    changed["owner_descriptive_fields"]["concept"] = "changed response"

    with pytest.raises(FoundryError) as exc:
        svc._apply_response(
            run["run_id"],
            canonical_json(changed),
            {"mode": "STANDARD_API", "provider_called": True},
        )

    assert exc.value.code == "CG1_FINAL_PLAN_IMMUTABLE"


def test_stale_owner_writer_merges_current_distinct_resolution(tmp_path, monkeypatch):
    svc, db, run, details = _start_primed(tmp_path / "stale-merge")
    stale_run = deepcopy(run)
    calls = []
    _install_controlled_compile(svc, calls)
    args = _decision_args(svc, stale_run, details)

    # Simulate a newer owner decision having been durably applied after this
    # caller captured its public snapshot.  The second decision must extend
    # that current batch instead of writing the stale snapshot's empty list.
    other_resolution = {
        "schema": "TianxiaFoundry.OwnerDecisionResolution.v1",
        "decision_id": "cg1.decision.other-current",
        "field": "item_priorities",
        "slot_id": "item_priorities",
        "operation": "add_slot_value",
        "target_value": None,
        "value": "item.current",
        "binding": {
            "run_id": run["run_id"],
            "request_sha256": run["request"]["request_sha256"],
            "response_sha256": run["response"]["response_sha256"],
            "content_lock_hash": run["request"]["content_lock_hash"],
            "blocker_sha256": "current-blocker",
        },
    }
    current_validation = deepcopy(run["validation"])
    current_validation["owner_resolutions"] = [other_resolution]
    current_validation["owner_resolution_batch"] = svc._owner_resolution_batch_marker(
        [other_resolution],
        response_sha256=run["response"]["response_sha256"],
        status="APPLIED",
    )
    current_validation["owner_resolution_batch_sha256"] = svc._owner_resolution_batch_sha256([other_resolution])
    with db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET validation_json=? WHERE run_id=?",
            (canonical_json(current_validation), run["run_id"]),
        )

    real_get = svc.get
    returned = 0

    def stale_once(run_id):
        nonlocal returned
        returned += 1
        return stale_run if returned == 1 else real_get(run_id)

    monkeypatch.setattr(svc, "get", stale_once)
    merged = svc.resolve_owner_decision(run["run_id"], **args)

    decision_ids = [row["decision_id"] for row in merged["validation"]["owner_resolutions"]]
    assert decision_ids == [other_resolution["decision_id"], args["decision_id"]]
    assert merged["validation"]["owner_resolution_batch"]["status"] == "APPLIED"
    assert calls == [True]


def test_stale_owner_writer_rejects_request_rebind_without_persisting_pending(tmp_path, monkeypatch):
    svc, db, run, details = _start_primed(tmp_path / "rebind")
    stale_run = deepcopy(run)
    args = _decision_args(svc, stale_run, details)
    real_get = svc.get
    returned = 0

    def stale_then_rebind(run_id):
        nonlocal returned
        returned += 1
        if returned == 1:
            rebound_request = deepcopy(run["request"])
            rebound_request["request_sha256"] = "rebound-request-sha256"
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
                    (canonical_json(rebound_request), run_id),
                )
            return stale_run
        return real_get(run_id)

    monkeypatch.setattr(svc, "get", stale_then_rebind)
    with pytest.raises(FoundryError) as exc:
        svc.resolve_owner_decision(run["run_id"], **args)

    assert exc.value.code == "CG1_DECISION_BINDING_MISMATCH"
    rebound = real_get(run["run_id"])
    assert not rebound["validation"].get("owner_resolutions")
    assert "owner_resolution_batch" not in rebound["validation"]


def test_stale_duplicate_cannot_demote_applied_batch_or_add_attempt(tmp_path, monkeypatch):
    svc, db, run, details = _start_primed(tmp_path / "stale-applied")
    stale_run = deepcopy(run)
    args = _decision_args(svc, stale_run, details)
    resolution = {
        "schema": "TianxiaFoundry.OwnerDecisionResolution.v1",
        "decision_id": args["decision_id"],
        "field": args["field"],
        "slot_id": args["slot_id"],
        "operation": args["operation"],
        "target_value": args["target_value"],
        "value": args["value"],
        "binding": {
            "run_id": run["run_id"],
            "request_sha256": args["request_sha256"],
            "response_sha256": args["response_sha256"],
            "content_lock_hash": args["content_lock_hash"],
            "blocker_sha256": sha256_bytes(canonical_json(details).encode("utf-8")),
        },
    }
    current_validation = deepcopy(run["validation"])
    current_validation["owner_resolutions"] = [resolution]
    current_validation["owner_resolution_batch"] = svc._owner_resolution_batch_marker(
        [resolution],
        response_sha256=args["response_sha256"],
        status="APPLIED",
    )
    current_validation["owner_resolution_batch_sha256"] = svc._owner_resolution_batch_sha256([resolution])
    with db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET validation_json=? WHERE run_id=?",
            (canonical_json(current_validation), run["run_id"]),
        )
    calls = []
    _install_controlled_compile(svc, calls)
    real_get = svc.get
    returned = 0

    def stale_once(run_id):
        nonlocal returned
        returned += 1
        return stale_run if returned == 1 else real_get(run_id)

    monkeypatch.setattr(svc, "get", stale_once)
    before = real_get(run["run_id"])
    duplicate = svc.resolve_owner_decision(run["run_id"], **args)

    assert calls == []
    assert len(duplicate["attempt_history"]) == len(before["attempt_history"])
    assert duplicate["validation"]["owner_resolution_batch"]["status"] == "APPLIED"
    assert duplicate["validation"]["owner_resolutions"] == [resolution]


def test_applied_commit_race_returns_persisted_run_without_new_attempt(tmp_path):
    svc, db, run, details = _start_primed(tmp_path / "applied-race")
    calls = []

    def mark_applied_before_final_commit(compiling_run, result):
        current = svc.get(compiling_run["run_id"])
        rows = current["validation"]["owner_resolutions"]
        validation = deepcopy(current["validation"])
        validation["owner_resolution_batch"] = svc._owner_resolution_batch_marker(
            rows,
            response_sha256=current["response"]["response_sha256"],
            status="APPLIED",
        )
        validation["owner_resolution_batch_sha256"] = svc._owner_resolution_batch_sha256(rows)
        with db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_runs SET validation_json=?,final_plan_json=? WHERE run_id=?",
                (canonical_json(validation), canonical_json(result["final_plan"]), compiling_run["run_id"]),
            )

    _install_controlled_compile(svc, calls, before_return=mark_applied_before_final_commit)
    args = _decision_args(svc, run, details)
    before = svc.get(run["run_id"])
    result = svc.resolve_owner_decision(run["run_id"], **args)

    assert calls == [True]
    assert len(result["attempt_history"]) == len(before["attempt_history"])
    assert result["validation"]["owner_resolution_batch"]["status"] == "APPLIED"
