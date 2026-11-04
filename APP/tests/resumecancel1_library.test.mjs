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
vm.runInContext(source.slice(start, end) + "\n" + source.slice(resumeStart, resumeEnd), context);
const canResume = context.gmCharacterLibraryIsResumableDraft;
const findDraft = context.guidedDraftCandidate;

test("cancelled saved drafts use project revision, not library write counter", () => {
  const workflow = {active_run: null, latest_run: {status: "CANCELLED", starting_revision: 1}};
  const library = {lifecycle: {persistence_state: "saved_draft"}, source_revision: 7, workflow};
  const project = {status: "draft", revision: 1, builder_persistence_state: "saved_draft", character_creation_run_count: 1, workflow};
  assert.equal(canResume(library), true);
  assert.equal(findDraft([project]).revision, 1);
  assert.equal(findDraft([{...project, revision: 2}]), null);
  assert.equal(findDraft([{...project, workflow: null}]), null);
  assert.equal(findDraft([{...project, workflow: {...workflow, latest_run: {...workflow.latest_run, status: "FAILED"}}}]).revision, 1);
  assert.equal(canResume({...library, workflow: {...workflow, active_run: {status: "PREPARING_REQUEST"}}}), false);
  assert.equal(canResume({...library, lifecycle: {persistence_state: "completed"}}), false);
  assert.equal(findDraft([{...project, workflow: {...workflow, active_run: {status: "PREPARING_REQUEST"}}}]), null);
});
