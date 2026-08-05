from __future__ import annotations

from copy import deepcopy
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import FoundryError
from character_builder import CharacterBuilderService
from character_creation.service import CharacterCreationExecutionService
from project_store.service import ProjectStore


def _new_normal_project(builder: CharacterBuilderService, *, target_cl: int = 5) -> dict:
    return builder.create_project(
        working_name=f"WIN1 normal first-cycle {uuid.uuid4()}",
        concept="A normal wizard project whose first-cycle canonical plan is server-owned.",
        target_cl=target_cl,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={},
        sphere_priority_ids=[],
        talent_priority_ids=[],
        generation_route="ai_bootstrap",
    )


def _execution_service(db) -> CharacterCreationExecutionService:
    return CharacterCreationExecutionService(
        db,
        stage1=None,
        provider=None,
        project_store=ProjectStore(db),
    )


def _proposal_from_commit(commit: dict) -> dict:
    plan = commit["grant_plan"]
    sphere_id = plan["acquired_canonical_sphere_ids"][0]
    free_id = plan["grant_accounting"]["free_sphere_talent_grants"][0]["talent_id"]
    return {
        "target_cl": plan["target_cl"],
        "stage2_proposal": {
            "choices": [
                {"kind": "ai_bootstrap_sphere_acquisition", "record_id": sphere_id},
                {"kind": "ai_bootstrap_talent_acquisition", "record_id": free_id},
                *[
                    {"kind": "level_talent_acquisition", "record_id": talent_id}
                    for talent_id in plan["grant_accounting"]["ordinary_talent_ids"]
                ],
            ],
        },
    }


def test_incomplete_normal_canonical_acquisition_is_rejected_before_scratch(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    created = _new_normal_project(builder, target_cl=1)
    run = {"project_id": created["project_id"]}
    incomplete = {
        "target_cl": 1,
        "stage2_proposal": {
            "choices": [{
                "kind": "ai_bootstrap_sphere_acquisition",
                "record_id": "tianxia.sphere.fire",
            }],
        },
    }

    with pytest.raises(FoundryError) as exc:
        _execution_service(db)._validate_frozen_catalog_choices(run, incomplete)

    assert exc.value.code == "CG1_COMMITTED_CATALOG_CHOICE_PLAN_REQUIRED"


def test_normal_wizard_endpoint_commits_ready_first_cycle_plan_and_is_idempotent(catalog_environment):
    app = create_app(catalog_environment["settings"])
    with TestClient(app) as client:
        created = _new_normal_project(app.state.character_builder)
        token = client.get("/api/session").json()["token"]
        headers = {"X-Foundry-Token": token}
        endpoint = (
            f"/api/character-builder/projects/{created['project_id']}"
            "/normal-first-cycle-catalog-choice-lock"
        )

        first_response = client.post(endpoint, headers=headers, json={})
        assert first_response.status_code == 200, first_response.text
        first = first_response.json()
        plan = first["grant_plan"]
        accounting = plan["grant_accounting"]
        assert first["schema"] == "TianxiaFoundry.CanonicalCatalogChoiceCommit.v1"
        assert first["evidence_issued"] is False
        assert plan["schema"] == "TianxiaFactory.CanonicalGrantPlan.v1"
        assert plan["ready"] is True
        assert len(plan["acquired_canonical_sphere_ids"]) == 1
        assert len(accounting["free_sphere_talent_grants"]) == 1
        assert accounting["ordinary_talent_count"] == 5
        assert first["typed_choice_snapshot"]["project_revision"] == first["project_revision"]

        project = app.state.projects.get_project(created["project_id"])["project"]
        lock = next(
            row for row in project["user_locks"]
            if row["field"] == "character_creation.committed_catalog_choice_plan"
        )
        assert lock["source"] == "server-validated-canonical-choice-commit"
        assert lock["value"] == plan

        second_response = client.post(endpoint, headers=headers, json={})
        assert second_response.status_code == 200, second_response.text
        second = second_response.json()
        assert second["idempotent"] is True
        assert second["grant_plan"] == plan
        assert second["typed_choice_snapshot"] == first["typed_choice_snapshot"]


def test_catalog_planner_authority_and_revision_content_lock_safeguards_remain_enforced(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    created = _new_normal_project(builder)
    project_id = created["project_id"]
    committed = builder.commit_normal_first_cycle_catalog_choices(project_id)
    plan = committed["grant_plan"]
    ordinary = list(plan["grant_accounting"]["ordinary_talent_ids"])

    with pytest.raises(FoundryError) as duplicate_commit:
        builder.commit_catalog_choices(
            project_id,
            acquired_sphere_ids=list(plan["acquired_canonical_sphere_ids"]),
            free_talent_grants={
                row["sphere_id"]: row["talent_id"]
                for row in plan["grant_accounting"]["free_sphere_talent_grants"]
            },
            ordinary_talent_ids=ordinary,
        )
    assert duplicate_commit.value.code == "USER_LOCK_FIELD_IMMUTABLE"

    execution = _execution_service(db)
    run = {
        "project_id": project_id,
        "request": {"typed_choice_snapshot": committed["typed_choice_snapshot"]},
    }
    assert execution._require_frozen_choice_snapshot(run) == committed["typed_choice_snapshot"]
    wrong_content_snapshot = deepcopy(committed["typed_choice_snapshot"])
    wrong_content_snapshot["content_lock_hash"] = "0" * 64
    with pytest.raises(FoundryError) as wrong_content:
        execution._require_frozen_choice_snapshot({
            "project_id": project_id,
            "request": {"typed_choice_snapshot": wrong_content_snapshot},
        })
    assert wrong_content.value.code == "CG1_TYPED_CHOICE_SNAPSHOT_STALE"

    mismatched = _proposal_from_commit(committed)
    mismatched["stage2_proposal"]["choices"][-1]["record_id"] = ordinary[0]
    with pytest.raises(FoundryError) as proposal_mismatch:
        execution._validate_frozen_catalog_choices(run, mismatched)
    assert proposal_mismatch.value.code == "CG1_FROZEN_CATALOG_CHOICE_MISMATCH"

    ProjectStore(db).append_user_locks(
        project_id,
        [{"field": "character_sheet.owner_note", "value": "post-freeze mutation"}],
    )
    with pytest.raises(FoundryError) as stale_revision:
        execution._require_frozen_choice_snapshot(run)
    assert stale_revision.value.code == "CG1_TYPED_CHOICE_SNAPSHOT_STALE"
