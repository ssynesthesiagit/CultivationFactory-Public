from __future__ import annotations

from character_creation import CharacterCreationExecutionService


AI_NAME = "Ji Wuying"
AI_CONCEPT = "A sword master demonic cultivator master of qi and body refining."


def _run(accepted: dict[str, object]) -> dict[str, object]:
    proposed = {"identity": {"name": AI_NAME}, "concept": AI_CONCEPT}
    return {
        "owner_descriptive_fields": {"proposed": proposed, "accepted": accepted},
        "dry_run": {"preview": {"identity": proposed}, "candidate_identity": "reviewed"},
    }


def test_finalize_reuses_reviewed_dry_run_for_unchanged_accepted_identity():
    service = object.__new__(CharacterCreationExecutionService)
    run = _run({"identity": {"name": f" {AI_NAME} "}, "concept": f" {AI_CONCEPT} "})
    calls = []

    def compile_twice(*args, **kwargs):
        calls.append((args, kwargs))
        return {"candidate_identity": "recompiled"}

    service._compile_twice = compile_twice
    plan = {"plan": "reviewed"}
    final_plan = {"final": "reviewed"}

    candidate = service._approved_candidate_for_finalization(run, plan, final_plan)

    assert candidate is run["dry_run"]
    assert calls == []


def test_finalize_recompiles_for_changed_accepted_identity():
    service = object.__new__(CharacterCreationExecutionService)
    run = _run({"identity": {"name": "Owner-edited name"}, "concept": AI_CONCEPT})
    calls = []
    recompiled = {"candidate_identity": "recompiled"}

    def compile_twice(*args, **kwargs):
        calls.append((args, kwargs))
        return recompiled

    service._compile_twice = compile_twice
    plan = {"plan": "reviewed"}
    final_plan = {"final": "reviewed"}

    candidate = service._approved_candidate_for_finalization(run, plan, final_plan)

    assert candidate is recompiled
    assert calls == [((run, plan), {"accepted_final_plan": final_plan})]


def test_finalize_recompiles_for_substantive_noncanonical_identity_shapes():
    cases = [
        ("accepted", {"name": AI_NAME, "concept": AI_CONCEPT}),
        ("proposed", {"name": AI_NAME, "concept": AI_CONCEPT}),
        ("reviewed", {"identity": {"name": AI_NAME}, "character_concept": AI_CONCEPT}),
    ]

    for location, malformed in cases:
        service = object.__new__(CharacterCreationExecutionService)
        run = _run({"identity": {"name": AI_NAME}, "concept": AI_CONCEPT})
        if location == "accepted":
            run["owner_descriptive_fields"]["accepted"] = malformed
        elif location == "proposed":
            run["owner_descriptive_fields"]["proposed"] = malformed
        else:
            run["dry_run"]["preview"]["identity"] = malformed
        calls = []
        recompiled = {"candidate_identity": "recompiled"}

        def compile_twice(*args, **kwargs):
            calls.append((args, kwargs))
            return recompiled

        service._compile_twice = compile_twice
        plan = {"plan": "reviewed"}
        final_plan = {"final": "reviewed"}

        candidate = service._approved_candidate_for_finalization(run, plan, final_plan)

        assert candidate is recompiled
        assert calls == [((run, plan), {"accepted_final_plan": final_plan})]


def test_finalize_reuses_reviewed_dry_run_without_substantive_accepted_fields():
    service = object.__new__(CharacterCreationExecutionService)
    run = _run({})
    calls = []

    def compile_twice(*args, **kwargs):
        calls.append((args, kwargs))
        return {"candidate_identity": "recompiled"}

    service._compile_twice = compile_twice
    plan = {"plan": "reviewed"}
    final_plan = {"final": "reviewed"}

    candidate = service._approved_candidate_for_finalization(run, plan, final_plan)

    assert candidate is run["dry_run"]
    assert calls == []


def test_finalize_compacts_reviewed_candidate_before_live_execution():
    service = object.__new__(CharacterCreationExecutionService)
    candidate = {
        "schema": "TianxiaFoundry.CharacterCreationDryRun.v3",
        "candidate_identity": "reviewed",
        "identities": {"character_sheet": "sheet-hash"},
        "deterministic": True,
        "independent_compilations": 2,
        "preview": {"large": "discarded"},
        "artifacts": {"large": "discarded"},
    }
    run = {"dry_run": candidate}

    compact = service._compact_finalization_candidate(run, candidate)

    assert run["dry_run"] == {"candidate_identity": "reviewed"}
    assert compact == {
        "schema": "TianxiaFoundry.CharacterCreationDryRun.v3",
        "candidate_identity": "reviewed",
        "identities": {"character_sheet": "sheet-hash"},
        "deterministic": True,
        "independent_compilations": 2,
    }
    assert compact["identities"] is not candidate["identities"]
    assert "preview" not in compact
    assert "artifacts" not in compact


def test_finalize_blank_failure_reports_type_phase_and_repr():
    details = CharacterCreationExecutionService._finalization_failure_details(
        MemoryError(),
        phase="live_execution",
        restored=True,
    )

    assert details == {
        "cause": "",
        "exception_type": "builtins.MemoryError",
        "exception_repr": "MemoryError()",
        "phase": "live_execution",
        "restored": True,
    }
