from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tools import provider_free_guided_probe as probe


def _persist_counter(receipt: dict) -> tuple[list[int], Callable[[], None]]:
    writes: list[int] = []

    def persist() -> None:
        writes.append(len(receipt.get("phases") or []))

    return writes, persist


def test_probe_rejects_live_data_root_and_descendants() -> None:
    live = Path.home() / ".local" / "state" / "cultivation-factory"
    for path in (live, live / "foundry.sqlite3", live / "scratch" / "receipt.json"):
        with pytest.raises(probe.ProbeSafetyError):
            probe.reject_live_path(path, label="test path")


def test_probe_receipt_writes_and_seals_a_scratch_path(tmp_path: Path) -> None:
    receipt = {"schema_version": probe.RECEIPT_SCHEMA, "status": "STARTING"}
    target = probe._write_receipt(tmp_path / "evidence" / "probe.json", receipt)

    stored = json.loads(target.read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in stored.items() if key != "receipt_sha256"}
    assert stored["receipt_sha256"] == probe._sha256_json(unsigned)
    assert stored["status"] == "STARTING"


class _Service:
    def __init__(self, status: str = "READY_FOR_REVIEW") -> None:
        self.status = status
        self.calls: list[str] = []

    def get(self, run_id: str) -> dict[str, str]:
        self.calls.append(f"get:{run_id}")
        return {"status": self.status, "run_id": run_id}

    def finalize(self, run_id: str) -> dict[str, str]:
        self.calls.append(f"finalize:{run_id}")
        return {"status": "CLEAN_AND_FINALIZED", "run_id": run_id}


class _Workflow:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def issue_review_challenge(self, project_id: str) -> dict[str, object]:
        self.calls.append(("challenge", project_id))
        return {"status": "ISSUED", "challenge": {"challenge_id": "challenge.probe", "nonce": "nonce.private"}}

    def approve_current_triplet(self, project_id: str, challenge_id: str, nonce: str) -> dict[str, str]:
        self.calls.append(("approve", (project_id, challenge_id, nonce)))
        return {"status": "APPROVED", "review_record_id": "final-review.probe"}

    def materialize_current_triplet(self, project_id: str, review_record_id: str) -> dict[str, str]:
        self.calls.append(("materialize", (project_id, review_record_id)))
        return {"status": "MATERIALIZED", "materialization_id": "materialization.probe"}


class _Exports:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def export(self, project_id: str, *, filename: str) -> dict[str, object]:
        self.calls.append((project_id, filename))
        return {"exported": True, "status": "EXPORTED", "filename": filename}


def test_finalize_chain_calls_real_service_order_and_persists_intermediate_states() -> None:
    service = _Service()
    workflow = _Workflow()
    exports = _Exports()
    receipt = {"status": "READY_FOR_REVIEW", "phases": []}
    writes, persist = _persist_counter(receipt)

    assert probe.run_finalize_chain(
        service,
        workflow,
        exports,
        run_id="cg1.run.probe",
        project_id="project.probe",
        receipt=receipt,
        persist=persist,
    ) is True
    assert service.calls == ["get:cg1.run.probe", "finalize:cg1.run.probe"]
    assert [name for name, _ in workflow.calls] == ["challenge", "approve", "materialize"]
    assert exports.calls == [("project.probe", "ASTRA_project.probe_GM_Screen.zip")]
    assert [row["phase"] for row in receipt["phases"]] == [
        "finalize", "review_challenge", "approve", "materialize", "gm_export",
    ]
    assert receipt["status"] == "EXPORTED"
    assert len(writes) >= 10
    assert "nonce.private" not in json.dumps(receipt)


def test_resume_finalized_run_skips_finalize_and_continues_review_chain() -> None:
    service = _Service(status="CLEAN_AND_FINALIZED")
    workflow = _Workflow()
    exports = _Exports()
    receipt = {"status": "CLEAN_AND_FINALIZED", "phases": []}
    _, persist = _persist_counter(receipt)

    assert probe.run_finalize_chain(
        service,
        workflow,
        exports,
        run_id="cg1.run.probe",
        project_id="project.probe",
        receipt=receipt,
        persist=persist,
    ) is True
    assert service.calls == ["get:cg1.run.probe"]
    assert receipt["finalize"]["status"] == "ALREADY_FINALIZED"


def test_finalize_chain_redacts_nonce_from_approval_errors_and_details() -> None:
    class EchoingBlockedWorkflow(_Workflow):
        def approve_current_triplet(self, project_id: str, challenge_id: str, nonce: str) -> dict[str, str]:
            self.calls.append(("approve", (project_id, challenge_id, nonce)))
            error = RuntimeError(f"approval failed for {nonce}")
            error.code = f"APPROVAL_FAILED_{nonce}"  # type: ignore[attr-defined]
            error.details = {"nonce": nonce, "nested": [f"echo: {nonce}"]}  # type: ignore[attr-defined]
            raise error

    service = _Service()
    workflow = EchoingBlockedWorkflow()
    exports = _Exports()
    receipt = {"status": "READY_FOR_REVIEW", "phases": []}
    _, persist = _persist_counter(receipt)

    assert probe.run_finalize_chain(
        service,
        workflow,
        exports,
        run_id="cg1.run.probe",
        project_id="project.probe",
        receipt=receipt,
        persist=persist,
    ) is False
    assert receipt["status"] == "BLOCKED"
    assert receipt["error"]["message"] == "approval failed for [REDACTED]"
    assert receipt["error"]["details"] == {"nonce": "[REDACTED]", "nested": ["echo: [REDACTED]"]}
    assert "nonce.private" not in json.dumps(receipt)
    assert exports.calls == []


def test_finalize_chain_rejects_non_successful_approval_with_record_id() -> None:
    class BlockedApprovalWorkflow(_Workflow):
        def approve_current_triplet(self, project_id: str, challenge_id: str, nonce: str) -> dict[str, object]:
            self.calls.append(("approve", (project_id, challenge_id, nonce)))
            return {
                "status": "BLOCKED",
                "review_record_id": "final-review.probe",
                "details": {"blockers": ["review not ready"]},
            }

    service = _Service()
    workflow = BlockedApprovalWorkflow()
    exports = _Exports()
    receipt = {"status": "READY_FOR_REVIEW", "phases": []}
    _, persist = _persist_counter(receipt)

    assert probe.run_finalize_chain(
        service,
        workflow,
        exports,
        run_id="cg1.run.probe",
        project_id="project.probe",
        receipt=receipt,
        persist=persist,
    ) is False
    assert receipt["status"] == "BLOCKED"
    assert receipt["error"]["code"] == "PROBE_REVIEW_APPROVAL_STATUS_UNEXPECTED"
    assert receipt["approve"]["status"] == "BLOCKED"
    assert receipt["phases"][2]["status"] == "BLOCKED"
    assert exports.calls == []


def test_finalize_chain_does_not_claim_export_for_blocked_result() -> None:
    class BlockedExports(_Exports):
        def export(self, project_id: str, *, filename: str) -> dict[str, object]:
            self.calls.append((project_id, filename))
            return {"exported": False, "readiness": "GM_NOT_READY", "blockers": ["missing package"]}

    service = _Service()
    workflow = _Workflow()
    exports = BlockedExports()
    receipt = {"status": "READY_FOR_REVIEW", "phases": []}
    _, persist = _persist_counter(receipt)

    assert probe.run_finalize_chain(
        service,
        workflow,
        exports,
        run_id="cg1.run.probe",
        project_id="project.probe",
        receipt=receipt,
        persist=persist,
    ) is False
    assert receipt["status"] == "BLOCKED"
    assert receipt["error"]["code"] == "PROBE_GM_EXPORT_RESULT_UNEXPECTED"
    assert receipt["gm_export"]["exported"] is False
    assert receipt["phases"][-1]["status"] == "BLOCKED"
    assert exports.calls == [("project.probe", "ASTRA_project.probe_GM_Screen.zip")]


def test_finalize_chain_stops_at_actual_review_blocker() -> None:
    class BlockedWorkflow(_Workflow):
        def issue_review_challenge(self, project_id: str) -> dict[str, object]:
            self.calls.append(("challenge", project_id))
            error = RuntimeError("all three authoring components are required")
            error.code = "FINAL_CHARACTER_REVIEW_NOT_READY"  # type: ignore[attr-defined]
            error.details = {"missing": ["command4", "composite_controller", "immortal_art"]}  # type: ignore[attr-defined]
            raise error

    service = _Service()
    workflow = BlockedWorkflow()
    exports = _Exports()
    receipt = {"status": "READY_FOR_REVIEW", "phases": []}
    _, persist = _persist_counter(receipt)

    assert probe.run_finalize_chain(
        service,
        workflow,
        exports,
        run_id="cg1.run.probe",
        project_id="project.probe",
        receipt=receipt,
        persist=persist,
    ) is False
    assert receipt["status"] == "BLOCKED"
    assert receipt["error"]["code"] == "FINAL_CHARACTER_REVIEW_NOT_READY"
    assert exports.calls == []
