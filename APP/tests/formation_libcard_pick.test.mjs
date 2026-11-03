import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

// libCard (sheet.js) must follow the option the player picked: the Use button, its legal style and the
// selected option all come from the choice, not from the first button of the card (formation review finding 4).
const sheet = readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");

function h(tag, attrs, ...kids) {
  return {tag, attrs: attrs || {}, kids: kids.flat(Infinity)};
}
function find(node, pred, out = []) {
  if (!node || typeof node === "string") return out;
  if (pred(node)) out.push(node);
  node.kids.forEach(kid => find(kid, pred, out));
  return out;
}

function harness(state) {
  const context = vm.createContext({
    h, state, LIB_STATUS: {action: {cls: "", label: "Action", title: ""}},
    layoutText: text => text, plainRules: text => text, cleanRules: text => text, ruleSummary: text => text,
    highlight: text => [text], snippet: () => null, rulesText: () => null,
  });
  vm.runInContext(sheet.slice(sheet.indexOf("function libCard("), sheet.indexOf("function renderLibrary(")), context);
  return context;
}

const buttons = new Map([
  ["b-locking", {id: "b-locking", label: "Combat Array: Locking Gate"}],
  ["b-nourish", {id: "b-nourish", label: "Combat Array: Nourishing Cycle"}],
]);
const item = {id: "rec.set", name: "Set Array", status: "action", kind: "Base ability", economy: "ACTION",
  text: "", summary: "", button_id: "b-locking", button_ids: ["b-locking", "b-nourish"]};

function state(picked) {
  const libPick = new Map(picked ? [[item.id, picked]] : []);
  return {libOpen: new Set(), libPick, byId: buttons, legal: new Set(["b-locking"])};
}

test("the Use button and the selected option follow the picked choice", () => {
  const first = harness(state(null)).libCard(item, "");
  assert.equal(find(first, node => node.attrs.class?.includes("lib-use"))[0].attrs["data-button-id"], "b-locking");
  const picked = harness(state("b-nourish")).libCard(item, "");
  const use = find(picked, node => node.attrs.class?.includes("lib-use"))[0];
  assert.equal(use.attrs["data-button-id"], "b-nourish");
  assert.doesNotMatch(use.attrs.class, /is-legal/, "the chosen option is not legal, so it must not look usable");
  const selected = find(picked, node => node.tag === "option" && node.attrs.selected)
    .map(node => node.attrs.value);
  assert.deepEqual(selected, ["b-nourish"]);
});

test("changing the choice and clicking Use activates the chosen action", () => {
  const listeners = {};
  const s = state(null);
  let rendered = 0, activated = null;
  const context = vm.createContext({
    state: s,
    $: () => ({addEventListener: (event, fn) => { listeners["sheet-" + event] = fn; }}),
    document: {addEventListener: (event, fn) => { listeners["document-" + event] = fn; }},
    renderLibrary: () => { rendered++; },
    activate: (id) => { activated = id; },
  });
  const start = sheet.indexOf("function wireSheet() {");
  const end = sheet.indexOf('  for (const tab of document.querySelectorAll', start);
  vm.runInContext(sheet.slice(start, end) + "}\nwireSheet();", context);
  const select = {dataset: {libChoice: item.id}, value: "b-nourish",
    closest: selector => selector === "[data-lib-choice]" ? select : null};
  listeners["document-change"]({target: select});
  assert.equal(s.libPick.get(item.id), "b-nourish");
  assert.equal(rendered, 1);
  const use = {disabled: false, dataset: {buttonId: "b-locking"},
    closest: selector => selector === ".lib-card" ? {querySelector: () => select} : null};
  listeners["sheet-click"]({target: {closest: selector => selector === "[data-button-id]" ? use : null}});
  assert.equal(activated, "b-nourish");
});
