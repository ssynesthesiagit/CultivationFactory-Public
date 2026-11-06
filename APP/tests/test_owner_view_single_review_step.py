"""The owner flow has one review page: step 4, "Your character".

Owner request (2026-09-13): after the AI makes the character the owner wants a
single page that shows everything and has Finalize on it, instead of walking
Review draft -> Review Insights -> Review Spheres & Talents -> Preview sheet ->
Save character.  Steps 5-8 are no longer screens, so every post-build state
must report the owner screen as step 4 and must not send the owner to a step
that no longer exists.

This is a presentation contract only: run statuses, validation, finalize and
the server pipeline are unchanged.
"""
from __future__ import annotations

from copy import deepcopy

from app.api import _owner_view
from character_creation.service import CharacterCreationExecutionService

POST_BUILD_STATUSES = ("READY_FOR_REVIEW", "NEEDS_REVIEW", "CLEAN_AND_FINALIZED")


def _run(status: str, **overrides) -> dict:
    run = {
        "run_id": f"cg1.run.onepage.{status.lower()}",
        "project_id": "project.onepage.test",
        "status": status,
        "execution_mode": "LOCAL_AI",
        "request": {"request_sha256": "a" * 64, "content_lock_hash": "b" * 64},
        "response": {"response_sha256": "c" * 64},
        "final_plan": {},
        "dry_run": {},
        "outputs": {},
        "blockers": [],
        "warnings": [],
        "quality": {"status": "CLEAN"},
        "commit": {},
        "action_availability": {},
        "owner_descriptive_fields": {"resolved": {}, "proposed": {}},
    }
    run.update(overrides)
    return run


def test_display_state_step_is_four_for_every_post_build_status() -> None:
    for status in POST_BUILD_STATUSES:
        owner = _owner_view(deepcopy(_run(status)))
        assert owner["display_state"]["step"] == 4, status
        assert owner["display_state"]["status"] == status


def test_next_legal_action_targets_step_four_for_every_post_build_status() -> None:
    for status in POST_BUILD_STATUSES:
        owner = _owner_view(deepcopy(_run(status)))
        assert owner["next_legal_action"]["target_step"] == 4, status


def test_reviewable_and_blocked_runs_still_report_their_own_label() -> None:
    ready = _owner_view(deepcopy(_run("READY_FOR_REVIEW")))
    assert ready["display_state"]["step"] == 4
    assert ready["next_legal_action"]["target_step"] == 4
    assert ready["next_legal_action"]["label"] == "Review and finalize proposal"

    blocked = _owner_view(deepcopy(_run(
        "NEEDS_REVIEW",
        blockers=[{"code": "CG1_AUTHORITY_SHAPE_UNRESOLVED", "message": "The response cannot satisfy the authority contract."}],
    )))
    assert blocked["display_state"]["step"] == 4
    assert blocked["next_legal_action"]["target_step"] == 4
    assert len(blocked["blockers"]) == 1
    # A "replace the response" blocker keeps naming the AI route (step 3), which
    # still exists; only the retired review steps 5-8 may never be a target.
    assert blocked["blockers"][0]["recovery_action"] == "Replace Response"
    assert blocked["blockers"][0]["target_step"] in (3, 4)


def test_finalized_run_lands_on_the_review_page_that_holds_its_exports() -> None:
    owner = _owner_view(deepcopy(_run(
        "CLEAN_AND_FINALIZED",
        commit={"commit_id": "commit.onepage.test", "approved_candidate_identity": "candidate.onepage.test"},
    )))
    assert owner["display_state"]["step"] == 4
    assert owner["next_legal_action"]["target_step"] == 4
    # No step 5-8 target may survive anywhere in the owner projection.
    assert owner["display_state"]["step"] not in (5, 6, 7, 8)


def test_persisted_owner_stage_matches_the_single_review_step() -> None:
    service = CharacterCreationExecutionService
    for status in POST_BUILD_STATUSES:
        assert service._owner_stage_for_status(status) == 4, status
    # The pre-build states keep their real screens.
    assert service._owner_stage_for_status("PREPARING_REQUEST") == 3
    assert service._owner_stage_for_status("WAITING_FOR_RESPONSE") == 3
    assert service._owner_stage_for_status("REVISED") == 3
    # The legacy four-stage recovery contract is untouched by this change.
    assert service._stage_for_status("CLEAN_AND_FINALIZED") == 4
    assert service._stage_for_status("CANCELLED") == 2
