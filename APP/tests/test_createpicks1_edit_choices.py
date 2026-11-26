"""A blocked draft can be repaired without losing its build history."""

from pathlib import Path
import subprocess

import pytest

from app.core import FoundryError, canonical_json
from catalog_choice_authority import DELEGATED_FINAL_CATALOG_GRANT_FIELD
from character_builder.service import CharacterBuilderService
from character_creation.choice_snapshot import materialize_choice_snapshot
from character_creation.service import CharacterCreationExecutionService
from non_sphere_authority.service import NonSphereAuthorityService
from project_store.service import ProjectStore
from stage1.service import Stage1ClipboardService


FORM = dict(
    working_name="Cedar Ferry", concept="A cultivator who repairs bridges.",
    source_reference="An invented story", target_cl=3, power_band="supporting",
    creation_mode="detailed", ability_scores={"STR": 10},
    selections={"path_choice": ["tianxia.path.qi_cultivation"]},
    generation_route="ai_bootstrap",
)


@pytest.fixture
def blocked(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    store = ProjectStore(db)
    project_id = builder.create_project(**FORM)["project_id"]
    builder.commit_normal_first_cycle_catalog_choices(project_id)
    service = CharacterCreationExecutionService(
        db, stage1=Stage1ClipboardService(db), provider=None, project_store=store,
    )
    run_id = service.start(
        project_id, execution_mode="MANUAL_CHAT", idempotency_key="cedar-ferry-original",
    )["run_id"]
    # Represent a persisted review blocker without calling an AI or building
    # an unrelated Stage 2 candidate.
    with db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET status='NEEDS_REVIEW',blockers_json=? WHERE run_id=?",
            (canonical_json([{"code": "DCC_LINEAR_PROGRESSION_UNSATISFIABLE", "message": "Choose a different Path."}]), run_id),
        )
    return service, builder, store.get_project(project_id)["project"], service.get(run_id)


def test_edit_blocked_draft_rebinds_paths_and_level_in_one_revision(blocked):
    service, _, before, source = blocked
    path = "tianxia.path.body_refining"
    availability = service._action_availability({
        **source, "response": {"response_sha256": "a" * 64},
    }, audit_provider=False)
    assert {key for key, action in availability.items() if action["available"]} == {
        "edit_brief_create_new_request", "cancel_build",
    }
    service.projects.materialize_server_derived_user_lock(
        before["project_id"], field=DELEGATED_FINAL_CATALOG_GRANT_FIELD,
        value={"schema": "TianxiaFactory.CanonicalGrantPlan.v1", "target_cl": 3},
        source="fixture:server-derived", lock_id="lock.fixture.old-final-plan",
    )
    prepared = service.prepare_edit_brief(
        source["run_id"], form={**FORM, "target_cl": 4, "selections": {"path_choice": [path]}},
    )
    child = service.edit_brief_create_new_request(source["run_id"], edit_id=prepared["edit_id"])
    project = service.projects.get_project(before["project_id"])["project"]
    assert project["revision"] == child["starting_revision"] == before["revision"] + 1
    snapshot = child["request"]["typed_choice_snapshot"]
    assert snapshot == materialize_choice_snapshot(project)
    locks = {row["field"]: row["value"] for row in snapshot["typed_locks"]}
    assert locks["character_sheet.locked_choices"]["path_choice"] == [path]
    assert locks["target_cl"] == 4
    assert not any(row["field"] == DELEGATED_FINAL_CATALOG_GRANT_FIELD for row in project["user_locks"])
    non_sphere = NonSphereAuthorityService(service.db).get_state(before["project_id"])
    assert {row["path_id"]: row["attainment"] for row in non_sphere["paths"] if row["attainment"]} == {path: 4}
    plan = locks["character_creation.committed_catalog_choice_plan"]
    assert plan["target_cl"] == 4
    assert len(plan["grant_accounting"]["ordinary_talent_ids"]) == 4
    old = service.get(source["run_id"])
    assert old["status"] == "REVISED"
    assert old["request"] == source["request"]
    assert old["blockers"] == source["blockers"]


def test_invalid_edit_uses_create_validation_and_writes_nothing(blocked):
    service, builder, before, source = blocked
    bad = {**FORM, "method_planning_mode": "EXACT"}
    with pytest.raises(FoundryError) as create_error:
        builder.create_project(**bad)
    with pytest.raises(FoundryError) as edit_error:
        service.prepare_edit_brief(source["run_id"], form=bad)
    assert edit_error.value.code == create_error.value.code == "CHARACTER_METHOD_EXACT_CHOICE_REQUIRED"
    assert service.projects.get_project(before["project_id"])["project"] == before
    with service.db.connection() as conn:
        assert [row["run_id"] for row in conn.execute(
            "SELECT run_id FROM character_creation_runs WHERE project_id=?", (before["project_id"],),
        )] == [source["run_id"]]
        assert conn.execute(
            "SELECT count(*) FROM character_creation_brief_edits WHERE source_run_id=?", (source["run_id"],),
        ).fetchone()[0] == 0


def test_finished_character_still_refuses_full_form_edit(blocked):
    service, _, before, source = blocked
    service.projects.mark_builder_completed(before["project_id"])
    with pytest.raises(FoundryError) as refused:
        service.prepare_edit_brief(source["run_id"], form=FORM)
    assert refused.value.code == "CG1_EDIT_BRIEF_FINISHED"


def test_blocker_row_uses_server_available_actions_once():
    static = Path(__file__).resolve().parents[1] / "static"
    result = subprocess.run(
        ["node", "-e", r"""
const assert = require("node:assert/strict");
const js = require("node:fs").readFileSync(0, "utf8");
const host = {children: [], appendChild(node) { this.children.push(node); }};
const document = {
  getElementById(id) { return id === "ownerPrimaryActions" ? host : null; },
  createElement(tag) { return {tag}; },
};
function clearNode(node) { node.children.length = 0; }
function ownerRunProgressing() { return false; }
function openGuidedBriefEditor() {}
function ownerViewFor() { return {}; }
function renderOwnerReviewStatus() {}
function renderOwnerNextAction() {}
function ownerNextActionDecision() {
  return {recovery: "localAIFix", label: "Fix with Local AI", disabled: true};
}
const start = js.indexOf("function appendOwnerActionButton(");
const end = js.indexOf("function renderOwnerNextAction()", start);
assert.ok(start >= 0 && end > start);
eval(js.slice(start, end) + `
  const run = {
    run_id: "blocked", status: "NEEDS_REVIEW", blockers: [{code: "fixture"}],
    action_availability: {
      edit_brief_create_new_request: {available: true}, cancel_build: {available: true},
      retry_local_ai_correction: {available: false}, retry_local_build: {available: false},
      replace_response: {available: false},
    },
  };
  const buttons = () => host.children.filter(node => node.tag === "button");
  renderOwnerPrimaryActions(run);
  assert.deepEqual(buttons().map(node => node.textContent), ["Edit brief", "Cancel"]);
  assert.ok(buttons().every(node => !node.disabled));
  run.action_availability.retry_local_ai_correction.available = true;
  run.action_availability.retry_local_build.available = true;
  run.action_availability.replace_response.available = true;
  renderOwnerPrimaryActions(run);
  assert.deepEqual(buttons().map(node => node.textContent), [
    "Fix with Local AI", "Retry Local Build", "Replace Response", "Edit brief", "Cancel",
  ]);
  assert.equal(buttons().filter(node => node.className === "primary-action")[0].textContent, "Fix with Local AI");
  assert.ok(buttons().every(node => !node.disabled));
`);
"""],
        input=(static / "app.js").read_text(), text=True, capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "ownerPrimaryActionsBottom" not in (static / "app.js").read_text()
    assert "ownerPrimaryActionsBottom" not in (static / "index.html").read_text()
