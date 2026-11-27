"""Editing only power style preserves unrelated choices and request history."""

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


def draft_form(**changes):
    return {
        **dict(
            working_name="River Juniper",
            concept="A wandering cultivator who repairs bridges.",
            source_reference="An invented river folktale",
            target_cl=3,
            power_band="supporting",
            creation_mode="detailed",
            ability_scores={"STR": 10},
            selections={"path_choice": ["tianxia.path.qi_cultivation"]},
            generation_route="ai_bootstrap",
        ),
        **changes,
    }


@pytest.fixture
def draft(catalog_environment):
    db = catalog_environment["db"]
    created = CharacterBuilderService(db).create_project(**draft_form())
    store = ProjectStore(db)
    project_id = created["project_id"]
    store.save_builder_draft(project_id)
    CharacterBuilderService(db).commit_normal_first_cycle_catalog_choices(project_id)
    service = CharacterCreationExecutionService(
        db, stage1=Stage1ClipboardService(db), provider=None, project_store=store,
    )
    run = service.start(project_id, execution_mode="MANUAL_CHAT", idempotency_key="river-juniper-original")
    assert run["status"] == "WAITING_FOR_RESPONSE", run["status"]
    return service, store.get_project(project_id)["project"], run


def test_edit_brief_rebinds_power_style_without_changing_other_picks(draft):
    service, before, source = draft
    project_id = before["project_id"]
    form = draft_form(power_band="rival/boss")
    prepared = service.prepare_edit_brief(source["run_id"], form=form)
    validated_locks = prepared["payload"]["validated_creation_form"]["user_locks"]
    assert next(lock["value"] for lock in validated_locks if lock["field"] == "power_band") == "rival/boss"
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
    assert edited_locks["target_cl"] == original_locks["target_cl"]

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
    assert json.loads(edit["payload_json"])["validated_creation_form"]["user_locks"] == validated_locks


def test_prepared_form_edit_still_refuses_a_finished_character(draft):
    service, project, source = draft
    # Even a prepared edit on a non-terminal run can't modify a finished project.
    prepared = service.prepare_edit_brief(source["run_id"], form=draft_form(power_band="rival/boss"))
    service.projects.mark_builder_completed(project["project_id"])
    with pytest.raises(FoundryError) as refused:
        service.prepare_edit_brief(source["run_id"], form=draft_form(power_band="rival/boss"))
    assert refused.value.message == "A finished character changes through advancement, not Edit brief.", str(refused.value)
    with pytest.raises(FoundryError) as refused:
        service.edit_brief_create_new_request(source["run_id"], edit_id=prepared["edit_id"])
    assert refused.value.code == "CG1_EDIT_BRIEF_FINISHED", str(refused.value)
    saved = service.projects.get_project(project["project_id"])["project"]
    assert saved == project, saved


def test_edit_brief_unlocks_planning_and_submits_full_form():
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
function element(value = "") {
  return {
    value, disabled: false, dataset: {}, children: [],
    addEventListener(event, fn) { this[event] = fn; },
    dispatchEvent(event) { this[event.type]?.(event); },
    appendChild(child) { this.children.push(child); },
    setAttribute() {}, removeAttribute() {}, focus() {},
    classList: {remove() {} },
  };
}
const controls = new Map();
function field(id, value = "") {
  if (!controls.has(id)) controls.set(id, element(value));
  return controls.get(id);
}
const nameButtons = () => field("guidedNameChoices").children.filter(node => node.type === "button");
function clearNode(node) { node.children.length = 0; }
field("guidedName", "River Juniper");
field("guidedConcept", "A wandering cultivator");
field("guidedSource", "An invented folktale");
field("guidedPower", "supporting");
field("guidedLevel", "3");
const sheetPick = field("sheetBackground", "background.fixture");
const briefFields = ["guidedName", "guidedConcept", "guidedSource", "guidedPower"];
field("guidedCreate").reset = () => briefFields.forEach(id => { field(id).value = ""; });
const document = {
  getElementById: field,
  createElement() { return element(); },
  querySelector() { return null; },
  querySelectorAll(selector) {
    if (selector === "#guidedNameChoices button") return nameButtons();
    return selector.includes("#sheetBackground,") ? [sheetPick] : [];
  },
};
const PLANNING_FREEZE_MESSAGE = "saved";
const characterBuilderOptions = {};
const savedProjects = {
  "saved-draft": {
    "character.identity.display_name": "River Juniper", concept: "A wandering cultivator",
    source_reference: "An invented folktale", power_band: "supporting", target_cl: 3,
    "character_sheet.locked_choices": {background_choice: ["background.fixture"]},
  },
  "second-draft": {power_band: "supporting", target_cl: 3},
};
const action_availability = {edit_brief_create_new_request: {available: true}};
let guidedProjectId = "saved-draft";
let guidedRun = {run_id: "original", status: "NEEDS_REVIEW", starting_revision: 0, action_availability};
let guidedWizardStep = 4, guidedResponseSubmissionAction, status;
let selectedProject, guidedAutogenSeed, guidedRecovery, guidedFinalizeInFlight;
const guidedProviderStatus = null;
let guidedProjectLifecycle = {is_temporary: false};
let guidedNavigationGeneration = 0, methodCompatibilityRequestSerial = 0, methodCompatibility;
const restoredRun = {run_id: "second-run", status: "NEEDS_REVIEW", action_availability};
const reads = new Map([
  ["/api/character-builder/recovery", [{project_id: "second-draft", active_run: restoredRun}]],
  ["/api/character-creation/runs/second-run", restoredRun],
]);
const calls = [];
const preparedForms = new Map();
let names, prepare;
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function rollNames() {
  const response = names = deferred();
  const done = field("guidedNameDice").click();
  return async (name, seed) => {
    response.resolve({seed, names: [{name, hanzi: "", meaning: "fixture"}]});
    await done;
  };
}
function submit() {
  guidedWizardStep = 2;
  return field("guidedCreate").submit({preventDefault() {}, submitter: field("guidedBuildButton")});
}
function selectedSet() { return new Set(); }
function evaluateGuidedReadiness() { return {valid: true}; }
function collectAbilityScores() { return {}; }
function collectAcquisitionChoices() { return {}; }
function collectFeaturePicks() { return {}; }
function collectSheetSelections() { return sheetPick.value ? {background_choice: [sheetPick.value]} : {}; }
function methodPlanningMode() { return "AUTO"; }
function methodRouteChoiceForSubmission() { return null; }
function selectedGearPreferences() { return []; }
function loadGearPreferenceOptions() {}
let creationMode = "detailed";
function setGuidedStep(step) { guidedWizardStep = step; }
function applyGuidedExecutionPreference() {}
function resetGuidedResponseSource() {}
function renderGuidedResponseSourceState() {}
function renderGuidedCandidate() { renderPlanningFreeze(); }
function guidedNavigationIsCurrent(generation) { return generation === guidedNavigationGeneration; }
function resetGuidedCandidateGMAuthoring() {}
function methodCompatibilityKey() { return ""; }
function manualLineageResetState() {}
function setGuidedRoute() {}
function updateGuidedModeUI() {}
function renderOwnerMethodCompatibility() {}
function hideGuidedStartupRecovery() {}
function resetFinalCharacterReviewState() {}
function resetCharacterSheet() {}
function restoreCharacterSheet(locks) {
  sheetPick.value = locks["character_sheet.locked_choices"]?.background_choice?.[0] || "";
  // The real restore finishes by rendering the planning freeze after setting the mode.
  renderPlanningFreeze();
}
function setCreationMode(mode) { creationMode = mode; renderPlanningFreeze(); }
function showScreen() {}
function setGuidedStatus(message) { status = message; }
function plainAPIError(error) { return error.message; }
async function api(url, options) {
  if (url.startsWith("/api/names/generate?")) return names.promise;
  if (reads.has(url)) return reads.get(url);
  if (url.startsWith("/api/projects/")) {
    const locks = savedProjects[url.split("/").pop()];
    return {builder_lifecycle: {is_temporary: false}, project: {
      user_locks: Object.entries(locks).map(([field, value]) => ({field, value})),
    }};
  }
  assert.ok(options?.body, "Unexpected API call: " + url);
  const body = JSON.parse(options.body);
  calls.push([url, body]);
  if (url.endsWith("/prepare")) {
    const projectId = guidedProjectId;
    const prepared = await prepare.promise;
    preparedForms.set(prepared.edit_id, {projectId, form: body.form});
    return prepared;
  }
  const {projectId, form} = preparedForms.get(body.edit_id);
  Object.assign(savedProjects[projectId], {
    "character.identity.display_name": form.working_name, concept: form.concept,
    source_reference: form.source_reference, power_band: form.power_band, target_cl: form.target_cl,
    "character_sheet.locked_choices": form.selections,
  });
  return {run_id: body.edit_id === "current-edit" ? "current-child" : "child", action_availability};
}
eval(
  part("let guidedBriefEdit = null;", "let guidedProjectLifecycle") +
  part("function resetGuidedBuilder(", "function guidedPromptForChatGPT(") +
  part("function planningIsEditable(", "function setCreationMode(") +
  part("function restoreGuidedForm(", "function restoreCharacterSheet(") +
  part("function guidedRecoveryDescription(", "function recoveryActionButton(") +
  part("function guidedCreationForm(", '\ndocument.getElementById("guidedSaveDraft")') +
  part('document.getElementById("guidedEditBrief").onclick', '\ndocument.getElementById("guidedCancel")') +
  part('document.getElementById("guidedNameDice")?.addEventListener', 'document.getElementById("guidedNewCharacter")') +
  `(async () => {
    renderPlanningFreeze();
    assert.equal(field("guidedPower").disabled, true, "Power was not initially frozen");
    await field("guidedEditBrief").onclick();
    assert.equal(field("guidedPower").disabled, false, "Edit brief left Power disabled");
    assert.equal(field("guidedLevel").disabled, false, "Edit brief left Intended level disabled");
    assert.equal(sheetPick.disabled, false, "Edit brief left a sheet choice disabled");
    assert.deepEqual(calls, [], "opening the editor sent an API request");
    field("guidedRevisionNotes").value = "Do not send these cancelled notes.";
    sheetPick.value = "cancelled-background";
    const finishCancelledRoll = rollNames();
    field("guidedCancelBriefEdit").click();
    await field("guidedEditBrief").onclick();
    await finishCancelledRoll("Discarded name", "cancelled-seed");
    assert.deepEqual(nameButtons(), [], "A roll from the cancelled edit reached the reopened editor");

    field("guidedPower").value = "rival/boss";
    const finishDuringSave = rollNames();
    prepare = deferred();
    const submission = submit();
    assert.equal(field("guidedPower").disabled, true, "Power remains editable during request");
    assert.equal(field("guidedLevel").disabled, true, "Level remains editable during request");
    assert.equal(field("guidedRevisionNotes").disabled, true, "Notes remain editable during request");
    await finishDuringSave("Too early", "during-save-seed");
    assert.deepEqual(nameButtons(), [], "A pending name roll rendered during the save");
    assert.equal(field("guidedNameSeed").value, "", "A pending name roll updated the seed during the save");
    assert.equal(field("guidedName").value, "River Juniper", "A pending roll changed the name during the save");
    prepare.resolve({edit_id: "prepared"});
    await submission;
    assert.deepEqual(calls.map(([url]) => url), [
      "/api/character-creation/runs/original/edit-brief/prepare",
      "/api/character-creation/runs/original/edit-brief-create-new-request",
    ], "Build did not prepare and submit the edit");
    assert.equal(calls[0][1].form.power_band, "rival/boss");
    assert.equal(calls[0][1].form.target_cl, 3);
    assert.deepEqual(calls[0][1].form.selections, {background_choice: ["background.fixture"]});
    assert.equal(calls[0][1].owner_notes, "", "Cancelled notes leaked into the next request");
    assert.equal(calls[1][1].edit_id, "prepared");
    assert.equal(sheetPick.value, "background.fixture");
    assert.equal(field("guidedPower").disabled, true, "submitted Power stayed editable");

    await field("guidedEditBrief").onclick();
    await rollNames()("Stone Willow", "shown-seed");
    const [shown] = nameButtons();
    assert.equal(shown?.textContent, "Stone Willow", "The first roll did not render");
    const finishAfterSave = rollNames();
    prepare = deferred();
    const rejected = submit();
    assert.equal(shown.disabled, true, "A shown suggestion stayed enabled during the save");
    prepare.reject(new Error("Revision notes were rejected"));
    await rejected;
    assert.equal(status, "Revision notes were rejected");
    assert.equal(shown.disabled, false, "The rejected save left the suggestion disabled");
    await finishAfterSave("Too late", "after-save-seed");
    assert.deepEqual(nameButtons(), [shown], "A pending roll replaced the shown suggestion after the rejected save");
    assert.equal(field("guidedNameSeed").value, "shown-seed", "A pending roll changed the seed after the rejected save");
    assert.equal(field("guidedName").value, "River Juniper", "A pending roll changed the name after the rejected save");
    nameButtons()[0].click();
    assert.equal(field("guidedName").value, "Stone Willow", "An enabled suggestion stopped working after rejection");
    prepare = deferred();
    const retry = submit();
    prepare.resolve({edit_id: "retry"});
    await retry;
    assert.deepEqual(calls.slice(2).map(([url]) => url), [
      "/api/character-creation/runs/child/edit-brief/prepare",
      "/api/character-creation/runs/child/edit-brief/prepare",
      "/api/character-creation/runs/child/edit-brief-create-new-request",
    ], "The rejected save did not retry");
    assert.equal(calls[2][1].form.working_name, "River Juniper");
    assert.equal(calls[3][1].form.working_name, "Stone Willow");
    assert.deepEqual(calls[4][1], {edit_id: "retry"});

    await field("guidedEditBrief").onclick();
    field("guidedRevisionNotes").value = "Notes for the original character only.";
    prepare = deferred();
    const oldSave = submit();
    assert.equal(await restoreGuidedActiveBuild("second-draft", "second-run"), true, status);
    prepare.reject(new Error("Old save rejected"));
    await oldSave;
    await field("guidedEditBrief").onclick();
    assert.equal(field("guidedPower").disabled, false, "The previous save kept Power frozen on the restored character");
    field("guidedPower").value = "rival/boss";
    const nextRequest = calls.length;
    prepare = deferred();
    const submitRestored = submit();
    const [restoredUrl, restoredBody] = calls[nextRequest];
    assert.equal(restoredUrl, "/api/character-creation/runs/second-run/edit-brief/prepare");
    assert.equal(restoredBody.owner_notes, "");
    assert.equal(restoredBody.form.power_band, "rival/boss");
    prepare.resolve({edit_id: "second-prepared"});
    await submitRestored;

    for (const outcome of ["resolve", "reject"]) {
      assert.equal(await restoreGuidedActiveBuild("second-draft", "second-run"), true, status);
      await field("guidedEditBrief").onclick();
      prepare = deferred();
      const replacedSave = submit();
      assert.equal(field("guidedPower").disabled, true, "The old save did not lock the brief");
      await startNewCharacter();
      assert.equal(guidedRun, null, "Start New did not leave the saved run");
      for (const id of briefFields) {
        assert.equal(field(id).disabled, false, id + " stayed disabled on the new character while the old save was pending");
      }
      if (outcome === "resolve") prepare.resolve({edit_id: "late"});
      else prepare.reject(new Error("Old save rejected after reset"));
      await replacedSave;
      assert.equal(guidedRun, null, "A late " + outcome + " changed the new character's run");
      for (const id of briefFields) {
        assert.equal(field(id).disabled, false, id + " stayed disabled after the old save's " + outcome);
      }
    }

    assert.equal(await restoreGuidedActiveBuild("second-draft", "second-run"), true, status);
    await field("guidedEditBrief").onclick();
    field("guidedPower").value = "rival/boss";
    const sameRunRequests = calls.length;
    const stalePrepare = prepare = deferred();
    const staleSave = submit();

    assert.equal(await restoreGuidedActiveBuild("second-draft", "second-run"), true, status);
    await field("guidedEditBrief").onclick();
    field("guidedConcept").value = "A bridge builder";
    const currentPrepare = prepare = deferred();
    const currentSave = submit();
    const base = "/api/character-creation/runs/second-run";
    assert.deepEqual(calls.slice(sameRunRequests).map(([url]) => url), [
      base + "/edit-brief/prepare", base + "/edit-brief/prepare",
    ], "Both sessions must prepare on the same run");
    assert.equal(calls[sameRunRequests][1].form.power_band, "rival/boss");
    assert.equal(calls[sameRunRequests + 1][1].form.concept, "A bridge builder");

    stalePrepare.resolve({edit_id: "stale-edit"});
    await staleSave;
    assert.equal(guidedRun.run_id, "second-run", "The old save replaced the restored run");

    currentPrepare.resolve({edit_id: "current-edit"});
    await currentSave;
    assert.deepEqual(calls.slice(sameRunRequests).filter(([url]) => url.endsWith("/edit-brief-create-new-request")), [
      [base + "/edit-brief-create-new-request", {edit_id: "current-edit"}],
    ], "Only the reopened editor may commit its edit");
    assert.equal(guidedRun.run_id, "current-child", "The reopened editor's child was not applied");
  })().catch(error => { console.error(error); process.exitCode = 1; });`
);
"""],
        input=app_js.read_text(encoding="utf-8"), encoding="utf-8", capture_output=True, check=False, timeout=15,
    )
    assert result.returncode == 0, result.stderr or result.stdout
