// SOL197: real card and sheet renderers, without a browser or network.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import {fileURLToPath} from "node:url";
import {documentStub, registry} from "./gm_sheet_dom_stub/domstub.js";
import {describe, matchesQuery} from "../static/tabletop/fighter-picker.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../static");
const sandbox = {
  console, document: documentStub, AbortController,
  setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
  fetch: async () => { throw new Error("network disabled"); },
  navigator: {userAgent: "sol197"}, location: {assign() {}, reload() {}},
  localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
  Option: class { constructor(text = "", value = "") { this.textContent = text; this.value = value; } },
  addEventListener() {}, removeEventListener() {}, confirm: () => false, alert() {},
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
documentStub.getElementById("guidedManualLineageTrainingTypes").options = [{selected: false}];
for (const file of ["sphere_talent_logic.js", "sheet_view_model.js", "complete_request_save.js", "app.js"])
  vm.runInContext(fs.readFileSync(path.join(root, file), "utf8"), sandbox, {filename: file});
const descendants = node => [node, ...(node.children || []).flatMap(descendants)];
const summary = "Spirit Awakening (Soulstring Dancer) + Body Refining (Göruden)";
const row = {project_id: "sol197", name: "Two Paths", path: "Spirit Awakening", subpath: "Soulstring Dancer",
  path_summary: summary, current_cl: 10, cultivation_level: 10, workflow: {}};

test("actual library card includes both owned Subpaths, enrichment and single-path fallback", () => {
  sandbox.gmRenderCharacterLibraryRows([row]);
  const detail = descendants(registry.get("characterCardList")).find(n => n.className === "character-card-detail");
  assert.equal(detail.textContent, `${summary} · CL 10`);
  assert.equal(sandbox.gmCharacterCardDetail({...row, path_summary: null}, row), `${summary} · CL 10`);
  assert.equal(sandbox.gmCharacterCardDetail({...row, path_summary: null}, null), "Spirit Awakening · CL 10");
});

test("fighter picker displays and searches second Subpath; single Path is unchanged", () => {
  assert.equal(describe(row), `CL 10 · ${summary}`);
  assert.ok(matchesQuery(row, "goruden"));
  assert.equal(describe({...row, path_summary: null}), "CL 10 · Spirit Awakening · Soulstring Dancer");
});

test("real owner sheet header uses the server summary once", () => {
  const snapshot = JSON.parse(fs.readFileSync(path.join(root, "../tests/fixtures/gm_sheet/scratch_owner_sheet_snapshot.fixture.json")));
  sandbox.renderOwnerSheet({project_id: "sol197", name: "Two Paths", identity: {name: "Two Paths", current_cl: 10},
    path_summary: summary, owner_character_sheet: snapshot, sections: {}, readiness: {}, gm_export: {available: false}});
  const pills = descendants(registry.get("ownerCharacterSheet")).filter(n => n.className === "gm-pill gm-path-summary");
  assert.equal(pills.length, 1);
  assert.equal(pills[0].textContent, summary);
});

test("pop-out sheet header displays both Paths without changing single-Path text", () => {
  const source = fs.readFileSync(path.join(root, "tabletop/sheet.js"), "utf8");
  const header = source.slice(source.indexOf("function renderHeader()"), source.indexOf("// 2024 Carrying Capacity"));
  const context = {document: documentStub, $: id => documentStub.getElementById(id),
    showToken() {}, initials: () => "TP", state: {sheet: {}, summary: {
      name: "Two Paths", cultivation_level: 10, path: "Spirit Awakening", path_summary: summary}}};
  vm.createContext(context);
  vm.runInContext(header + "\nrenderHeader();", context);
  assert.equal(registry.get("char-sub").textContent, `CL 10 · ${summary}`);
  context.state.summary.path_summary = null;
  vm.runInContext("renderHeader();", context);
  assert.equal(registry.get("char-sub").textContent, "CL 10 · Spirit Awakening");
});
