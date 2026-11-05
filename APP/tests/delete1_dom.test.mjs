// Real app.js card/filter actions in a DOM stub; no browser or GUI launched.
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
  fetch: async () => { throw new Error("network disabled in DELETE1 DOM test"); },
  navigator: {userAgent: "delete1-dom"}, location: {assign() {}, reload() {}},
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
const descendants = node => [node, ...(node.children || []).flatMap(descendants)];
const pid = "00000000-0000-4000-8000-000000000001";

test("delete cards name the character, cancel safely and send exact confirmation", async () => {
  for (const lifecycle of ["temporary", "saved_draft"]) {
    sandbox.gmRenderCharacterLibraryRows([{project_id: pid, name: "Unwanted Test", lifecycle: {persistence_state: lifecycle}, workflow: {}}]);
    const button = descendants(registry.get("characterCardList")).find(node => node.textContent === "Delete permanently");
    assert.ok(button);
    let dialog = "";
    let posted = null;
    sandbox.api = async (url, options) => { posted = {url, options}; return {}; };
    sandbox.confirm = message => { dialog = message; return false; };
    button.click();
    await Promise.resolve();
    assert.match(dialog, /Unwanted Test/);
    assert.match(dialog, /backups\/deleted-characters/);
    assert.match(dialog, /when the Factory next restarts/);
    assert.match(dialog, /Undo delete/);
    assert.equal(posted, null);
    sandbox.confirm = () => true;
    sandbox.loadProjects = async () => {};
    button.click();
    await Promise.resolve();
    assert.equal(posted.url, `/api/character-library/${pid}/delete-permanently`);
    assert.equal(posted.options.method, "POST");
    assert.deepEqual(JSON.parse(posted.options.body), {confirm_project_id: pid});
  }
  sandbox.gmRenderCharacterLibraryRows([{project_id: pid, name: "Finished Test", lifecycle: {persistence_state: "completed"}, workflow: {}}]);
  assert.equal(descendants(registry.get("characterCardList")).some(node => node.textContent === "Delete permanently"), false);
});

test("queued and failed hidden cards explain deletion and offer undo without open", async () => {
  for (const status of ["queued", "failed"]) {
    sandbox.gmRenderCharacterLibraryRows([{project_id: pid, working_name: "Hidden Test", deletion_status: status,
      deletion_reason: status === "failed" ? "Finish this character's saved fight before deleting it permanently." : null}]);
    const elements = descendants(registry.get("characterCardList"));
    assert.ok(elements.some(node => node.textContent === (status === "queued"
      ? "Will be deleted when the Factory next restarts" : "Deletion could not finish")));
    assert.ok(elements.some(node => node.textContent.includes(status === "failed" ? "saved fight" : "complete backup")));
    assert.equal(elements.some(node => node.textContent === "Delete permanently" || node.textContent === "Open"), false);
    let posted;
    sandbox.api = async (url, options) => { posted = {url, options}; return {}; };
    const undo = elements.find(node => node.textContent === "Undo delete");
    assert.ok(undo);
    undo.click();
    await Promise.resolve();
    assert.equal(posted.url, `/api/character-library/${pid}/undo-delete`);
    assert.equal(posted.options.method, "POST");
  }
});

test("archive filter makes archived names and deletion reachable", async () => {
  sandbox.api = async url => {
    if (url === "/api/character-library/archived") return [{project_id: pid, working_name: "Archived Test", archived_at: "2026-10-01", builder_lifecycle: {persistence_state: "completed"}}];
    return [];
  };
  await registry.get("showArchivedCharacters").onclick();
  const elements = descendants(registry.get("characterCardList"));
  assert.ok(elements.some(node => node.textContent === "Archived Test"));
  assert.ok(elements.some(node => node.textContent === "Archived character"));
  assert.ok(elements.some(node => node.textContent === "Delete permanently"));
  await registry.get("showArchivedCharacters").onclick();
  assert.equal(descendants(registry.get("characterCardList")).some(node => node.textContent === "Archived Test"), false);
});
