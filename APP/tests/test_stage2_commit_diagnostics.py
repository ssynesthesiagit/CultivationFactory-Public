from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core import FoundryError, canonical_json, sha256_json
from stage2.service import EVENT_V3, RulesCausalStage2Service


PAYLOAD_SENTINEL = "OWNER_PAYLOAD_SENTINEL_SHOULD_NOT_LEAK"


class EmptyAuthorityBoundaryError(RuntimeError):
    pass


def _seed_commit_rows(db, *, project_id: str, proposal_id: str, attempt_id: str, binding_set_hash: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(
                project_id,working_name,status,revision,created_at,updated_at,
                target_factory_version,target_candidate_schema_version,target_gm_screen_version,
                catalog_build_hash,quality_target,project_json,compatibility_projection_status,
                compile_status,consumer_verification_status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                project_id,
                "diagnostic project",
                "stage_1",
                0,
                "2026-08-17T00:00:00Z",
                "2026-08-17T00:00:00Z",
                "factory",
                "candidate",
                "gm",
                None,
                "standard",
                canonical_json({"project_id": project_id, "revision": 0}),
                "not_started",
                "not_started",
                "not_started",
            ),
        )
        conn.execute(
            """INSERT INTO stage2_proposals(
                proposal_id,project_id,idempotency_key,expected_project_revision,
                expected_content_lock_hash,target_cl,status,proposal_json,proposal_hash,
                validation_json,approved_by,approved_at,created_at,updated_at,
                approved_proposal_hash,approved_validation_hash,approved_child_hashes_json,
                approved_compiled_event_hashes_json,approved_lock_proof_hash,approved_principal_id,
                approval_challenge_id,approval_evidence_id
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                proposal_id,
                project_id,
                "diagnostic-attempt",
                0,
                "content-lock",
                1,
                "approved",
                canonical_json({"schema_version": "diagnostic", "payload": PAYLOAD_SENTINEL}),
                "proposal-hash",
                None,
                "owner",
                "2026-08-17T00:00:00Z",
                "2026-08-17T00:00:00Z",
                "2026-08-17T00:00:00Z",
                "approved-proposal-hash",
                "approved-validation-hash",
                "[]",
                "[]",
                "approved-lock-proof-hash",
                "principal",
                "challenge",
                "evidence",
            ),
        )
        conn.execute(
            """INSERT INTO stage2_commit_attempts(
                attempt_id,proposal_id,project_id,attempt_no,status,retryable,
                base_revision,final_revision,approved_proposal_hash,approved_validation_hash,
                approved_child_hashes_json,approved_compiled_event_hashes_json,
                approved_lock_proof_hash,approved_principal_id,event_ids_json,event_hashes_json,
                state_before_hash,state_after_hash,error_json,created_at,completed_at,
                approved_principal_hash,binding_set_hash,approval_evidence_id
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                attempt_id,
                proposal_id,
                project_id,
                1,
                "started",
                1,
                0,
                None,
                "approved-proposal-hash",
                "approved-validation-hash",
                "[]",
                "[]",
                "approved-lock-proof-hash",
                "principal",
                "[]",
                "[]",
                "before-state-hash",
                None,
                None,
                "2026-08-17T00:00:00Z",
                None,
                sha256_json({"principal_id": "principal"}),
                binding_set_hash,
                "evidence",
            ),
        )


def test_non_foundry_commit_failure_retains_bounded_authority_diagnostics(fresh_db, monkeypatch) -> None:
    project_id = "project.stage2-diagnostic"
    proposal_id = "proposal.stage2-diagnostic"
    attempt_id = "attempt.stage2-diagnostic"
    binding_set = {
        "approved_proposal_hash": "approved-proposal-hash",
        "approved_validation_hash": "approved-validation-hash",
        "approved_child_hashes": [],
        "approved_compiled_event_hashes": [],
        "approved_lock_proof_hash": "approved-lock-proof-hash",
        "approved_principal_id": "principal",
        "approved_principal_hash": sha256_json({"principal_id": "principal"}),
        "approval_evidence_id": "evidence",
    }
    _seed_commit_rows(
        fresh_db,
        project_id=project_id,
        proposal_id=proposal_id,
        attempt_id=attempt_id,
        binding_set_hash=sha256_json(binding_set),
    )

    event = {
        "schema_version": EVENT_V3,
        "project_id": project_id,
        "sequence": 1,
        "event_id": "event.stage2-diagnostic",
        "event_hash": "event-hash",
        "previous_event_hash": "0" * 64,
        "created_at": "2026-08-17T00:00:00Z",
        "advancement": {
            "target_cl": 1,
            "opaque_payload": PAYLOAD_SENTINEL,
            "authority_bindings": [{
                "role": "diagnostic_authority",
                "record_id": "record.safe-diagnostic",
                "record_hash": "record-hash",
                "source_hash": "source-hash",
                "payload": PAYLOAD_SENTINEL,
            }],
        },
    }
    validation = {
        "valid": True,
        "compiled_events": [event],
        "mechanical_state_hash": "mechanical-state-hash",
    }
    attempt = {
        "attempt_id": attempt_id,
        "attempt_no": 1,
        "project_id": project_id,
        "base_revision": 0,
        "state_before_hash": "before-state-hash",
        "binding_set": binding_set,
        "binding_set_hash": sha256_json(binding_set),
    }
    row = {
        "proposal_id": proposal_id,
        "project_id": project_id,
        "status": "approved",
        "approved_by": "owner",
        "expected_project_revision": 0,
        "approved_proposal_hash": "approved-proposal-hash",
        "approved_validation_hash": "approved-validation-hash",
        "approved_child_hashes_json": "[]",
        "approved_compiled_event_hashes_json": "[]",
        "approved_lock_proof_hash": "approved-lock-proof-hash",
        "approved_principal_id": "principal",
        "approval_challenge_id": "challenge",
        "approval_evidence_id": "evidence",
    }

    service = object.__new__(RulesCausalStage2Service)
    service.db = fresh_db
    service.projects = SimpleNamespace(
        _replay_events=lambda _conn, _project_id: {"state_hash": "before-state-hash"},
    )
    monkeypatch.setattr(service, "_prepare_commit_attempt", lambda _proposal_id: (None, attempt))
    monkeypatch.setattr(service, "_proposal_row", lambda _conn, _proposal_id: row)
    monkeypatch.setattr(service, "compile_proposal", lambda _conn, _row: validation)
    monkeypatch.setattr(service, "_assert_approved_binding", lambda _row, _validation, _conn: None)

    caught_boundary: list[BaseException] = []

    def fail_authority_resolution(_conn, _project_id, _record_id):
        failure = EmptyAuthorityBoundaryError()
        caught_boundary.append(failure)
        raise failure

    monkeypatch.setattr(service, "_resolve_record_after_proof", fail_authority_resolution)

    with pytest.raises(FoundryError) as caught:
        service.commit_proposal(proposal_id)

    error = caught.value
    assert error.code == "STAGE2_ATOMIC_COMMIT_ROLLED_BACK"
    assert error.details["error"] == ""
    assert error.details["attempt_id"] == attempt_id
    assert caught_boundary and error.__cause__ is caught_boundary[0]
    assert error.details["exception_module"] == EmptyAuthorityBoundaryError.__module__
    assert error.details["exception_type"] == (
        f"{EmptyAuthorityBoundaryError.__module__}.{EmptyAuthorityBoundaryError.__qualname__}"
    )
    assert error.details["exception_repr"] == "EmptyAuthorityBoundaryError()"
    assert error.details["phase"] == "authority_binding_resolution"
    assert error.details["event_index"] == 1
    assert error.details["authority_role"] == "diagnostic_authority"
    assert error.details["record_id"] == "record.safe-diagnostic"

    frames = error.details["traceback_frames"]
    assert 0 < len(frames) <= 8
    assert all(set(frame) == {"file", "line", "function"} for frame in frames)
    assert all(isinstance(frame["line"], int) and frame["line"] > 0 for frame in frames)
    assert all("/" not in frame["file"] and "\\" not in frame["file"] for frame in frames)

    with fresh_db.connection() as conn:
        attempt_row = conn.execute(
            "SELECT status,retryable,error_json FROM stage2_commit_attempts WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
        proposal_row = conn.execute(
            "SELECT status FROM stage2_proposals WHERE proposal_id=?",
            (proposal_id,),
        ).fetchone()
        event_count = conn.execute("SELECT COUNT(*) FROM events WHERE project_id=?", (project_id,)).fetchone()[0]
        receipt_count = conn.execute(
            "SELECT COUNT(*) FROM stage2_calculation_authority_receipts WHERE event_id=?",
            (event["event_id"],),
        ).fetchone()[0]

    assert attempt_row["status"] == "rolled_back"
    assert attempt_row["retryable"] == 1
    assert proposal_row["status"] == "approved"
    assert event_count == 0
    assert receipt_count == 0

    durable = json.loads(attempt_row["error_json"])
    assert durable["type"] == "EmptyAuthorityBoundaryError"
    assert durable["code"] == "STAGE2_ATOMIC_COMMIT_ROLLED_BACK"
    assert durable["message"] == ""
    assert durable["details"] == error.details

    serialized = json.dumps({"durable": durable, "raised": error.details}, sort_keys=True)
    assert PAYLOAD_SENTINEL not in serialized
