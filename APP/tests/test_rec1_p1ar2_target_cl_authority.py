from __future__ import annotations

from copy import deepcopy
import uuid

import pytest

from app.core import FoundryError, canonical_json
from character_creation.delegated_choice_authority import (
    build_delegated_choice_envelope,
    final_plan_sha256,
    validate_accepted_final_plan_target,
    validate_delegated_choice_plan,
    validate_delegated_target_cl,
)
from path_method_authority import CANONICAL_PATH_IDS
from tests.test_rec1_p1a_delegated_choice_authority import (
    _plan as _p1a_plan,
    _prompt as _p1a_prompt,
    _project as _p1a_project,
    _run as _p1a_run,
)
from tests.test_rec1_p1ar1_delegated_recovery import (
    _canonical_state,
    _jiang_plan,
    _method_for_paths,
    _new_jiang_normal_project,
)
from stage1.service import Stage1ClipboardService
from app.api import create_app


def _authority(target_cl: int) -> tuple[dict, dict, dict]:
    project = deepcopy(_p1a_project())
    project["user_locks"][0]["value"] = target_cl
    envelope = build_delegated_choice_envelope(
        project,
        _p1a_prompt(),
        execution_mode="MANUAL_CHAT",
        idempotency_key="REC1-P1A-ONE-SHOT",
    )
    return project, envelope, _p1a_run(project, envelope)


def _plan_for_target(target_cl: int) -> dict:
    plan = _p1a_plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL")
    plan["target_cl"] = target_cl
    plan["stage2_proposal"]["target_cl"] = target_cl
    return plan


def test_matching_frozen_target_is_explicit_in_final_plan_and_hash():
    project, envelope, run = _authority(5)
    plan = _plan_for_target(5)

    assert validate_delegated_target_cl(run, project, plan) == 5
    final_plan = validate_delegated_choice_plan(
        run,
        project,
        plan,
        response_sha256="RESPONSE-5",
    )

    assert final_plan["target_cl"] == 5
    assert final_plan["target_cl_authority"]["value"] == 5
    assert final_plan["target_cl_authority"]["delegated"] is False
    assert final_plan["target_cl_authority"]["binding"] == envelope["binding"]
    assert final_plan_sha256(final_plan) == final_plan["final_plan_sha256"]

    synthetic_target_change = deepcopy(final_plan)
    synthetic_target_change["target_cl"] = 4
    assert final_plan_sha256(synthetic_target_change) != final_plan["final_plan_sha256"]


def test_response_target_mismatch_is_actionable_before_final_plan_derivation():
    project, _envelope, run = _authority(5)
    plan = _plan_for_target(1)

    with pytest.raises(FoundryError) as exc:
        validate_delegated_target_cl(run, project, plan)

    assert exc.value.code == "CG1_DELEGATED_TARGET_CL_MISMATCH"
    assert exc.value.details["expected_target_cl"] == 5
    assert exc.value.details["proposed_target_cl"] == 1
    assert exc.value.details["surface"] == "complete_response.target_cl"


@pytest.mark.parametrize(
    ("row_update", "surface", "proposed"),
    [
        ({"target_cl": 4, "effective_cl": 5}, "stage2_proposal.choices[0].target_cl", 4),
        ({"effective_cl": 4}, "stage2_proposal.level_advance_rows", 4),
        ({"effective_cl": 6}, "stage2_proposal.choices[0].effective_cl", 6),
    ],
)
def test_stage2_target_surfaces_cannot_imply_a_different_final_target(row_update, surface, proposed):
    project, _envelope, run = _authority(5)
    plan = _plan_for_target(5)
    plan["stage2_proposal"]["choices"] = [{"kind": "level_advance", "record_id": "LEVEL", **row_update}]

    with pytest.raises(FoundryError) as exc:
        validate_delegated_target_cl(run, project, plan)

    assert exc.value.code == "CG1_DELEGATED_TARGET_CL_MISMATCH"
    assert exc.value.details["expected_target_cl"] == 5
    assert exc.value.details["proposed_target_cl"] == proposed
    assert exc.value.details["surface"] == surface


def test_final_plan_without_target_authority_is_stale_and_requires_regeneration():
    project, _envelope, run = _authority(5)
    final_plan = validate_delegated_choice_plan(
        run,
        project,
        _plan_for_target(5),
        response_sha256="RESPONSE-5",
    )
    stale = deepcopy(final_plan)
    stale.pop("target_cl", None)
    stale.pop("target_cl_authority", None)

    with pytest.raises(FoundryError) as exc:
        validate_accepted_final_plan_target(run, project, stale)

    assert exc.value.code == "CG1_FINAL_PLAN_TARGET_CL_AUTHORITY_STALE"
    assert exc.value.details["expected_target_cl"] == 5
    assert exc.value.details["final_plan_target_cl"] is None


def test_real_execution_rejects_target_mismatch_before_derivation_or_scratch(catalog_environment, monkeypatch):
    app = create_app(catalog_environment["settings"])
    builder = app.state.character_builder
    created = _new_jiang_normal_project(builder)
    project_id = created["project_id"]
    builder.commit_normal_first_cycle_catalog_choices(project_id)

    prompt = Stage1ClipboardService(app.state.db).generate_prompt(project_id)
    method_id = _method_for_paths(prompt)
    execution = app.state.character_creation
    run = execution.start(
        project_id,
        execution_mode="MANUAL_CHAT",
        idempotency_key=f"rec1.p1ar2.target-mismatch.{uuid.uuid4().hex}",
    )
    plan = _jiang_plan(app.state.db, project_id, run, method_id)
    plan["target_cl"] = 1
    plan["stage2_proposal"]["target_cl"] = 1
    before = _canonical_state(app.state.db, project_id)
    derivation_calls = []
    compile_calls = []

    def derivation_trap(*args, **kwargs):
        derivation_calls.append((args, kwargs))
        raise AssertionError("target mismatch reached final-plan derivation")

    def compile_trap(*args, **kwargs):
        compile_calls.append((args, kwargs))
        raise AssertionError("target mismatch reached scratch compilation")

    monkeypatch.setattr(execution, "_derive_delegated_final_grant_plan", derivation_trap)
    monkeypatch.setattr(execution, "_compile_twice", compile_trap)
    result = execution.submit_manual(
        run["run_id"],
        response_text=canonical_json(plan),
        request_sha256=run["request"]["request_sha256"],
    )

    assert result["status"] == "NEEDS_REVIEW"
    assert result["blockers"][0]["code"] == "CG1_DELEGATED_TARGET_CL_MISMATCH"
    assert result["blockers"][0]["details"]["expected_target_cl"] == 5
    assert result["blockers"][0]["details"]["proposed_target_cl"] == 1
    assert result["blockers"][0]["details"]["surface"] == "complete_response.target_cl"
    assert derivation_calls == []
    assert compile_calls == []
    assert result["final_plan"] == {}
    assert "final_plan_sha256" not in result["final_plan"]
    assert _canonical_state(app.state.db, project_id) == before


def test_accepted_final_target_rebinds_downstream_plan_surfaces(catalog_environment):
    app = create_app(catalog_environment["settings"])
    builder = app.state.character_builder
    created = _new_jiang_normal_project(builder)
    project_id = created["project_id"]
    builder.commit_normal_first_cycle_catalog_choices(project_id)
    prompt = Stage1ClipboardService(app.state.db).generate_prompt(project_id)
    method_id = _method_for_paths(prompt)
    execution = app.state.character_creation
    run = execution.start(
        project_id,
        execution_mode="MANUAL_CHAT",
        idempotency_key=f"rec1.p1ar2.accepted-target.{uuid.uuid4().hex}",
    )
    plan = _jiang_plan(app.state.db, project_id, run, method_id)
    accepted_final_plan = {
        "target_cl": 5,
        "target_cl_authority": run["request"]["delegated_choice_envelope"]["frozen_owner_target_cl"],
    }
    accepted_final_plan["target_cl_authority"] = {
        **deepcopy(accepted_final_plan["target_cl_authority"]),
        "envelope_sha256": run["request"]["delegated_choice_envelope"]["envelope_sha256"],
    }
    downstream = deepcopy(plan)
    downstream["target_cl"] = 1
    downstream["stage2_proposal"]["target_cl"] = 1

    rebound = execution._plan_with_accepted_final_target(run, downstream, accepted_final_plan)

    assert rebound["target_cl"] == 5
    assert rebound["stage2_proposal"]["target_cl"] == 5
    assert downstream["target_cl"] == 1
    assert downstream["stage2_proposal"]["target_cl"] == 1
