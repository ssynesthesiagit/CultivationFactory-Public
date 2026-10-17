import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {test} from "node:test";

const source = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const start = source.indexOf("function guidedDraftCandidate(");
const end = source.indexOf("\n}\n", start) + 2;
const resumeStart = source.indexOf("function gmCharacterLibraryIsResumableDraft(");
const resumeEnd = source.indexOf("\n}\n", resumeStart) + 2;
const context = vm.createContext({});
vm.runInContext(source.slice(start, end) + "\\n" + source.slice(resumeStart, resumeEnd), context);
const canResume = context.gmCharacterLibraryIsResumableDraft;
const findDraft = context.guidedDraftCandidate;

const draft = {
  lifecycle: {persistence_state: "saved_draft"},
  source_revision: 1,
  workflow: {active_run: null, latest_run: {status: "CANCELLED", starting_revision: 1}},
};

test("saved draft with unchanged project after cancelled run is resumable", () => {
  assert.equal(canResume(draft), true);
  assert.equal(canResume({...draft, workflow: {...draft.workflow, latest_run: {status: "FAILED", starting_revision: 1}}}), true);
  assert.equal(canResume({...draft, source_revision: 2}), false);
});

test("active or finalized character is not offered Resume", () => {
  assert.equal(canResume({...draft, workflow: {...draft.workflow, active_run: {status: "PREPARING_REQUEST"}}}), false);
  assert.equal(canResume({...draft, lifecycle: {persistence_state: "completed"}}), false);
  assert.equal(findDraft([{...draft, status: "draft", builder_persistence_state: "saved_draft",
    workflow: {...draft.workflow, active_run: {status: "PREPARING_REQUEST"}}}]), null);
  assert.equal(findDraft([{...draft, status: "draft", builder_persistence_state: "saved_draft",
    revision: 1, workflow: draft.workflow}]).revision, 1);
});
