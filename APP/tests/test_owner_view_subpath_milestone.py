from __future__ import annotations

import pytest

from app.api import _character_creation_api_view
from character_creation.service import CharacterCreationExecutionService
from test_compiler_selection_authority import pinned_authority  # noqa: F401  (fixture)


_PATH_ID = "tianxia.path.qi_cultivation"
_SUBPATH_ID = "tianxia.subpath.qi.sage"


def _run(
    *,
    target_cl: int,
    subpath_minimum: int = 0,
    response_form: str = "preferred",
    authority: dict | None = None,
) -> dict:
    request = {
        "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v3",
        "required_plan_schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
        "request_sha256": "request-hash",
        "content_lock_hash": "content-hash",
        "stage1_prompt": {
            "envelope": {
                "decision_slots": [{
                    "slot_id": "subpath_choice",
                    "min_selections": subpath_minimum,
                    "max_selections": 1,
                }],
            },
        },
        "delegated_choice_envelope": {
            "allowed_choice_ids_by_slot": {
                "path_choice": [_PATH_ID],
                "subpath_choice": [_SUBPATH_ID],
            },
            "choices_by_slot": {
                "subpath_choice": {
                    _SUBPATH_ID: {
                        "name": "Qi Sage Tradition",
                        "owning_path_id": _PATH_ID,
                        "owning_path_choice_ids": [_PATH_ID],
                    },
                },
            },
            "selection_limits_by_slot": {
                "subpath_choice": {"final_min": subpath_minimum, "final_max": 1},
            },
            "owner_locks": {"by_slot": {}},
        },
    }
    if authority is not None:
        # Owner-review replacement choices are enumerated only from a verified
        # compiler selection authority bound to the envelope's content lock
        # (23237eff); without one the missing Subpath is reported as a
        # blocker instead of a decision card.
        request["delegated_choice_envelope"]["compiler_selection_authority"] = authority
        request["delegated_choice_envelope"]["binding"] = {
            "content_lock_hash": authority["content"]["content_lock_hash"],
            "compiler_selection_authority_sha256": authority["authority_sha256"],
        }
    parsed_plan = {
        "schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
        "canonical_selection_intent": {
            "response_form": response_form,
            "historical_stage2_rows": [{"kind": "historical"}] if response_form == "historical" else [],
        },
        "stage1_response": {
            "response_payload": {
                "decisions": [{
                    "slot_id": "subpath_choice",
                    "state": "deferred_with_reason",
                    "choice_ids": [],
                }],
            },
        },
    }
    return {
        "run_id": f"owner-subpath-{target_cl}-{response_form}",
        "project_id": "owner-subpath-project",
        "status": "READY_FOR_REVIEW",
        "request": request,
        "response": {"response_sha256": "response-hash", "parsed_plan": parsed_plan},
        "final_plan": {
            "target_cl": target_cl,
            "resolution": {
                "selected_choices_by_slot": {"path_choice": [_PATH_ID], "subpath_choice": []},
                "provenance": [{
                    "slot_id": "subpath_choice",
                    "choice_id": None,
                    "provenance": "needs_owner",
                    "status": "unresolved",
                }],
            },
        },
        "validation": {},
        "blockers": [],
        "warnings": [],
        "dry_run": {},
        "outputs": {},
        "owner_descriptive_fields": {"resolved": {}, "proposed": {}},
    }


@pytest.mark.parametrize("target_cl", [1, 2])
def test_generic_pre_subpath_owner_view_has_no_future_subpath_decision(target_cl: int) -> None:
    owner = _character_creation_api_view(_run(target_cl=target_cl))["owner_view"]

    assert owner["decisions"] == []
    assert owner["review"]["approval_required"] is True
    assert owner["tradition"]["name"] == "No Path-owned Subpath proposal supplied"


def test_cl3_missing_subpath_still_emits_owner_decision(pinned_authority) -> None:
    owner = _character_creation_api_view(
        _run(target_cl=3, subpath_minimum=1, authority=pinned_authority),
    )["owner_view"]

    assert [row["slot_id"] for row in owner["decisions"]] == ["subpath_choice"]
    assert owner["decisions"][0]["legal_choices"][0]["value"] == _SUBPATH_ID


def test_historical_pre_subpath_representation_remains_strict(pinned_authority) -> None:
    owner = _character_creation_api_view(
        _run(target_cl=1, response_form="historical", authority=pinned_authority),
    )["owner_view"]

    assert [row["slot_id"] for row in owner["decisions"]] == ["subpath_choice"]


def _unresolved_owner_authority(run: dict) -> list[dict]:
    service = object.__new__(CharacterCreationExecutionService)
    return service._unresolved_owner_authority(run)


@pytest.mark.parametrize("target_cl", [1, 2])
def test_generic_pre_subpath_finalization_gate_ignores_deferred_provenance(target_cl: int) -> None:
    assert _unresolved_owner_authority(_run(target_cl=target_cl)) == []


def test_cl3_finalization_gate_keeps_missing_subpath_strict() -> None:
    unresolved = _unresolved_owner_authority(_run(target_cl=3, subpath_minimum=1))

    assert [row["slot_id"] for row in unresolved] == ["subpath_choice"]


def test_historical_or_malformed_pre_subpath_representation_stays_strict() -> None:
    historical = _unresolved_owner_authority(_run(target_cl=1, response_form="historical"))
    malformed = _run(target_cl=1)
    del malformed["request"]["stage1_prompt"]
    fixture = _run(target_cl=1)
    fixture["request"]["fixture"] = True

    assert [row["slot_id"] for row in historical] == ["subpath_choice"]
    assert [row["slot_id"] for row in _unresolved_owner_authority(malformed)] == ["subpath_choice"]
    assert [row["slot_id"] for row in _unresolved_owner_authority(fixture)] == ["subpath_choice"]


def test_pre_subpath_gate_does_not_hide_an_actual_blocker() -> None:
    run = _run(target_cl=1)
    run["blockers"] = [{"slot_id": "subpath_choice", "code": "CG1_REAL_SUBPATH_BLOCKER"}]

    unresolved = _unresolved_owner_authority(run)

    assert [row["kind"] for row in unresolved] == ["blocker"]
    assert unresolved[0]["slot_id"] == "subpath_choice"
