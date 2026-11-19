from __future__ import annotations

from app.api import _owner_view


_PATH_IDS = (
    "tianxia.path.body_refining",
    "tianxia.path.qi_cultivation",
    "tianxia.path.spirit_awakening",
)
_QI_PATH_ID = "tianxia.path.qi_cultivation"


def _compiled_sheet() -> dict:
    return {
        "owner_character_sheet": {
            "identity": {"name": "Public Fixture", "concept": "Projection test"},
            "path_and_subpath": {
                "paths": [
                    {"path_id": path_id, "status": "DORMANT", "attainment": 0}
                    for path_id in _PATH_IDS
                ],
            },
        },
    }


def _run(*, blockers: list[dict] | None = None, authoritative_paths: bool = True) -> dict:
    resolution = {
        "selected_choices_by_slot": {"path_choice": [_QI_PATH_ID]},
        "provenance": [
            {
                "slot_id": "path_choice",
                "choice_id": _QI_PATH_ID,
                "provenance": "ai",
                "status": "accepted",
            },
            {
                "slot_id": "method_choice",
                "choice_id": "method.accepted",
                "provenance": "ai",
                "status": "accepted",
            },
            {
                "slot_id": "method_choice",
                "choice_id": "method.rejected",
                "provenance": "unavailable",
                "status": "rejected",
                "reason": "not offered by the frozen authority",
            },
            {
                "slot_id": "foundation_choice",
                "choice_id": "foundation.rejected",
                "provenance": "unavailable",
                "status": "rejected",
            },
        ],
    }
    if authoritative_paths:
        resolution.update({
            "selected_path_ids": [_QI_PATH_ID],
            "actual_advancing_path_ids": [_QI_PATH_ID],
            "method_granted_path_ids": [_QI_PATH_ID],
        })
    return {
        "run_id": "owner-view-public-fixture",
        "project_id": "owner-view-project",
        "status": "READY_FOR_REVIEW",
        "request": {
            "project_id": "owner-view-project",
            "request_sha256": "a" * 64,
            "content_lock_hash": "b" * 64,
            "delegated_choice_envelope": {
                "allowed_choice_ids_by_slot": {},
                "choices_by_slot": {
                    "method_choice": {
                        "method.accepted": {"name": "Accepted Method"},
                    },
                },
                "owner_locks": {"by_slot": {}},
            },
        },
        "response": {"response_sha256": "c" * 64},
        "final_plan": {
            "target_cl": 15,
            "resolution": resolution,
            "unresolved": [],
        },
        "validation": {},
        "blockers": blockers or [],
        "warnings": [],
        "dry_run": {"preview": {"compiled": {"character_sheet": _compiled_sheet()}}},
        "outputs": {},
        "owner_descriptive_fields": {"resolved": {}, "proposed": {}},
    }


def test_clean_owner_view_prefers_authoritative_advancing_paths_and_hides_rejected_alternatives() -> None:
    owner = _owner_view(_run())

    states = {row["name"]: row["state"] for row in owner["paths"]}
    assert states == {
        "Body Refining": "dormant",
        "Qi Cultivation": "advancing",
        "Spirit Awakening": "dormant",
    }
    assert owner["decisions"] == []
    assert owner["blockers"] == []
    assert owner["provenance_groups"]["Needs owner decision"] == []
    assert {
        row["name"] for row in owner["provenance_groups"]["AI proposed"]
    } == {"Qi Cultivation", "Accepted Method"}


def test_scratch_path_mode_remains_a_fallback_without_authoritative_resolution_state() -> None:
    run = _run(authoritative_paths=False)
    run["dry_run"]["preview"]["compiled"]["character_sheet"]["owner_character_sheet"][
        "path_and_subpath"
    ]["paths"][1]["status"] = "ADVANCING"
    owner = _owner_view(run)

    states = {row["name"]: row["state"] for row in owner["paths"]}
    assert states == {
        "Body Refining": "dormant",
        "Qi Cultivation": "advancing",
        "Spirit Awakening": "dormant",
    }


def test_selected_path_cannot_override_present_empty_advancing_authority() -> None:
    run = _run()
    resolution = run["final_plan"]["resolution"]
    resolution["selected_path_ids"] = [_QI_PATH_ID]
    resolution["actual_advancing_path_ids"] = []
    resolution["method_granted_path_ids"] = [_QI_PATH_ID]

    owner = _owner_view(run)

    states = {row["name"]: row["state"] for row in owner["paths"]}
    assert states["Qi Cultivation"] == "dormant"


def test_mixed_case_accepted_provenance_uses_resolved_groups() -> None:
    run = _run()
    accepted = run["final_plan"]["resolution"]["provenance"]
    accepted[0]["provenance"] = "AI"
    accepted[1]["provenance"] = "Automatic"
    accepted.append({
        "slot_id": "foundation_choice",
        "choice_id": "foundation.accepted",
        "provenance": "OwNeR",
        "status": "accepted",
    })

    owner = _owner_view(run)

    assert owner["provenance_groups"]["Needs owner decision"] == []
    assert len(owner["provenance_groups"]["AI proposed"]) == 1
    assert len(owner["provenance_groups"]["Automatic"]) == 1
    assert len(owner["provenance_groups"]["Owner"]) == 1


def test_real_owner_blocker_still_becomes_a_decision() -> None:
    owner = _owner_view(_run(blockers=[{
        "field": "foundation_choice",
        "details": {
            "field": "foundation_choice",
            "slot_id": "foundation_choice",
            "allowed_choice_ids": ["foundation.legal"],
            "operation": "set_field",
        },
        "message": "A source-backed Foundation choice is required.",
    }]))

    assert len(owner["decisions"]) == 1
    assert owner["decisions"][0]["field"] == "foundation_choice"
    assert owner["decisions"][0]["legal_choices"][0]["value"] == "foundation.legal"
    assert owner["blockers"][0]["field"] == "foundation_choice"
