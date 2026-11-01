from __future__ import annotations

from copy import deepcopy
import json
import uuid

import pytest

from app.api import create_app
from app.core import FoundryError, canonical_json, sha256_json
from character_builder import CharacterBuilderService
from character_creation.current_fixture import (
    ABANDONED_ORPHAN,
    ADVANCEMENT_TALENTS,
    CINDER_HEART,
    FIRE,
    HIDDEN_TOOL_CACHE,
    HIDDEN_TOOL_CACHE_STAGE2,
    STREET_HARDENED,
    exact_stage1_response,
    stage2_choices,
)
from character_creation.delegated_choice_authority import catalog_stage2_selections
from path_method_authority import CANONICAL_PATH_IDS
from non_sphere_authority import NonSphereAuthorityService
from project_store.service import ProjectStore
from stage1.service import Stage1ClipboardService

BACKGROUND_SPHERE = "tianxia.background_sphere.scoundrel"
LEGACY_NON_FIRE_TALENTS = set(ADVANCEMENT_TALENTS[2:5])
CANONICAL_FIRE_REPLACEMENTS = (
    "tianxia.talent.fire.fire_ward",
    "tianxia.talent.fire.combustive_step",
    "tianxia.talent.fire.heat_haze",
)
JIANG_SUBPATH_PREFERENCES = {
    CANONICAL_PATH_IDS[0]: "tianxia.subpath.body.flesh_crucible",
    CANONICAL_PATH_IDS[1]: CINDER_HEART,
    CANONICAL_PATH_IDS[2]: "tianxia.tradition.spirit.dreamweaver",
}


def _jiang_subpath_ids(builder: CharacterBuilderService) -> list[str]:
    """Resolve stable canonical choices against the current authority surface.

    The IDs are canonical identities, not catalog positions.  Resolve them
    through the Character Builder's current NonSphereAuthority-decorated
    options so this fixture fails clearly if a source choice is no longer
    published, rather than silently selecting a different catalog row.
    """
    category = next(
        row for row in builder.options()["categories"]
        if row["slot_id"] == "subpath_choice"
    )
    choices = {row["choice_id"]: row for row in category.get("choices") or []}
    missing = sorted(set(JIANG_SUBPATH_PREFERENCES.values()) - set(choices))
    assert not missing, {
        "missing_canonical_subpath_ids": missing,
        "available_count": len(choices),
    }
    selected: list[str] = []
    for path_id in CANONICAL_PATH_IDS:
        choice_id = JIANG_SUBPATH_PREFERENCES[path_id]
        choice = choices[choice_id]
        assert choice.get("owning_path_id") == path_id, {
            "path_id": path_id,
            "choice_id": choice_id,
            "owning_path_id": choice.get("owning_path_id"),
        }
        assert choice.get("owning_path_choice_ids") == [path_id], choice
        selected.append(choice_id)
    return selected


def _jiang_run_subpath_ids(run: dict) -> list[str]:
    envelope = run["request"]["delegated_choice_envelope"]
    selected = list(envelope["owner_locks"]["by_slot"]["subpath_choice"])
    assert len(selected) == len(CANONICAL_PATH_IDS), selected
    choices = envelope["choices_by_slot"]["subpath_choice"]
    assert {
        choices[subpath_id]["owning_path_id"] for subpath_id in selected
    } == set(CANONICAL_PATH_IDS)
    return selected


def _new_jiang_normal_project(builder: CharacterBuilderService) -> dict:
    categories = {row["slot_id"]: row for row in builder.options()["categories"]}
    method = next(
        row for row in categories["method_choice"]["choices"]
        if row["choice_id"] == "METHOD-085"
    )
    route = method["method_planning"]["owner_route_options"][0]
    subpath_ids = _jiang_subpath_ids(builder)
    return builder.create_project(
        working_name="Jiang Yun",
        concept="A corrected three-Path Jiang Yun normal-wizard package.",
        target_cl=5,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={
            "path_choice": list(CANONICAL_PATH_IDS),
            "subpath_choice": subpath_ids,
            "background_choice": [ABANDONED_ORPHAN],
            "background_sphere_choice": [BACKGROUND_SPHERE],
            "background_talent_choice": [HIDDEN_TOOL_CACHE],
            "origin_insight_choice": [STREET_HARDENED],
            # METHOD-085 is the corrected all-three Method.  Its exact route
            # is owner-supplied access evidence; the Method choice itself
            # remains delegated to the complete-character response.
            "method_choice": ["METHOD-085"],
        },
        sphere_priority_ids=[],
        talent_priority_ids=[],
        generation_route="ai_bootstrap",
        method_planning_mode="EXACT",
        method_route_choice=route["choice_id"],
        method_learning_note="Corrected Jiang Yun all-three Method access route.",
    )


def _canonical_state(db, project_id: str) -> dict:
    project = ProjectStore(db).get_project(project_id)
    with db.connection() as conn:
        events = [
            row[0]
            for row in conn.execute(
                "SELECT event_json FROM events WHERE project_id=? ORDER BY sequence_no",
                (project_id,),
            )
        ]
    return {
        "revision": project["revision"],
        "project": project["project"],
        "events": events,
    }


def _method_for_paths(prompt: dict) -> str:
    method_slot = next(
        row for row in prompt["envelope"]["decision_slots"]
        if row["slot_id"] == "method_choice"
    )
    offered = {row["choice_id"] for row in method_slot["choices"]}
    compatible = prompt["envelope"]["path_method_authority"]["compatible_method_ids"]
    return next(method_id for method_id in compatible if method_id in offered)


def _prompt_choice_id(run: dict, slot_id: str, raw_id: str) -> str:
    rows = run["request"]["delegated_choice_envelope"]["choices_by_slot"][slot_id]
    if raw_id in rows:
        return raw_id
    raw_tail = raw_id.casefold().replace("-", "_").split(".")[-1]
    if raw_id.startswith("TAL_"):
        raw_tail = raw_id[4:].casefold().replace("-", "_").split("_")[-1]
    candidates = [
        choice_id for choice_id in rows
        if choice_id.casefold().replace("-", "_").split(".")[-1] == raw_tail
        or choice_id.casefold().replace("-", "_").endswith(raw_tail)
    ]
    assert len(candidates) == 1, (slot_id, raw_id, candidates)
    return candidates[0]


def _jiang_stage2_choices(run: dict, method_id: str) -> list[dict]:
    output: list[dict] = []
    original_rows = stage2_choices()
    existing_fire_talents = {
        row["record_id"] for row in original_rows
        if row["kind"] == "level_talent_acquisition"
        and row["record_id"].startswith("FIRE_TAL_")
    }
    envelope_rows = run["request"]["delegated_choice_envelope"]["choices_by_slot"]["advancement_skeleton"]
    legal_fire_replacements = [
        choice_id
        for choice_id in run["request"]["delegated_choice_envelope"]["allowed_choice_ids_by_slot"]["advancement_skeleton"]
        if choice_id in CANONICAL_FIRE_REPLACEMENTS
        and choice_id not in existing_fire_talents
        and (
            envelope_rows[choice_id].get("availability", {}).get("minimum_cl") is None
            or int(envelope_rows[choice_id]["availability"]["minimum_cl"]) <= 5
        )
    ]
    assert legal_fire_replacements, legal_fire_replacements
    replacement_by_legacy_id = dict(zip(sorted(LEGACY_NON_FIRE_TALENTS), legal_fire_replacements))
    subpath_ids = _jiang_run_subpath_ids(run)
    for row in original_rows:
        if row["kind"] == "path_acquisition":
            output.extend(
                {
                    **deepcopy(row),
                    "record_id": path_id,
                }
                for path_id in CANONICAL_PATH_IDS
            )
            output.append(
                {
                    "kind": "method_acquisition",
                    "effective_cl": 1,
                    "record_id": method_id,
                    "acquisition_channel": "method-acquisition",
                    "parameters": {},
                }
            )
        elif row["kind"] == "background_sphere_acquisition":
            output.append({
                **deepcopy(row),
                "record_id": _prompt_choice_id(run, "background_sphere_choice", row["record_id"]),
            })
        elif row["kind"] == "background_talent_acquisition":
            output.append({
                **deepcopy(row),
                "record_id": _prompt_choice_id(run, "background_talent_choice", row["record_id"]),
            })
        elif row["kind"] == "level_talent_acquisition" and row["record_id"] in LEGACY_NON_FIRE_TALENTS:
            replacement = replacement_by_legacy_id.get(row["record_id"])
            if replacement is None:
                continue
            output.append({**deepcopy(row), "record_id": replacement})
        elif row["kind"] == "typed_none" and row.get("parameters", {}).get("target") == "method":
            continue
        elif row["kind"] == "subpath_acquisition":
            # The fixture is intentionally a three-Path project.  Replace the
            # old one-global-Subpath row with one exact owner-bound acquisition
            # event for each selected Path; Stage 2 remains authoritative about
            # validating those per-Path milestones.
            output.extend(
                {
                    **deepcopy(row),
                    "record_id": subpath_id,
                }
                for subpath_id in subpath_ids
            )
        else:
            output.append(deepcopy(row))
    return output


def _jiang_plan(db, project_id: str, run: dict, method_id: str) -> dict:
    project_result = ProjectStore(db).get_project(project_id)
    project = project_result["project"]
    choices = _jiang_stage2_choices(run, method_id)
    subpath_ids = _jiang_run_subpath_ids(run)
    plan = {
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "request_sha256": run["request"]["request_sha256"],
        "stage1_response": exact_stage1_response(run["request"]["stage1_prompt"]),
        "target_cl": 5,
        "stage2_proposal": {
            "schema_version": "TianxiaFoundry.Stage2AdvancementProposal.v2",
            "project_id": project_id,
            # The real exact-Method production path commits the Stage 1
            # blueprint and then its authenticated Method-access event before
            # Stage 2.  Bind the closed Stage2 proposal to that post-access
            # revision, not the pre-response owner-lock revision.
            "expected_project_revision": int(project_result["revision"]) + 2,
            "expected_content_lock_hash": project["content_lock"]["lock_hash"],
            "target_cl": 5,
            "idempotency_key": "rec1.p1ar1.jiang-yun.stage2",
            "choices": choices,
        },
        "owner_descriptive_fields": {
            "identity": {"name": project["name"]},
            "concept": next(
                row["value"] for row in project["user_locks"]
                if row["field"] == "concept"
            ),
        },
        "uncertainties": [],
        "fallbacks": [],
        "output_profile": {"combat_ready": False, "profile": "CHARACTER_GM_MODEL"},
    }
    stage2 = catalog_stage2_selections(plan)
    final_talent_order = [*stage2["free_sphere_talent_ids"], *stage2["ordinary_talent_ids"]]
    # These are deliberately redundant response representations.  The final
    # plan must prove that Stage 1, delegated fields, priority order, and typed
    # Stage 2 rows all resolve to the same accepted values.
    plan["delegated_choice_selections"] = {
        "by_slot": {
            "path_choice": list(CANONICAL_PATH_IDS),
            "method_choice": [method_id],
            "subpath_choice": subpath_ids,
            "sphere_priorities": list(stage2["sphere_ids"]),
            "advancement_skeleton": final_talent_order,
        }
    }
    # Stage2AdvancementProposal.v2 is a closed schema.  Keep this redundant
    # response representation at the enclosing complete-plan level.
    plan["catalog_priority_order"] = {
        "path_ids": list(CANONICAL_PATH_IDS),
        "method_id": method_id,
        "sphere_ids": list(stage2["sphere_ids"]),
        "talent_ids": final_talent_order,
    }
    return plan


def test_jiang_yun_normal_wizard_delegated_authority_recovery(catalog_environment):
    app = create_app(catalog_environment["settings"])
    builder = app.state.character_builder
    created = _new_jiang_normal_project(builder)
    project_id = created["project_id"]

    # This is the same server helper reached by the normal wizard endpoint.
    hidden_commit = builder.commit_normal_first_cycle_catalog_choices(project_id)
    hidden_plan = hidden_commit["grant_plan"]
    hidden_sphere = hidden_plan["acquired_canonical_sphere_ids"][0]
    assert hidden_sphere != FIRE

    prompt = Stage1ClipboardService(app.state.db).generate_prompt(project_id)
    method_id = _method_for_paths(prompt)
    execution = app.state.character_creation
    run = execution.start(
        project_id,
        execution_mode="MANUAL_CHAT",
        idempotency_key="rec1.p1ar1.jiang-yun.normal",
    )
    assert run["request"]["delegated_choice_envelope"]
    assert run["request"]["delegated_choice_envelope"]["owner_locks"]["by_slot"]["path_choice"] == list(CANONICAL_PATH_IDS)
    subpath_ids = _jiang_run_subpath_ids(run)
    subpath_choices = run["request"]["delegated_choice_envelope"]["choices_by_slot"]["subpath_choice"]
    expected_subpath_bindings = {
        path_id: next(
            subpath_id
            for subpath_id in subpath_ids
            if subpath_choices[subpath_id]["owning_path_id"] == path_id
        )
        for path_id in CANONICAL_PATH_IDS
    }

    plan = _jiang_plan(app.state.db, project_id, run, method_id)
    assert plan["delegated_choice_selections"]["by_slot"]["subpath_choice"] == subpath_ids
    proposed_subpath_rows = [
        row
        for row in plan["stage2_proposal"]["choices"]
        if row["kind"] == "subpath_acquisition"
    ]
    assert [row["record_id"] for row in proposed_subpath_rows] == subpath_ids
    assert [row["effective_cl"] for row in proposed_subpath_rows] == [3, 3, 3]
    assert all(row["acquisition_channel"] == "subpath-selection" for row in proposed_subpath_rows)
    response_text = canonical_json(plan)
    before_preview = _canonical_state(app.state.db, project_id)
    preview = execution.submit_manual(
        run["run_id"],
        response_text=response_text,
        request_sha256=run["request"]["request_sha256"],
    )
    assert preview["status"] == "READY_FOR_REVIEW", canonical_json({"blockers": preview["blockers"], "warnings": preview["warnings"]})
    assert preview["dry_run"]["deterministic"] is True
    assert preview["dry_run"]["independent_compilations"] == 2
    assert _canonical_state(app.state.db, project_id) == before_preview

    final_plan = preview["final_plan"]
    assert final_plan["target_cl"] == 5
    assert final_plan["target_cl_authority"]["value"] == 5
    assert final_plan["catalog_response_authority"]["target_cl"] == 5
    accepted_grant_plan = final_plan["canonical_grant_plan"]
    assert accepted_grant_plan["acquired_canonical_sphere_ids"] == [FIRE]
    assert final_plan["canonical_grant_plan_sha256"] == sha256_json(accepted_grant_plan)
    assert final_plan["resolution"]["owner_required_or_proposed_path_ids"] == list(CANONICAL_PATH_IDS)
    assert final_plan["resolution"]["actual_advancing_path_ids"] == list(CANONICAL_PATH_IDS)
    assert final_plan["resolution"]["method_granted_path_ids"] == list(CANONICAL_PATH_IDS)
    assert final_plan["resolution"]["method_semantics"]["status"] == "selected"
    assert final_plan["resolution"]["planner_prose_authority"] is False
    assert final_plan["response_representations"]["stage2_mechanical_choices"]["sphere_ids"] == [FIRE]
    assert final_plan["response_representations"]["stage2_mechanical_choices"]["ordinary_talent_ids"]
    assert final_plan["resolution"]["selected_choices_by_slot"]["path_choice"] == list(CANONICAL_PATH_IDS)
    assert final_plan["resolution"]["selected_choices_by_slot"]["method_choice"] == [method_id]
    assert final_plan["resolution"]["selected_choices_by_slot"]["subpath_choice"] == subpath_ids
    assert final_plan["response_representations"]["delegated_choice_selections"]["by_slot"]["subpath_choice"] == subpath_ids
    assert final_plan["response_representations"]["stage2_mechanical_choices"]["subpath_or_tradition_ids"] == subpath_ids
    assert {
        path_id: next(
            subpath_id
            for subpath_id in final_plan["resolution"]["selected_choices_by_slot"]["subpath_choice"]
            if subpath_choices[subpath_id]["owning_path_id"] == path_id
        )
        for path_id in CANONICAL_PATH_IDS
    } == expected_subpath_bindings
    assert any(
        row["slot_id"] == "sphere_priorities" and row["provenance"] == "AI"
        for row in final_plan["resolution"]["provenance"]
    )
    assert any(
        row["slot_id"] == "advancement_skeleton" and row["provenance"] == "AI"
        for row in final_plan["resolution"]["provenance"]
    )

    changed = deepcopy(plan)
    changed["owner_descriptive_fields"]["concept"] = "a different response"
    with pytest.raises(FoundryError) as immutable:
        execution.submit_manual(
            run["run_id"],
            response_text=canonical_json(changed),
            request_sha256=run["request"]["request_sha256"],
        )
    assert immutable.value.code == "CG1_FINAL_PLAN_IMMUTABLE"
    assert _canonical_state(app.state.db, project_id) == before_preview

    finalized = execution.finalize(run["run_id"])
    assert finalized["status"] == "CLEAN_AND_FINALIZED"
    assert finalized["final_plan"] == final_plan
    assert finalized["final_plan"]["resolution"]["selected_choices_by_slot"]["subpath_choice"] == subpath_ids
    evidence = finalized["outputs"]["catalog_acquisition_evidence"]
    assert evidence["candidate_identity"] == finalized["dry_run"]["candidate_identity"]
    live_project = ProjectStore(app.state.db).get_project(project_id)["project"]
    materialized = next(
        row for row in live_project["user_locks"]
        if row["field"] == "character_creation.delegated_final_catalog_grant_plan"
    )
    assert materialized["value"] == accepted_grant_plan
    live_state = NonSphereAuthorityService(app.state.db).get_state(project_id)
    assert {
        row["path_id"]: row["subpath_or_tradition_id"]
        for row in live_state["paths"]
        if row["path_id"] in CANONICAL_PATH_IDS
    } == expected_subpath_bindings
    persisted_subpath_events = [
        json.loads(raw_event)
        for raw_event in _canonical_state(app.state.db, project_id)["events"]
        if json.loads(raw_event).get("advancement", {}).get("kind") == "subpath_acquisition"
    ]
    assert [event["subject"]["record_id"] for event in persisted_subpath_events] == subpath_ids
    assert {
        event["advancement"]["calculation"]["outputs"]["parent_path_id"]: event["subject"]["record_id"]
        for event in persisted_subpath_events
    } == expected_subpath_bindings
