// NOFOUNDCL1: creation Foundation picker is locked below the published CL, and
// the builder panel re-enables its selects after a successful load.
// Run: node --test APP/tests/no_foundation_cl1_dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import {fileURLToPath} from "node:url";
import {documentStub, registry} from "./gm_sheet_dom_stub/domstub.js";

const staticRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../static");
const sandbox = {
  console, document: documentStub, AbortController,
  setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
  fetch: async () => { throw new Error("network disabled in NOFOUNDCL1 DOM test"); },
  navigator: {userAgent: "nofoundcl1-dom"}, location: {assign() {}, reload() {}},
  localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
  Option: class { constructor(text = "", value = "") { this.textContent = text; this.value = value; } },
  addEventListener() {}, removeEventListener() {}, confirm: () => false, alert() {},
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
documentStub.getElementById("guidedManualLineageTrainingTypes").options = [{selected: false}];
for (const file of ["sphere_talent_logic.js", "sheet_view_model.js", "complete_request_save.js", "app.js"]) {
  vm.runInContext(fs.readFileSync(path.join(staticRoot, file), "utf8"), sandbox, {filename: file});
}

const FOUNDATION = "FOUNDATION-SYNTHETIC-01";
const CATALOG = {initial_foundation_acquisition_cl: 5, categories: []};

function setLevel(value) { documentStub.getElementById("guidedLevel").value = String(value); }

test("creation Foundation picker is disabled and cleared below CL5, enabled at CL5", () => {
  const select = documentStub.getElementById("sheetFoundation");
  const notice = documentStub.getElementById("sheetFoundationNotice");
  vm.runInContext(`characterBuilderOptions = ${JSON.stringify(CATALOG)}`, sandbox);

  setLevel(1);
  select.value = FOUNDATION;
  vm.runInContext("syncFoundationAvailability()", sandbox);
  assert.equal(select.disabled, true);
  assert.equal(select.value, "");
  assert.equal(notice.textContent, "Foundations open at level 5.");

  setLevel(4);
  vm.runInContext("syncFoundationAvailability()", sandbox);
  assert.equal(select.disabled, true);

  setLevel(5);
  vm.runInContext("syncFoundationAvailability()", sandbox);
  assert.equal(select.disabled, false);
  assert.equal(notice.textContent, "");
  select.value = FOUNDATION;
  assert.equal(select.value, FOUNDATION, "a CL5 pick is kept");
});

test("builder panel re-enables its non-sphere selects after a successful load", async () => {
  const ids = ["nonSphereAccessSources", "nonSpherePrimaryMethod", "nonSphereFoundation"];
  const pid = "00000000-0000-4000-8000-00000000cf01";
  const state = {paths: [], target_cl: 5, primary_method_id: null, foundation_id: null, access_source_records: []};
  const apiResponses = {
    "/api/non-sphere/authority/status": {status: "ok", method_count: 0, orthodox_foundation_count: 0, operative_pairwise_authority_rows: 0},
    "/api/non-sphere/paths": {records: []},
    "/api/non-sphere/foundations": {orthodox: []},
  };
  sandbox.api = async url => {
    if (url in apiResponses) return apiResponses[url];
    if (url.endsWith("/state")) return state;
    if (url.startsWith("/api/non-sphere/methods")) return {records: []};
    if (url.endsWith("/readiness") || url.endsWith("/ap-eligibility")) return {};
    if (url.endsWith("/evidence")) return {evidence: []};
    throw new Error("unexpected " + url);
  };
  vm.runInContext(`selectedProject = ${JSON.stringify(pid)}`, sandbox);

  for (const id of ids) documentStub.getElementById(id).disabled = true;
  await vm.runInContext(`loadNonSphereAuthorityPanel(${JSON.stringify(pid)})`, sandbox);
  for (const id of ids) assert.equal(documentStub.getElementById(id).disabled, false, id + " must be enabled after load");
});
