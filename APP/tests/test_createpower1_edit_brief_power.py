"""Editing a saved draft changes its owner brief, not its other choices."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from app.core import FoundryError
from character_builder.service import CharacterBuilderService
from character_creation.service import CharacterCreationExecutionService
from creation_training_authority import CREATION_TRAINING_MAX_PER_CL
from project_store.service import ProjectStore
from stage1.service import Stage1ClipboardService


@pytest.fixture
def draft(catalog_environment):
    db = catalog_environment["db"]
    created = CharacterBuilderService(db).create_project(
        working_name="River Juniper",
        concept="A wandering cultivator who repairs bridges.",
        source_reference="An invented river folktale",
        target_cl=3,
        power_band="supporting",
        creation_mode="detailed",
        ability_scores={"STR": 10},
        selections={"path_choice": ["tianxia.path.qi_cultivation"]},
        generation_route="ai_bootstrap",
    )
    store = ProjectStore(db)
    project_id = created["project_id"]
    store.save_builder_draft(project_id)
    service = CharacterCreationExecutionService(
        db, stage1=Stage1ClipboardService(db), provider=None, project_store=store,
    )
    run = service.start(project_id, execution_mode="MANUAL_CHAT", idempotency_key="river-juniper-original")
    assert run["status"] == "WAITING_FOR_RESPONSE", run["status"]
    return service, store.get_project(project_id)["project"], run


def test_edit_brief_rebinds_power_style_without_changing_other_picks(draft):
    service, before, source = draft
    project_id = before["project_id"]
    expected_changes = [{"field": "power_band", "from": "supporting", "to": "rival/boss"}]
    prepared = service.prepare_edit_brief(source["run_id"], user_locks=[{"field": "power_band", "value": "rival/boss"}])
    assert prepared["payload"]["proposed_user_locks"] == expected_changes, prepared["payload"]
    still_saved = service.projects.get_project(project_id)["project"]
    assert still_saved == before, still_saved

    child = service.edit_brief_create_new_request(source["run_id"], edit_id=prepared["edit_id"])
    project = service.projects.get_project(project_id)["project"]
    revision = before["revision"] + 1
    assert (project["revision"], child["starting_revision"]) == (revision, revision), (
        project["revision"], child["starting_revision"],
    )
    original_locks = {lock["field"]: lock for lock in before["user_locks"]}
    edited_locks = {lock["field"]: lock for lock in project["user_locks"]}
    power = edited_locks.pop("power_band")
    old_power = original_locks.pop("power_band")
    assert (power["value"], power["created_revision"], power["lock_id"]) == (
        "rival/boss", revision, old_power["lock_id"],
    ), power
    assert edited_locks == original_locks, edited_locks
    assert project["content_lock"] == before["content_lock"], project["content_lock"]

    contract = child["request"]["delegated_choice_envelope"]["creation_training_contract"]
    assert contract["required_choices_by_cl"] == {
        str(cl): CREATION_TRAINING_MAX_PER_CL for cl in range(1, 4)
    }, contract["required_choices_by_cl"]
    old_run = service.get(source["run_id"])
    assert old_run["status"] == "REVISED", old_run["status"]
    assert old_run["request"] == source["request"], old_run["request"]["request_sha256"]
    with service.db.connection() as conn:
        edit = conn.execute(
            "SELECT status, child_run_id, payload_json FROM character_creation_brief_edits WHERE edit_id=?",
            (prepared["edit_id"],),
        ).fetchone()
    assert edit is not None, edit
    assert (edit["status"], edit["child_run_id"]) == ("CONSUMED", child["run_id"]), dict(edit)
    assert json.loads(edit["payload_json"])["proposed_user_locks"] == expected_changes, edit["payload_json"]


def test_edit_brief_refuses_other_picks_and_a_finished_character(draft):
    service, project, source = draft
    with pytest.raises(FoundryError) as refused:
        service.prepare_edit_brief(
            source["run_id"], user_locks=[{"field": "character_sheet.locked_choices", "value": {}}],
        )
    assert refused.value.code == "CG1_EDIT_BRIEF_USER_LOCKS_UNSUPPORTED", str(refused.value)

    # Even a prepared edit on a non-terminal run can't modify a finished project.
    prepared = service.prepare_edit_brief(source["run_id"], user_locks=[{"field": "power_band", "value": "rival/boss"}])
    service.projects.mark_builder_completed(project["project_id"])
    with pytest.raises(FoundryError) as refused:
        service.prepare_edit_brief(source["run_id"], user_locks=[{"field": "power_band", "value": "rival/boss"}])
    assert refused.value.message == "A finished character changes through advancement, not Edit brief.", str(refused.value)
    with pytest.raises(FoundryError) as refused:
        service.edit_brief_create_new_request(source["run_id"], edit_id=prepared["edit_id"])
    assert refused.value.code == "CG1_EDIT_BRIEF_FINISHED", str(refused.value)
    saved = service.projects.get_project(project["project_id"])["project"]
    assert saved == project, saved


def test_edit_brief_enables_only_brief_fields_and_submits_changed_power():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the creator's form handlers")
    app_js = Path(__file__).resolve().parents[1] / "static" / "app.js"
    result = subprocess.run(
        [node, "-e", r"""
const assert = require("node:assert/strict");
const js = require("node:fs").readFileSync(0, "utf8");
const part = (from, to) => {
  const start = js.indexOf(from);
  const end = js.indexOf(to, start + from.length);
  assert.ok(start >= 0 && end > start, `Missing app.js section: ${from}`);
  return js.slice(start, end);
};
const controls = new Map();
function field(id, value = "") {
  if (!controls.has(id)) controls.set(id, {
    value, disabled: false, dataset: {}, addEventListener(event, fn) { this[event] = fn; },
    setAttribute() {}, removeAttribute() {}, focus() {},
  });
  return controls.get(id);
}
field("guidedName", "River Juniper");
field("guidedConcept", "A wandering cultivator");
field("guidedSource", "An invented folktale");
field("guidedPower", "supporting");
field("guidedLevel", "3");
const sheetPick = field("sheetBackground", "background.fixture");
const document = {
  getElementById: field,
  querySelectorAll(selector) { return selector.includes("#sheetBackground,") ? [sheetPick] : []; },
};
const PLANNING_FREEZE_MESSAGE = "saved";
let guidedProjectId = "saved-draft", guidedBriefEdit = null;
let guidedRun = {run_id: "original", status: "NEEDS_REVIEW", starting_revision: 0,
  action_availability: {edit_brief_create_new_request: {available: true}}};
let guidedWizardStep = 4, guidedResponseSubmissionAction;
const calls = [];
let release;
const pending = new Promise(resolve => { release = resolve; });
function selectedSet() { return new Set(); }
let creationMode = "detailed";
function setGuidedStep(step) { guidedWizardStep = step; }
function applyGuidedExecutionPreference() {}
function resetGuidedResponseSource() {}
function renderGuidedResponseSourceState() {}
function renderGuidedCandidate() {}
function setGuidedStatus() {}
function plainAPIError(error) { throw error; }
async function api(url, options) {
  calls.push([url, JSON.parse(options.body)]);
  if (url.endsWith("/prepare")) await pending;
  return url.endsWith("/prepare") ? {edit_id: "prepared"} : {run_id: "child"};
}
eval(
  part("function planningIsEditable(", "function renderGuidedPersistence(") +
  part('document.getElementById("guidedCreate").addEventListener("submit"', '\ndocument.getElementById("guidedSaveDraft")') +
  part('document.getElementById("guidedEditBrief").onclick', '\ndocument.getElementById("guidedCancel")') +
  `(async () => {
    renderPlanningFreeze();
    assert.equal(field("guidedPower").disabled, true, "Power was not initially frozen");
    await field("guidedEditBrief").onclick();
    assert.equal(field("guidedPower").disabled, false, "Edit brief left Power disabled");
    assert.equal(field("guidedLevel").disabled, false, "Edit brief left Intended level disabled");
    assert.equal(sheetPick.disabled, true, "Edit brief unlocked a sheet choice");
    assert.deepEqual(calls, [], "opening the editor sent an API request");
    field("guidedPower").value = "rival/boss";
    const submission = field("guidedCreate").submit({preventDefault() {}, submitter: field("guidedBuildEditedBrief")});
    assert.equal(field("guidedPower").disabled, true, "Power remains editable during request");
    assert.equal(field("guidedLevel").disabled, true, "Level remains editable during request");
    assert.equal(field("guidedRevisionNotes").disabled, true, "Notes remain editable during request");
    release();
    await submission;
    assert.deepEqual(calls.map(([url]) => url), [
      "/api/character-creation/runs/original/edit-brief/prepare",
      "/api/character-creation/runs/original/edit-brief-create-new-request",
    ], "Build did not prepare and submit the edit");
    assert.deepEqual(calls[0][1].user_locks, [{field: "power_band", value: "rival/boss"}]);
    assert.equal(calls[1][1].edit_id, "prepared");
    assert.equal(sheetPick.value, "background.fixture");
    assert.equal(field("guidedPower").disabled, true, "submitted Power stayed editable");
  })().catch(error => { console.error(error); process.exitCode = 1; });`
);
"""],
        input=app_js.read_text(encoding="utf-8"), encoding="utf-8", capture_output=True, check=False, timeout=15,
    )
    assert result.returncode == 0, result.stderr or result.stdout
