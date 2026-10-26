from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.core import FoundryError
from character_creation import service as creation_service
from character_creation.service import CharacterCreationExecutionService, DRY_RUN_SCHEMA


def _service(tmp_path):
    service = object.__new__(CharacterCreationExecutionService)
    service._plan_with_accepted_final_target = lambda _run, value, _accepted: deepcopy(value)
    # No approved GM candidate: compiles capture as they do before GM authoring.
    service.candidate_gm_authoring = SimpleNamespace(candidate_compilation_authority=lambda _run, final_plan=None: None)
    if tmp_path is not None:
        service.db = SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path))
    return service


def _candidate(identity: str, *, ledger_identity: str | None = None) -> dict[str, object]:
    ledger_identity = ledger_identity or identity
    artifact = {
        "identity": ledger_identity,
        "payload": "large-artifact-payload",
    }
    return {
        "schema": "TianxiaFoundry.CompiledCharacterCandidate.v3",
        "candidate_identity": identity,
        "identities": {"ledger": ledger_identity},
        "artifacts": {"ledger": artifact},
        "preview": {
            "identity": {"name": "Owner-facing"},
            "target_cl": 1,
            "compiled": {"ledger": deepcopy(artifact)},
            "readiness": {
                "ledger": {
                    "service": "ledger",
                    "identity": ledger_identity,
                    "verification_status": "VERIFIED",
                    "receipt": deepcopy(artifact),
                }
            },
        },
        "_timings": creation_service._compile_timing_receipt({"snapshot_copy_hash": 3}),
    }


def _run(run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "created_at": "2026-08-28T00:00:00Z",
        "request": {"request_sha256": "a" * 64},
    }


def test_compile_twice_compacts_first_candidate_and_keeps_two_independent_builds(tmp_path):
    service = _service(tmp_path)
    calls: list[int] = []

    def fake_compile_once(_run, _plan, index, **_kwargs):
        calls.append(index)
        return _candidate("candidate-id", ledger_identity="ledger-id")

    service._compile_once = fake_compile_once
    result = service._compile_twice(_run("retention-run"), {"target_cl": 1})

    assert calls == [1, 2]
    assert result["schema"] == DRY_RUN_SCHEMA
    assert result["deterministic"] is True
    assert result["independent_compilations"] == 2
    assert result["candidate_identity"] == "candidate-id"
    assert result["identities"] == {"ledger": "ledger-id"}
    assert result["artifacts"]["ledger"]["payload"] == "large-artifact-payload"
    assert "compiled" not in result["preview"]
    assert "receipt" not in result["preview"]["readiness"]["ledger"]
    assert result["preview"]["readiness"]["ledger"]["artifact_key"] == "ledger"
    assert result["_timings"]["phases_ms"]["factory_compile_1.snapshot_copy_hash"] == 3

    sidecars = list((tmp_path / "diagnostics" / "character_creation").glob("*.jsonl"))
    assert len(sidecars) == 1
    records = [json.loads(line) for line in sidecars[0].read_text(encoding="utf-8").splitlines()]
    assert [(row["phase"], row["status"]) for row in records] == [
        ("compile_twice", "started"),
        ("compile_1", "started"),
        ("compile_1", "complete"),
        ("compile_2", "started"),
        ("compile_2", "complete"),
        ("compile_twice", "complete"),
    ]
    allowed = {
        "schema",
        "run_id",
        "phase",
        "status",
        "compile_index",
        "elapsed_ms",
        "timing_phases_ms",
        "candidate_identity",
        "error_code",
    }
    forbidden = {"payload", "artifacts", "preview", "response", "prompt", "tokens"}
    for record in records:
        assert set(record) <= allowed
        assert not forbidden.intersection(record)
        if "elapsed_ms" in record:
            assert isinstance(record["elapsed_ms"], (int, float))
            assert not isinstance(record["elapsed_ms"], bool)


def test_compile_twice_identity_mismatch_still_fails_closed_after_two_builds(tmp_path):
    service = _service(tmp_path)
    calls: list[int] = []

    def fake_compile_once(_run, _plan, index, **_kwargs):
        calls.append(index)
        if index == 1:
            return _candidate("candidate-one", ledger_identity="ledger-one")
        return _candidate("candidate-two", ledger_identity="ledger-two")

    service._compile_once = fake_compile_once
    with pytest.raises(FoundryError) as exc_info:
        service._compile_twice(_run("mismatch-run"), {"target_cl": 1})

    assert exc_info.value.code == "CG1_NONDETERMINISTIC_COMPILATION"
    assert calls == [1, 2]
    sidecars = list((tmp_path / "diagnostics" / "character_creation").glob("*.jsonl"))
    assert len(sidecars) == 1
    records = [json.loads(line) for line in sidecars[0].read_text(encoding="utf-8").splitlines()]
    assert ("identity_compare", "failed") in [(row["phase"], row["status"]) for row in records]
    assert records[-1]["error_code"] == "CG1_NONDETERMINISTIC_COMPILATION"


def test_compile_twice_failure_persists_bounded_active_phase_timings(tmp_path):
    service = _service(tmp_path)
    calls: list[int] = []

    def fake_compile_once(_run, _plan, index, **kwargs):
        calls.append(index)
        timing_sink = kwargs["_timing_sink"]
        timing_sink["snapshot_copy_hash"] = 17
        timing_sink["prompt_payload"] = 999
        timing_sink["scratch_db_migrate_service_creation"] = "not numeric"
        raise FoundryError("CG1_TEST_COMPILE_FAILURE", "focused failure")

    service._compile_once = fake_compile_once
    with pytest.raises(FoundryError) as exc_info:
        service._compile_twice(_run("timing-failure-run"), {"target_cl": 1})

    assert exc_info.value.code == "CG1_TEST_COMPILE_FAILURE"
    assert calls == [1]
    sidecars = list((tmp_path / "diagnostics" / "character_creation").glob("*.jsonl"))
    assert len(sidecars) == 1
    records = [json.loads(line) for line in sidecars[0].read_text(encoding="utf-8").splitlines()]
    assert [(row["phase"], row["status"]) for row in records] == [
        ("compile_twice", "started"),
        ("compile_1", "started"),
        ("compile_twice", "failed"),
    ]
    failed = records[-1]
    assert failed["compile_index"] == 1
    assert isinstance(failed["elapsed_ms"], (int, float))
    assert not isinstance(failed["elapsed_ms"], bool)
    assert failed["timing_phases_ms"] == {
        "snapshot_copy_hash": 17,
    }
    assert "prompt_payload" not in failed["timing_phases_ms"]
    assert "scratch_db_migrate_service_creation" not in failed["timing_phases_ms"]


def test_walk_completion_compiles_once_and_finalize_runs_only_the_second_build(tmp_path):
    service = _service(tmp_path)
    calls: list[int] = []

    def fake_compile_once(_run, _plan, index, **_kwargs):
        calls.append(index)
        return _candidate("candidate-id", ledger_identity="ledger-id")

    service._compile_once = fake_compile_once
    first = service._compile_twice(_run("deferred-run"), {"target_cl": 1}, compilations=1)
    assert calls == [1]
    assert first["independent_compilations"] == 1 and first["deterministic"] is None
    proven = service._compile_twice(_run("deferred-run"), {"target_cl": 1}, reuse_first=first)
    assert calls == [1, 2]
    assert proven["independent_compilations"] == 2 and proven["deterministic"] is True
    assert proven["candidate_identity"] == "candidate-id"


def test_deferred_second_build_must_reproduce_the_reviewed_identity(tmp_path):
    service = _service(tmp_path)
    identities = iter(["reviewed-id", "different-id"])
    service._compile_once = lambda _run, _plan, _index, **_kwargs: _candidate(next(identities))
    first = service._compile_twice(_run("deferred-mismatch"), {"target_cl": 1}, compilations=1)
    with pytest.raises(FoundryError) as raised:
        service._compile_twice(_run("deferred-mismatch"), {"target_cl": 1}, reuse_first=first)
    assert raised.value.code == "CG1_NONDETERMINISTIC_COMPILATION"
