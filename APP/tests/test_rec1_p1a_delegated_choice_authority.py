from __future__ import annotations

from copy import deepcopy

import pytest

from app.core import FoundryError
from character_creation.delegated_choice_authority import (
    build_delegated_choice_envelope,
    final_plan_sha256,
    validate_delegated_choice_plan,
)
from character_creation.response_materialization import normalize_selection_intent
from path_method_authority import CANONICAL_PATH_IDS


def _project(path_ids: list[str] | None = None) -> dict:
    locks = [{"field": "target_cl", "value": 1, "source": "rec1-p1ar2-test"}]
    if path_ids:
        locks.append({
            "field": "character_sheet.locked_choices",
            "value": {"path_choice": list(path_ids)},
            "source": "rec1-p1a-test",
        })
    return {
        "project_id": "REC1-P1A-PROJECT",
        "revision": 4,
        "user_locks": locks,
        "content_lock": {"catalog_build_id": "CATALOG-4", "lock_hash": "CONTENT-4"},
    }


def _choice(choice_id: str, **fields) -> dict:
    return {"choice_id": choice_id, "initial_creation_selectable": True, "availability": {"available": True}, **fields}


def _prompt() -> dict:
    body = CANONICAL_PATH_IDS[0]
    paths = list(CANONICAL_PATH_IDS)
    methods = {
        "METHOD-ALL": _choice("METHOD-ALL", related_choice_ids=paths, compatible_foundation_ids=["FOUNDATION-ALL"]),
        "METHOD-BODY": _choice("METHOD-BODY", related_choice_ids=[body], compatible_foundation_ids=["FOUNDATION-BODY"]),
    }
    foundations = {
        "FOUNDATION-ALL": _choice("FOUNDATION-ALL", compatible_method_ids=["METHOD-ALL"], compatible_path_ids=paths),
        "FOUNDATION-BODY": _choice("FOUNDATION-BODY", compatible_method_ids=["METHOD-BODY"], compatible_path_ids=[body]),
    }
    return {
        "prompt_id": "STAGE1-PROMPT-4",
        "prompt_sha256": "STAGE1-HASH-4",
        "envelope": {
            "decision_slots": [
                {"slot_id": "path_choice", "min_selections": 1, "max_selections": 3, "allow_none": False, "choices": [_choice(path_id) for path_id in paths]},
                {"slot_id": "method_choice", "min_selections": 0, "max_selections": 1, "allow_none": True, "choices": list(methods.values())},
                {"slot_id": "foundation_choice", "min_selections": 0, "max_selections": 1, "allow_none": True, "choices": list(foundations.values())},
                {"slot_id": "sphere_priorities", "min_selections": 0, "max_selections": 1, "allow_none": True, "choices": [_choice("SPHERE-FIRE"), _choice("SPHERE-LOCKED")],},
            ],
            "path_method_authority": {
                "all_path_ids": paths,
                "method_granted_path_ids": {"METHOD-ALL": paths, "METHOD-BODY": [body]},
            },
        },
    }


def _run(project: dict, envelope: dict) -> dict:
    return {
        "project_id": project["project_id"],
        "starting_revision": project["revision"],
        "execution_mode": "MANUAL_CHAT",
        "idempotency_key": "REC1-P1A-ONE-SHOT",
        "request": {"request_sha256": "REQUEST-4", "delegated_choice_envelope": envelope},
        "response": {"response_sha256": "RESPONSE-4"},
    }


def _plan(*, paths: list[str] | None = None, method: str | None = "METHOD-ALL", foundation: str | None = None, sphere: list[str] | None = None) -> dict:
    by_slot = {}
    if paths is not None:
        by_slot["path_choice"] = list(paths)
    if method is not None:
        by_slot["method_choice"] = [method]
    if foundation is not None:
        by_slot["foundation_choice"] = [foundation]
    if sphere is not None:
        by_slot["sphere_priorities"] = list(sphere)
    return {
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "target_cl": 1,
        "delegated_choice_selections": {"by_slot": by_slot},
        "stage2_proposal": {"target_cl": 1, "choices": [], "planner_rationale": "Prose cannot grant a choice."},
        "owner_descriptive_fields": {"identity": {"name": ""}, "concept": ""},
    }


def _authority(path_ids: list[str] | None = None):
    project = _project(path_ids)
    envelope = build_delegated_choice_envelope(
        project,
        _prompt(),
        execution_mode="MANUAL_CHAT",
        idempotency_key="REC1-P1A-ONE-SHOT",
    )
    assert envelope is not None
    return project, envelope, _run(project, envelope)


def _raises(code: str, plan: dict, project: dict | None = None, envelope: dict | None = None):
    project, fresh_envelope, run = _authority() if project is None else (project, envelope, _run(project, envelope))
    with pytest.raises(FoundryError) as exc:
        validate_delegated_choice_plan(run, project, plan, response_sha256="RESPONSE-4")
    assert exc.value.code == code


def test_zero_owner_locks_offer_all_paths_and_ai_method_grants_are_authoritative():
    project, envelope, run = _authority()
    assert envelope["frozen_owner_target_cl"]["value"] == 1
    assert envelope["frozen_owner_target_cl"]["delegated"] is False
    assert envelope["owner_locks"]["by_slot"]["path_choice"] == []
    assert envelope["owner_locks"]["zero_owner_path_locks_are_legal"] is True
    assert envelope["offered_choice_ids_by_slot"]["path_choice"] == list(CANONICAL_PATH_IDS)
    assert envelope["allowed_choice_ids_by_slot"]["path_choice"] == list(CANONICAL_PATH_IDS)
    plan = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL", sphere=["SPHERE-FIRE"])
    final = validate_delegated_choice_plan(run, project, plan, response_sha256="RESPONSE-4")
    assert final is not None
    assert final["target_cl"] == 1
    assert final["target_cl_authority"]["value"] == 1
    resolution = final["resolution"]
    assert resolution["actual_advancing_path_ids"] == list(CANONICAL_PATH_IDS)
    assert resolution["actual_advancing_path_ids"] == resolution["method_granted_path_ids"]
    assert resolution["selected_choices_by_slot"]["sphere_priorities"] == ["SPHERE-FIRE"]
    assert all(row["provenance"] == "AI" for row in resolution["provenance"] if row["slot_id"] == "path_choice")
    assert resolution["descriptive_fields"] == {"name": None, "concept": None}
    assert final_plan_sha256(final) == final["final_plan_sha256"]


def test_blank_delegated_name_and_concept_can_be_ai_proposed_for_owner_review():
    project, envelope, run = _authority()
    plan = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL")
    plan["owner_descriptive_fields"] = {
        "identity": {"name": "玄火·云舟"},
        "concept": "A wandering cultivator who turns disciplined fire into patient protection.",
    }
    final = validate_delegated_choice_plan(run, project, plan, response_sha256="RESPONSE-4")
    assert final["resolution"]["descriptive_fields"] == {
        "name": "玄火·云舟",
        "concept": "A wandering cultivator who turns disciplined fire into patient protection.",
    }
    assert any(
        row["slot_id"] == "identity.name" and row["provenance"] == "needs_owner"
        for row in final["resolution"]["provenance"]
    ) is False


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_all_owner_path_lock_counts_are_explicit_and_final_no_path_is_rejected(count: int):
    locked = list(CANONICAL_PATH_IDS[:count])
    project, envelope, run = _authority(locked)
    assert len(envelope["owner_locks"]["by_slot"]["path_choice"]) == count
    if count == 0:
        assert envelope["owner_locks"]["by_slot"]["path_choice"] == []
        with pytest.raises(FoundryError) as exc:
            validate_delegated_choice_plan(run, project, _plan(paths=None, method=None), response_sha256="RESPONSE-4")
        assert exc.value.code == "CG1_DELEGATED_PATH_REQUIRED"
        return
    final = validate_delegated_choice_plan(run, project, _plan(paths=locked, method="METHOD-ALL"), response_sha256="RESPONSE-4")
    assert final["resolution"]["selected_path_ids"] == locked
    assert set(locked).issubset(set(final["resolution"]["actual_advancing_path_ids"]))
    assert all(row["provenance"] == "owner" for row in final["resolution"]["provenance"] if row["slot_id"] == "path_choice" and row["choice_id"] in locked)


def test_method_granted_extras_are_disclosed_and_ai_can_select_unspecified_legal_choices():
    project, envelope, run = _authority([CANONICAL_PATH_IDS[0]])
    final = validate_delegated_choice_plan(run, project, _plan(paths=[CANONICAL_PATH_IDS[0]], method="METHOD-ALL", sphere=["SPHERE-FIRE"]), response_sha256="RESPONSE-4")
    assert final["resolution"]["extra_method_granted_path_ids"] == list(CANONICAL_PATH_IDS[1:])
    assert {row["choice_id"] for row in final["resolution"]["provenance"] if row["provenance"] == "automatic"} == set(CANONICAL_PATH_IDS[1:])
    assert any(row["choice_id"] == "SPHERE-FIRE" and row["provenance"] == "AI" for row in final["resolution"]["provenance"])
    assert final["resolution"]["planner_prose_authority"] is False


def test_out_of_envelope_duplicate_count_conflict_and_method_incompatibility_fail_closed():
    project, envelope, run = _authority()
    _raises("CG1_DELEGATED_CHOICE_OUT_OF_ENVELOPE", _plan(paths=["PATH-NOT-OFFERED"], method="METHOD-ALL"), project, envelope)
    out_of_envelope_stage2 = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL")
    out_of_envelope_stage2["stage2_proposal"]["choices"] = [{
        "kind": "ai_bootstrap_sphere_acquisition",
        "record_id": "SPHERE-NOT-OFFERED",
    }]
    _raises("CG1_DELEGATED_CHOICE_OUT_OF_ENVELOPE", out_of_envelope_stage2, project, envelope)
    _raises("CG1_DELEGATED_DUPLICATE_CHOICE", _plan(paths=[CANONICAL_PATH_IDS[0], CANONICAL_PATH_IDS[0]], method="METHOD-ALL"), project, envelope)
    _raises("CG1_DELEGATED_CHOICE_COUNT_INVALID", _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL", sphere=["SPHERE-FIRE", "SPHERE-LOCKED"]), project, envelope)
    too_many_methods = _plan(paths=list(CANONICAL_PATH_IDS), method=None)
    too_many_methods["delegated_choice_selections"]["by_slot"]["method_choice"] = ["METHOD-ALL", "METHOD-BODY"]
    _raises("CG1_DELEGATED_CHOICE_COUNT_INVALID", too_many_methods, project, envelope)
    _raises("CG1_METHOD_PATH_INCOMPATIBLE", _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-BODY"), project, envelope)


def test_method_foundation_prerequisite_and_conflicting_authority_fail_closed():
    project, envelope, run = _authority()
    _raises("CG1_METHOD_FOUNDATION_INCOMPATIBLE", _plan(paths=[CANONICAL_PATH_IDS[0]], method="METHOD-ALL", foundation="FOUNDATION-BODY"), project, envelope)
    prereq_envelope = deepcopy(envelope)
    prereq_envelope["choices_by_slot"]["sphere_priorities"]["SPHERE-LOCKED"]["prerequisites"] = [{"operator": "requires", "target_id": "SPHERE-MISSING"}]
    prereq_envelope["envelope_sha256"] = __import__("app.core", fromlist=["sha256_json"]).sha256_json({k: v for k, v in prereq_envelope.items() if k != "envelope_sha256"})
    prereq_run = _run(project, prereq_envelope)
    _raises("CG1_DELEGATED_PREREQUISITE_UNMET", _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL", sphere=["SPHERE-LOCKED"]), project, prereq_envelope)
    conflict = _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL")
    conflict["stage2_proposal"]["catalog_priority_order"] = {"path_ids": [CANONICAL_PATH_IDS[0]]}
    _raises("CG1_DELEGATED_AUTHORITY_CONFLICT", conflict, project, envelope)


def test_historical_selection_intent_normalizes_explicit_acquisition_list():
    project, envelope, run = _authority([CANONICAL_PATH_IDS[0]])
    pair = {
        "kind": "__free_sphere_talent_pair__",
        "sphere_id": "SPHERE-FIRE",
        "record_id": "TALENT-FLAME",
    }
    plan = {
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "request_sha256": run["request"]["request_sha256"],
        "selection_intent": {
            "by_slot": {
                "path_choice": [CANONICAL_PATH_IDS[0]],
                "method_choice": ["METHOD-ALL"],
            },
        },
        "acquisition_intent": [pair],
        "owner_descriptive_fields": {"identity": {"name": "Intent Test"}, "concept": "Bounded"},
        "bounded_choices": {"ability_scores": {"STR": 8, "DEX": 15, "CON": 12, "INT": 10, "WIS": 10, "CHA": 10}},
    }
    intent = normalize_selection_intent(
        plan,
        request_sha256=run["request"]["request_sha256"],
        delegated_envelope=envelope,
        project=project,
        target_cl=1,
    )
    document = intent.as_dict()
    assert document["acquisition_intent"] == {
        "sphere_free_talent_pairs": [{
            "sphere_id": "SPHERE-FIRE",
            "talent_id": "TALENT-FLAME",
        }],
        "ordinary_talent_ids": [],
        "insight_occurrences": [],
    }
    assert "sphere_priorities" not in document["selected_by_slot"]


def test_stale_or_tampered_envelope_and_owner_lock_changes_are_rejected():
    project, envelope, run = _authority()
    tampered = deepcopy(envelope)
    tampered["allowed_choice_ids_by_slot"]["path_choice"] = list(CANONICAL_PATH_IDS[:1])
    _raises("CG1_DELEGATED_ENVELOPE_TAMPERED", _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL"), project, tampered)
    stale_project = deepcopy(project)
    stale_project["revision"] = 5
    with pytest.raises(FoundryError) as exc:
        validate_delegated_choice_plan(_run(stale_project, envelope), stale_project, _plan(paths=list(CANONICAL_PATH_IDS), method="METHOD-ALL"), response_sha256="RESPONSE-4")
    assert exc.value.code == "CG1_DELEGATED_ENVELOPE_STALE"
