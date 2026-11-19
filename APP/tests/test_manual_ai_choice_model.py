from __future__ import annotations

from copy import deepcopy
import io
import json
import zipfile

import pytest

from app.core import FoundryError, canonical_json, sha256_bytes
from character_creation.manual_ai_choice import (
    MANUAL_AI_CHOICE_MODEL_SCHEMA,
    MANUAL_AI_CORRECTION_SCHEMA,
    classify_ordinary_talent_corrections,
    build_compact_choice_model,
)
from character_creation.response_materialization import RESPONSE_SCHEMA
from character_creation.service import CharacterCreationExecutionService
from stage1.service import SLOT_SPECS, Stage1ClipboardService


def _authority(
    *,
    minimum_cl: int = 1,
    owner: str = "sphere.fire",
    channels: list[str] | None = None,
    kinds: list[str] | None = None,
) -> dict:
    return {
        "authority_complete": True,
        "allowed_kinds": kinds or ["level_talent_acquisition"],
        "allowed_channels": channels or ["level-choice"],
        "owning_canonical_sphere_id": owner,
        "minimum_cl": minimum_cl,
    }


def _row(name: str, authority: dict, *, prerequisites: list | None = None) -> dict:
    return {
        "choice_id": name,
        "name": f"Display {name}",
        "description": f"Short cue for {name}.",
        "content_type": "talent",
        "acquisition_channels": list(authority.get("allowed_channels") or []),
        "availability": {"minimum_cl": authority.get("minimum_cl")},
        "prerequisites": prerequisites or [],
        "incompatibilities": [],
    }


def _request() -> dict:
    authorities = {
        "talent.cl1": _authority(),
        "talent.early_a": _authority(),
        "talent.early_b": _authority(),
        "talent.late": _authority(minimum_cl=5),
        "talent.channel": _authority(),
        "talent.sphere": _authority(owner="sphere.water"),
        "talent.prereq": _authority(),
        "talent.free": _authority(),
    }
    rows = {
        choice_id: _row(
            choice_id,
            authority,
            prerequisites=[{"operator": "requires", "target_id": "talent.missing"}]
            if choice_id == "talent.prereq" else [],
        )
        for choice_id, authority in authorities.items()
    }
    return {
        "schema": "TianxiaFoundry.CharacterCreationCompleteRequest.v1",
        "project_id": "project.manual-test",
        "project_revision": 7,
        "request_sha256": "r" * 64,
        "content_lock_hash": "l" * 64,
        "delegated_choice_envelope": {
            "frozen_owner_target_cl": {"value": 5},
            "allowed_choice_ids_by_slot": {
                "advancement_skeleton": sorted(rows),
            },
            "choices_by_slot": {"advancement_skeleton": rows},
            "typed_choice_authority_by_slot": {
                "advancement_skeleton": {
                    "stage2_authority_by_choice": authorities,
                },
            },
            "ordinary_talent_count": 5,
        },
    }


def _bad_plan() -> dict:
    return {
        "target_cl": 5,
        "selection_intent": {"by_slot": {"sphere_priorities": ["sphere.fire"]}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [
                {"sphere_id": "sphere.fire", "talent_id": "talent.free"},
            ],
            "ordinary_talent_ids": [
                "talent.cl1",
                "talent.late",
                "talent.channel",
                "talent.sphere",
                "talent.prereq",
            ],
        },
    }


def _bounded_request() -> dict:
    milestone_id = "tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight.cl16"
    return {
        "schema": "TianxiaFoundry.CharacterCreationCompleteRequest.v1",
        "project_id": "project.manual-bounded-test",
        "project_revision": 12,
        "request_sha256": "b" * 64,
        "content_lock_hash": "c" * 64,
        "delegated_choice_envelope": {
            "frozen_owner_target_cl": {"value": 16},
            "owner_locks": {"by_slot": {"path_choice": ["path.qi_cultivation"]}},
            "choices_by_slot": {},
            "allowed_choice_ids_by_slot": {},
            "advancement_choice_milestones": [{
                "milestone_id": milestone_id,
                "path_id": "path.qi_cultivation",
                "feature_record_id": "feature.ability_score_improvement_or_cultivation_insight",
                "cl": 16,
                "allowed_kinds": ["ability_score_change", "cultivation_insight_acquisition"],
            }],
        },
    }


def _bounded_plan(request: dict) -> dict:
    return {
        "schema": RESPONSE_SCHEMA,
        "request_sha256": request["request_sha256"],
        "selection_intent": {"by_slot": {"path_choice": ["path.qi_cultivation"]}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": [],
            "insight_occurrences": [],
        },
        "bounded_choices": {
            "ability_scores": {ability: 10 for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")},
            "ability_score_changes_by_milestone_id": {},
        },
        "owner_descriptive_fields": {},
    }


def _resolve_event_authority(record: dict, *_args, **_kwargs):
    if record.get("record_id") == "talent.channel":
        raise FoundryError(
            "CG1_AUTHORITY_CHANNEL_NOT_ALLOWED",
            "The selected channel is not legal for this Talent.",
        )
    return "level_talent_acquisition", "level-choice", {}


def _correction_run() -> tuple[dict, dict]:
    request = _request()
    correction = classify_ordinary_talent_corrections(
        request,
        _bad_plan(),
        {},
        _resolve_event_authority,
    )
    assert correction is not None
    prior = canonical_json({"schema": "prior-response", "request_sha256": request["request_sha256"]})
    run = {
        "run_id": "run.manual-correction",
        "project_id": request["project_id"],
        "starting_revision": request["project_revision"],
        "execution_mode": "MANUAL_CHAT",
        "request": request,
        "response": {
            "exact_response_text": prior,
            "response_sha256": sha256_bytes(prior.encode("utf-8")),
        },
        "validation": {
            "last_submission_error": {
                "details": {"ai_correction_required": correction},
            },
        },
        "blockers": [{
            "code": "CG1_MANUAL_AI_CORRECTION_REQUIRED",
            "details": {"ai_correction_required": correction},
        }],
        "attempt_history": [{"attempt_id": "attempt.1", "ordinal": 1, "status": "BLOCKED"}],
    }
    return run, correction


def test_compact_model_is_deterministic_and_explicit_about_cl_positions() -> None:
    request = _request()
    first = build_compact_choice_model(request)
    second = build_compact_choice_model(deepcopy(request))

    assert first == second
    assert first["schema"] == MANUAL_AI_CHOICE_MODEL_SCHEMA
    assert first["request_sha256"] == request["request_sha256"]
    assert first["response_contract"]["array_position_semantics"] == (
        "zero-based array index N is the ordinary Talent acquired at CL N+1"
    )
    assert [row["cl"] for row in first["ordinary_talent_slots"]] == list(range(1, 21))
    assert [row["array_index"] for row in first["ordinary_talent_slots"]] == list(range(20))
    assert [row["active_for_request"] for row in first["ordinary_talent_slots"]] == [True] * 5 + [False] * 15
    for row in first["choices_by_slot"]["advancement_skeleton"]:
        assert set(row) == {
            "id", "display_name", "owner", "category", "minimum_cl",
            "hard_prerequisite_ids", "incompatibility_ids", "acquisition_channel",
            "semantic_cue",
        }
        assert "source" not in row
        assert "full_description" not in row
    by_cl = {row["cl"]: set(row["eligible_choice_ids"]) for row in first["ordinary_talent_slots"]}
    assert "talent.late" not in by_cl[2] | by_cl[3] | by_cl[4]
    assert "talent.late" in by_cl[5]


def test_background_package_ids_survive_old_prefix_cut_and_remain_linked() -> None:
    background_id = "tianxia.background.abandoned_orphan"
    sphere_id = "tianxia.background_sphere.scoundrel"
    talent_id = "tianxia.background_talent.scoundrel.hidden_tool_cache"
    sphere_ids = [f"tianxia.background_sphere.a{index:02d}" for index in range(1, 9)] + [sphere_id]
    talent_ids = [f"tianxia.background_talent.a{index:02d}" for index in range(1, 9)] + [talent_id]
    package_linkage = [{
        "package_index": 0,
        "sphere_record_id": "tianxia.sphere.scoundrel",
        "talent_record_id": "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE",
        "background_sphere_choice_id": sphere_id,
        "background_talent_choice_id": talent_id,
    }]
    record = {
        "record_id": background_id,
        "dependencies": [sphere_id, talent_id],
        "compatibility": {
            "factory": {
                "stage2_authority": {
                    "background_packages": [{
                        "sphere_record_id": "tianxia.sphere.scoundrel",
                        "talent_record_id": "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE",
                    }],
                },
            },
        },
    }

    assert sphere_id not in sorted(sphere_ids)[:8]
    assert talent_id not in sorted(talent_ids)[:8]
    assert Stage1ClipboardService._background_package_linkage(
        record,
        background_sphere_ids=set(sphere_ids),
        background_talent_ids=set(talent_ids),
    ) == package_linkage
    assert {
        spec["slot_id"]: spec["limit"]
        for spec in SLOT_SPECS
        if spec["slot_id"] in {"background_choice", "background_sphere_choice", "background_talent_choice"}
    } == {
        "background_choice": None,
        "background_sphere_choice": None,
        "background_talent_choice": None,
    }

    def choice_row(choice_id: str, content_type: str) -> dict:
        return {
            "choice_id": choice_id,
            "name": choice_id,
            "content_type": content_type,
            "description": choice_id,
        }

    rows_by_slot = {
        "background_choice": {background_id: choice_row(background_id, "background")},
        "background_sphere_choice": {
            choice_id: choice_row(choice_id, "background_sphere") for choice_id in sphere_ids
        },
        "background_talent_choice": {
            choice_id: choice_row(choice_id, "background_talent") for choice_id in talent_ids
        },
    }
    request = {
        "project_id": "project.background-linkage-test",
        "project_revision": 1,
        "request_sha256": "b" * 64,
        "content_lock_hash": "l" * 64,
        "delegated_choice_envelope": {
            "frozen_owner_target_cl": {"value": 1},
            "allowed_choice_ids_by_slot": {
                slot_id: sorted(rows) for slot_id, rows in rows_by_slot.items()
            },
            "choices_by_slot": rows_by_slot,
            "typed_choice_authority_by_slot": {
                "background_choice": {
                    "background_package_linkage": {background_id: package_linkage},
                },
            },
        },
    }

    model = build_compact_choice_model(request)
    assert sphere_id in {
        row["id"] for row in model["choices_by_slot"]["background_sphere_choice"]
    }
    assert talent_id in {
        row["id"] for row in model["choices_by_slot"]["background_talent_choice"]
    }
    assert model["background_package_linkage"] == {background_id: package_linkage}
    assert model["response_contract"]["background_package_linkage_field"] == "background_package_linkage"
    assert "do not infer or mix package rows" in model["response_contract"]["background_package_selection_semantics"]


def test_manual_correction_aggregates_invalid_positions_without_owner_choices() -> None:
    correction = classify_ordinary_talent_corrections(
        _request(),
        _bad_plan(),
        {},
        _resolve_event_authority,
    )

    assert correction is not None
    assert correction["schema"] == MANUAL_AI_CORRECTION_SCHEMA
    assert correction["classification"] == "AI_CORRECTION_REQUIRED"
    assert correction["request_sha256"] == "r" * 64
    assert correction["error_count"] == 4
    assert [row["array_index"] for row in correction["errors"]] == [1, 2, 3, 4]
    assert [row["cl"] for row in correction["errors"]] == [2, 3, 4, 5]
    assert [row["proposed_id"] for row in correction["errors"]] == [
        "talent.late", "talent.channel", "talent.sphere", "talent.prereq",
    ]
    assert correction["errors"][0]["reason_codes"] == ["MINIMUM_CL"]
    assert correction["errors"][1]["reason_codes"] == ["ACQUISITION_CHANNEL"]
    assert correction["errors"][2]["reason_codes"] == ["SPHERE_OWNERSHIP"]
    assert correction["errors"][3]["reason_codes"] == ["HARD_PREREQUISITE"]
    assert "talent.early_a" in correction["errors"][0]["legal_choice_ids"]
    assert all("legal_candidate_ids" in row for row in correction["errors"])


def test_correction_artifact_is_bound_deterministic_and_route_isolated() -> None:
    run, correction = _correction_run()
    service = object.__new__(CharacterCreationExecutionService)

    first = service._manual_ai_correction_package(run)
    second = service._manual_ai_correction_package(deepcopy(run))
    assert first["filename"] == second["filename"]
    assert first["payload"] == second["payload"]
    assert first["request_sha256"] == run["request"]["request_sha256"]
    assert first["response_sha256"] == run["response"]["response_sha256"]

    with zipfile.ZipFile(io.BytesIO(first["payload"])) as archive:
        assert set(archive.namelist()) == {
            "AI_CHOICE_MODEL.json", "AI_CORRECTION_INSTRUCTIONS.md",
            "AI_CORRECTION_REQUEST.json", "BINDING.json", "PRIOR_RESPONSE.json",
            "PRIOR_RESPONSE_EVIDENCE.json", "SHA256SUMS.txt",
        }
        correction_request = json.loads(archive.read("AI_CORRECTION_REQUEST.json"))
        binding = json.loads(archive.read("BINDING.json"))
        assert correction_request["request_binding"]["request_sha256"] == run["request"]["request_sha256"]
        assert correction_request["request_binding"]["prior_response_sha256"] == run["response"]["response_sha256"]
        assert correction_request["return_contract"] == {
            "same_chat": True,
            "preserve_request_sha256": run["request"]["request_sha256"],
            "next_factory_action": "Replace Response",
        }
        assert correction_request["error_count"] == correction["error_count"]
        assert binding["run_id"] == run["run_id"]
        assert archive.read("PRIOR_RESPONSE.json").decode("utf-8") == run["response"]["exact_response_text"]
        assert b"same chat" in archive.read("AI_CORRECTION_INSTRUCTIONS.md")

    with pytest.raises(FoundryError) as raised:
        service._manual_ai_correction_package({**run, "execution_mode": "STANDARD_API"})
    assert raised.value.code == "CG1_MANUAL_CORRECTION_MODE_MISMATCH"


def test_other_modes_and_server_finalization_guard_remain_separate() -> None:
    run, correction = _correction_run()
    service = object.__new__(CharacterCreationExecutionService)
    for mode in ("STANDARD_API", "AUTO_FINALIZE_WHEN_CLEAN"):
        assert service._manual_ai_correction_for_response(
            {"execution_mode": mode}, _bad_plan(), {},
        ) is None

    assert "unresolved_owner_decisions" not in run["validation"]
    with pytest.raises(FoundryError) as raised:
        service._require_owner_decisions_resolved(run)
    assert raised.value.code == "CG1_OWNER_DECISIONS_REQUIRED"
    assert raised.value.details["unresolved_count"] == 1
    assert correction["classification"] == "AI_CORRECTION_REQUIRED"


def test_manual_bounded_missing_milestone_is_same_ai_correction_with_legal_context() -> None:
    request = _bounded_request()
    plan = _bounded_plan(request)
    milestone_id = request["delegated_choice_envelope"]["advancement_choice_milestones"][0]["milestone_id"]
    error = FoundryError(
        "CG1_BOUNDED_DECISION_REQUIRED",
        "Resolve every source-backed advancement milestone exactly once with an ability-score change or Insight.",
        details={
            "field": f"bounded_choices.ability_score_changes_by_milestone_id.{milestone_id}",
            "milestone_id": milestone_id,
            "effective_cl": 16,
            "allowed_resolutions": ["ability_score_change", "cultivation_insight_acquisition"],
        },
        status_code=409,
    )
    service = object.__new__(CharacterCreationExecutionService)
    service._owner_decision_authority = lambda _run: {
        milestone_id: {
            "allowed_kinds": ["ability_score_change", "cultivation_insight_acquisition"],
            "ability_change": {
                "allowed_abilities": ["STR", "DEX"],
                "allowed_deltas": [1, 2],
                "budget": 2,
                "cap": 20,
            },
        },
    }
    run = {
        "execution_mode": "MANUAL_CHAT",
        "project_id": request["project_id"],
        "request": request,
    }
    response_text = canonical_json(plan)
    correction = service._manual_ai_correction_for_bounded_failure(run, response_text, error)

    assert correction is not None
    assert correction["classification"] == "AI_CORRECTION_REQUIRED"
    assert correction["response_field"] == error.details["field"]
    assert correction["errors"][0]["proposal"] is None
    assert correction["errors"][0]["proposal_state"] == "missing"
    assert correction["errors"][0]["reason_code"] == error.code
    assert correction["source_error"]["code"] == error.code
    candidates = correction["errors"][0]["legal_candidates"]
    assert len(candidates) == 3
    assert all(set(row) == {"id", "display_name", "semantic_cue", "kind", "milestone_id", "parameters"} for row in candidates)
    assert all(row["kind"] == "ability_score_change" and row["parameters"]["deltas"] for row in candidates)
    assert correction == service._manual_ai_correction_for_bounded_failure(run, response_text, error)


def test_bounded_correction_packet_is_deterministic_and_has_no_owner_decision_contract() -> None:
    request = _bounded_request()
    plan = _bounded_plan(request)
    milestone_id = request["delegated_choice_envelope"]["advancement_choice_milestones"][0]["milestone_id"]
    error = FoundryError(
        "CG1_BOUNDED_DECISION_REQUIRED",
        "Resolve every source-backed advancement milestone exactly once with an ability-score change or Insight.",
        details={
            "field": f"bounded_choices.ability_score_changes_by_milestone_id.{milestone_id}",
            "milestone_id": milestone_id,
            "effective_cl": 16,
        },
        status_code=409,
    )
    service = object.__new__(CharacterCreationExecutionService)
    service._owner_decision_authority = lambda _run: {
        milestone_id: {
            "ability_change": {
                "allowed_abilities": ["STR", "DEX"],
                "allowed_deltas": [1, 2],
                "budget": 2,
                "cap": 20,
            },
        },
    }
    response_text = canonical_json(plan)
    correction = service._manual_ai_correction_for_bounded_failure(
        {"execution_mode": "MANUAL_CHAT", "project_id": request["project_id"], "request": request},
        response_text,
        error,
    )
    assert correction is not None
    prior_sha256 = sha256_bytes(response_text.encode("utf-8"))
    run = {
        "run_id": "run.manual-bounded-correction",
        "project_id": request["project_id"],
        "starting_revision": request["project_revision"],
        "execution_mode": "MANUAL_CHAT",
        "request": request,
        "response": {"exact_response_text": response_text, "response_sha256": prior_sha256},
        "validation": {"last_submission_error": {"details": {"ai_correction_required": correction}}},
        "blockers": [{"code": "CG1_MANUAL_AI_CORRECTION_REQUIRED", "details": {"ai_correction_required": correction}}],
        "attempt_history": [{"attempt_id": "attempt.bounded.1", "ordinal": 1, "status": "BLOCKED"}],
        "manual_ai_correction": {
            "required": True,
            "errors": correction["errors"],
            "error_count": 1,
        },
    }
    first = service._manual_ai_correction_package(run)
    second = service._manual_ai_correction_package(deepcopy(run))
    assert first["payload"] == second["payload"]

    with zipfile.ZipFile(io.BytesIO(first["payload"])) as archive:
        payload = json.loads(archive.read("AI_CORRECTION_REQUEST.json"))
        row = payload["errors"][0]
        assert payload["request_binding"]["prior_response_sha256"] == prior_sha256
        assert payload["source_error"]["code"] == "CG1_BOUNDED_DECISION_REQUIRED"
        assert row["field"].endswith(milestone_id)
        assert row["proposal"] is None
        assert row["legal_candidate_ids"] == [candidate["id"] for candidate in row["legal_candidates"]]
        assert all(candidate["semantic_cue"] and candidate["parameters"] for candidate in row["legal_candidates"])
        assert archive.read("PRIOR_RESPONSE.json").decode("utf-8") == response_text

    from app.api import _owner_view

    owner = _owner_view(run)
    assert owner["decisions"] == []
    assert owner["ai_correction_required"] is True
    assert owner["review"]["status"] == "ai_correction_required"
    assert all(not row.get("legal_choices") for row in owner["blockers"])
