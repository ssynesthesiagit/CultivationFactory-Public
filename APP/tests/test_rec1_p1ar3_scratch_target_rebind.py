from __future__ import annotations

from copy import deepcopy

from app.core import sha256_json
from character_creation import CharacterCreationExecutionService
from character_creation.stage1_first_compile import compile_once_stage1_first
from tests.test_rec1_p1ar2_target_cl_authority import _authority, _plan_for_target


def test_compile_twice_centrally_rebinds_accepted_target_for_both_scratch_calls(monkeypatch):
    assert CharacterCreationExecutionService._compile_once is compile_once_stage1_first

    project, _envelope, delegated_run = _authority(5)
    delegated_run["created_at"] = "2026-01-01T00:00:00+00:00"
    incoming_plan = _plan_for_target(1)
    incoming_before = deepcopy(incoming_plan)
    accepted_final_plan = {
        "target_cl": 5,
        "target_cl_authority": {
            **deepcopy(
                delegated_run["request"]["delegated_choice_envelope"]["frozen_owner_target_cl"]
            ),
            "envelope_sha256": delegated_run["request"]["delegated_choice_envelope"]["envelope_sha256"],
        },
    }
    accepted_before = deepcopy(accepted_final_plan)
    service = CharacterCreationExecutionService.__new__(CharacterCreationExecutionService)
    service._project = lambda project_id: project
    captured = []
    events = []
    original_rebind = service._plan_with_accepted_final_target

    def rebind_stub(run, plan, accepted_final_plan):
        events.append("rebind")
        return original_rebind(run, plan, accepted_final_plan)

    def compile_stub(
        run,
        plan,
        index,
        *,
        prior_attempt_id=None,
        accepted_final_plan=None,
    ):
        events.append(f"compile-{index}")
        captured.append(
            {
                "index": index,
                "plan_object": plan,
                "plan": deepcopy(plan),
                "plan_sha256": sha256_json(plan),
                "accepted_final_plan": accepted_final_plan,
            }
        )
        return {
            "candidate_identity": "deterministic-candidate",
            "identities": {"scratch": "deterministic-identity"},
        }

    monkeypatch.setattr(service, "_plan_with_accepted_final_target", rebind_stub)
    monkeypatch.setattr(service, "_compile_once", compile_stub)
    delegated_result = service._compile_twice(
        delegated_run,
        incoming_plan,
        accepted_final_plan=accepted_final_plan,
    )

    assert delegated_result["independent_compilations"] == 2
    assert events == ["rebind", "compile-1", "compile-2"]
    assert [entry["index"] for entry in captured] == [1, 2]
    assert [entry["plan"]["target_cl"] for entry in captured] == [5, 5]
    assert [entry["plan"]["stage2_proposal"]["target_cl"] for entry in captured] == [5, 5]
    assert captured[0]["plan_sha256"] == captured[1]["plan_sha256"]
    assert captured[0]["plan_object"] is not captured[1]["plan_object"]
    assert all(entry["accepted_final_plan"] is accepted_final_plan for entry in captured)
    assert incoming_plan == incoming_before
    assert incoming_plan["target_cl"] == 1
    assert accepted_final_plan == accepted_before
    assert captured[0]["plan"]["target_cl"] != incoming_plan["target_cl"]

    captured.clear()
    events.clear()
    legacy_run = {
        "created_at": delegated_run["created_at"],
        "request": {"request_sha256": delegated_run["request"]["request_sha256"]},
    }
    legacy_plan = _plan_for_target(1)
    legacy_before = deepcopy(legacy_plan)
    service._compile_twice(legacy_run, legacy_plan)

    assert events == ["rebind", "compile-1", "compile-2"]
    assert [entry["plan"]["target_cl"] for entry in captured] == [1, 1]
    assert [entry["plan"]["stage2_proposal"]["target_cl"] for entry in captured] == [1, 1]
    assert captured[0]["plan_sha256"] == captured[1]["plan_sha256"]
    assert legacy_plan == legacy_before
