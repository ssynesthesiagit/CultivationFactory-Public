"""The GM authoring gate names its real next action, not Replace Response.

A captured candidate fails the Character/GM Command 4 profile only because
its GM guidance is still provisional.  That is the product's normal
pre-GM-authoring gate: the owner authors, builds and approves the GM
candidate in Review draft and then runs Retry Local Build.  Telling the
owner to replace the response would discard a sound candidate for nothing.
"""
from __future__ import annotations

from copy import deepcopy

from app.api import _owner_view
from character_creation.service import (
    CharacterCreationExecutionService,
    GM_CANDIDATE_AUTHORING_NEXT_ACTION,
    gm_candidate_authoring_gate,
    gm_candidate_authoring_gate_blocker,
)

GATE_DIAGNOSTICS = [
    {"code": "CHARACTER_GM_PROVISIONAL_AUTHORING_NOT_READY"},
    {"code": "CHARACTER_GM_DAO_ICHING_CLASSIFICATION_INVALID"},
]


def _gate_blocker(diagnostics=None, *, capsule=True) -> dict:
    details = {
        "schema_version": "TianxiaFoundry.CharacterGMCommand4ProfileValidation.v1",
        "character_gm_command4_status": "CHARACTER_GM_COMMAND_4_PROFILE_FAIL",
        "diagnostics": deepcopy(GATE_DIAGNOSTICS if diagnostics is None else diagnostics),
        "valid": False,
    }
    if capsule:
        details["gm_candidate_capsule"] = {"capsule_id": "cg1.gm.capsule.test", "gm_authoring_status": "NOT_AUTHORED"}
    return {
        "code": "CHARACTER_GM_COMMAND4_BLOCKED",
        "boundary": "VALIDATION",
        "message": "The Character/GM Command 4 profile failed validation.",
        "details": details,
    }


def _run(blockers: list[dict], *, status: str = "NEEDS_REVIEW") -> dict:
    return {
        "run_id": "cg1.run.gm-gate-test",
        "project_id": "project.gm-gate-test",
        "status": status,
        "execution_mode": "LOCAL_AI",
        "request": {"request_sha256": "a" * 64, "content_lock_hash": "b" * 64},
        "response": {"response_sha256": "c" * 64},
        "blockers": blockers,
    }


def test_gate_predicate_matches_only_the_provisional_authoring_diagnostics() -> None:
    assert gm_candidate_authoring_gate_blocker(_gate_blocker()) is True
    assert gm_candidate_authoring_gate_blocker(_gate_blocker([GATE_DIAGNOSTICS[0]])) is True
    assert gm_candidate_authoring_gate_blocker(_gate_blocker(capsule=False)) is False
    assert gm_candidate_authoring_gate_blocker(_gate_blocker([])) is False
    wider = _gate_blocker(GATE_DIAGNOSTICS + [{"code": "CHARACTER_GM_TRAINING_COVERAGE_INVALID", "missing": ["X"]}])
    assert gm_candidate_authoring_gate_blocker(wider) is False
    assert gm_candidate_authoring_gate_blocker({"code": "CG1_AUTHORITY_SHAPE_UNRESOLVED"}) is False
    assert gm_candidate_authoring_gate(_run([_gate_blocker()])) is True
    assert gm_candidate_authoring_gate(_run([_gate_blocker()], status="READY_FOR_REVIEW")) is False
    assert gm_candidate_authoring_gate(_run([_gate_blocker(), wider])) is False
    assert gm_candidate_authoring_gate(_run([])) is False


def test_owner_view_routes_the_gate_to_author_gm_candidate() -> None:
    owner = _owner_view(_run([_gate_blocker()]))
    assert owner["decisions"] == []
    assert len(owner["blockers"]) == 1
    blocker = owner["blockers"][0]
    assert blocker["code"] == "CHARACTER_GM_COMMAND4_BLOCKED"
    assert blocker["recovery_action"] == "Author GM candidate"
    assert blocker["control"] == {"type": "gm_candidate_authoring", "apply_label": "Author GM candidate"}
    assert blocker["target_step"] == 4
    assert blocker["diagnostics"] == sorted(row["code"] for row in GATE_DIAGNOSTICS)
    assert "Replace Response" not in blocker["resolving_action"]
    action = owner["next_legal_action"]
    assert action["label"] == "Author GM candidate"
    assert action["target_step"] == 4
    assert action["description"] == GM_CANDIDATE_AUTHORING_NEXT_ACTION


def test_owner_view_keeps_replace_response_for_a_wider_command4_failure() -> None:
    wider = _gate_blocker(GATE_DIAGNOSTICS + [{"code": "CHARACTER_GM_TRAINING_COVERAGE_INVALID", "missing": ["X"]}])
    owner = _owner_view(_run([wider]))
    blocker = owner["blockers"][0]
    assert blocker["recovery_action"] == "Replace Response"
    assert owner["next_legal_action"]["label"] != "Author GM candidate"


def test_next_legal_action_text_names_the_gm_candidate_path() -> None:
    service = object.__new__(CharacterCreationExecutionService)
    assert service._next_action_for_status(_run([_gate_blocker()]), audit_provider=False) == GM_CANDIDATE_AUTHORING_NEXT_ACTION
    ordinary = service._next_action_for_status(_run([{"code": "CG1_AUTHORITY_SHAPE_UNRESOLVED", "message": "x"}]), audit_provider=False)
    assert "Replace Response" in ordinary
