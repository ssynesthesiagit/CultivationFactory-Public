// NOACTIONSHEET1: a No-action setting picked on the pop-out sheet updates only its own row.
// The owner hit this on the sheet (2026-10-20): every setting choice redrew the whole actions list. The handlers
// below are the real sheet.js functions, run with a tiny fake DOM: the preset reply and the table's "actor"
// message must sync the rider row in place (On/Off text and its dropdown), leaving the list, scroll, search and
// filter untouched. A refused save must restore the old control in place with the existing toast.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {PresetQueue} from "../static/tabletop/preset-queue.mjs";

const source = fs.readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");

function section(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `missing sheet source boundary: ${start}`);
  return source.slice(from, to);
}

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.attributes = {};
    this.children = [];
    this.parentElement = null;
    this.style = {setProperty() {}};
  }
  get className() { return this.attributes.class || ""; }
  set className(value) { this.attributes.class = String(value); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  hasAttribute(name) { return name in this.attributes; }
  get dataset() {
    return Object.fromEntries(Object.entries(this.attributes)
      .filter(([key]) => key.startsWith("data-"))
      .map(([key, value]) => [key.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()), value]));
  }
  set dataset(values) {
    for (const [key, value] of Object.entries(values)) {
      this.attributes[`data-${key.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}`] = String(value);
    }
  }
  get classList() {
    const names = () => this.className.split(/\s+/).filter(Boolean);
    return {
      contains: name => names().includes(name),
      toggle: (name, force) => {
        const has = names().includes(name);
        const want = force ?? !has;
        this.className = names().filter(n => n !== name).concat(want ? [name] : []).join(" ");
        return want;
      },
      add: name => { if (!names().includes(name)) this.className = [...names(), name].join(" "); },
      remove: (...list) => { this.className = names().filter(n => !list.includes(n)).join(" "); },
    };
  }
  append(...kids) { for (const kid of kids) this.appendChild(kid); }
  appendChild(kid) {
    if (kid instanceof Element) kid.parentElement = this;
    this.children.push(kid);
    return kid;
  }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(c => c !== this); }
  set textContent(value) { this.children = [String(value)]; }
  get textContent() { return this.children.map(child => child instanceof Element ? child.textContent : child).join(""); }
  get options() { return this.children.filter(child => child instanceof Element && child.tagName === "OPTION"); }
  get value() {
    const chosen = this.options.find(option => option.hasAttribute("selected")) || this.options[0];
    return chosen ? chosen.getAttribute("value") : "";
  }
  set value(value) {
    for (const option of this.options) {
      if (String(option.getAttribute("value")) === String(value)) option.setAttribute("selected", "");
      else option.removeAttribute("selected");
    }
  }
  querySelectorAll(selector) {
    const match = node => {
      if (selector === "[data-button-id]") return node.hasAttribute("data-button-id");
      if (selector === "[data-rider-key]") return node.hasAttribute("data-rider-key");
      if (selector === "[data-rider-select]") return node.hasAttribute("data-rider-select");
      return false;
    };
    const found = [];
    const walk = node => node.children.forEach(child => {
      if (!(child instanceof Element)) return;
      if (match(child)) found.push(child);
      walk(child);
    });
    walk(this);
    return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

const BUTTON = {
  id: "act:test.pressure", label: "Pressure-Point Strike", kind: "combat", attack_modifier: true,
  variant_of: "act:test.pressure.base", economy: "NONE", detail: {cost: "1 Stamina"},
  modifier: {id: "test.modifier", name: "Prefer disadvantage", description: ""},
};
const OFF = "act:test.pressure.disadvantage";
const ON = "act:test.pressure.off";
function riderRow({on, current}) {
  return {
    button_id: BUTTON.id, on,
    selectors: [{field: "effect", label: "Effect", current, options: [
      {button_id: OFF, value: "disadvantage", label: "Prefer disadvantage"},
      {button_id: ON, value: "off", label: "Off"},
    ]}],
  };
}

function harness() {
  const list = new Element("div");
  list.setAttribute("id", "action-list");
  list.scrollTop = 240;
  const root = new Element("body");
  root.appendChild(list);
  const toasts = [];
  const posts = [];
  const document = {
    createElement: tag => new Element(tag),
    getElementById: id => (id === "action-list" ? list : null),
    querySelectorAll: selector => root.querySelectorAll(selector),
  };
  const state = {
    projectId: "project:test",
    sheet: {actor_id: "actor:test", attack_modifier_rows: [riderRow({on: false, current: "disadvantage"})]},
    actor: {match_id: "match:1", actor_id: "actor:test", attack_modifier_rows: [riderRow({on: false, current: "disadvantage"})]},
    byId: new Map([[BUTTON.id, BUTTON], [BUTTON.variant_of, {id: BUTTON.variant_of, label: "Pressure-Point Strike"}]]),
    buttons: [BUTTON],
    connected: true, legal: new Set(), filter: "no_action", tab: "actions", featureQuery: "pressure",
    copySignature: "",
  };
  const context = {
    Node: Element,
    document,
    state,
    presetWindow: "sheet-1",
    posts,
    toasts,
    renders: {actions: 0, live: 0, legal: 0},
    $: id => (id === "action-list" ? list : null),
    describe: () => "", additionalRuleText: () => "", actionTipCard: () => ({}),
    toast: (...args) => toasts.push(args),
    post: message => posts.push(message),
    renderActions: () => { context.renders.actions += 1; },
    renderLive: () => { context.renders.live += 1; },
    applyLegal: () => { context.renders.legal += 1; },
    clearTimeout: () => {}, helloTimer: 0,
    presetQueue: {acceptRefresh() {}, next: new Map(), value: (_key, authoritative) => authoritative},
  };
  vm.createContext(context);
  vm.runInContext([
    section("function h(tag, attrs, ...kids)", "function icon("),
    section("function weaponCopyKeys(b)", "function comboLegal(b)"),
    section("function modifierRowFor(buttonId)", "function actionRow(b)"),
    section("function actionRow(b)", "// Hover text"),
    section("function riderKey(buttonId, field)", "let helloTimer"),
    section("function onMessage(msg)", "// ------------------------------------------------------------------ activation"),
  ].join("\n"), context);
  context.container = list;
  context.button = BUTTON;
  return {context, list, state, posts, toasts, document};
}

function drawRow(context) {
  vm.runInContext("container.replaceChildren(actionRow(button))", context);
  return context.container.children[0];
}

test("a saved No-action choice syncs its row in place and never redraws the list", async () => {
  const {context, list, state, posts} = harness();
  const rowNode = drawRow(context);
  const select = rowNode.querySelector("[data-rider-key]");
  const key = `match:1|${BUTTON.id}/effect`;
  const saved = [];
  const queue = new PresetQueue({
    send: async (scope, values) => {
      saved.push({scope, values});
      // The sheet's send callback merges the reply's modifier rows into the live view before the queue settles.
      state.actor.attack_modifier_rows = [riderRow({on: true, current: "off"})];
      return {state_version: 4, modifier_rows: state.actor.attack_modifier_rows};
    },
    changed: vm.runInContext("presetChanged", context),
    error: vm.runInContext("presetError", context),
    pending: vm.runInContext("presetPending", context),
    delay: 0,
  });
  context.presetQueue = queue;

  await queue.edit(key, ON, OFF, "match:1");
  await queue.flush("match:1");

  assert.equal(context.renders.actions, 0, "the whole actions list was not rebuilt");
  assert.equal(list.children[0], rowNode, "the row node itself is kept");
  assert.equal(rowNode.querySelector("[data-button-id]").textContent, `+ Pressure-Point Strike: On · turn off`);
  assert.equal(select.value, ON, "the dropdown shows the saved choice");
  assert.equal(list.scrollTop, 240, "scroll position is untouched");
  assert.equal(state.filter, "no_action", "the active filter is untouched");
  assert.equal(state.tab, "actions", "the active tab is untouched");
  assert.equal(state.featureQuery, "pressure", "the feature search is untouched");
  assert.deepEqual(saved, [{scope: "match:1", values: [ON]}], "the setting is still saved on the server");
  assert.deepEqual(posts.map(message => message.type), ["settings-pending", "settings-saved"]);
  assert.equal(posts.at(-1).ok, true);
});

test("a refused save restores the old choice in place with the existing toast", async () => {
  const {context, list, state, toasts} = harness();
  const rowNode = drawRow(context);
  const select = rowNode.querySelector("[data-rider-key]");
  const key = `match:1|${BUTTON.id}/effect`;
  const queue = new PresetQueue({
    send: async () => { throw new Error("That is not a preset this character owns."); },
    changed: vm.runInContext("presetChanged", context),
    error: vm.runInContext("presetError", context),
    pending: vm.runInContext("presetPending", context),
    delay: 0,
  });
  context.presetQueue = queue;

  await queue.edit(key, ON, OFF, "match:1");
  await assert.rejects(queue.flush("match:1"), /Choose it again before attacking/);

  assert.equal(context.renders.actions, 0, "a refusal does not rebuild the list either");
  assert.equal(list.children[0], rowNode, "the row node itself is kept");
  assert.equal(select.value, OFF, "the old choice is restored on the control");
  assert.equal(rowNode.querySelector("[data-button-id]").textContent, `+ Pressure-Point Strike: Off · turn on`, "the row still shows the old state");
  assert.equal(state.actor.attack_modifier_rows[0].on, false);
  assert.equal(toasts.length, 1);
  assert.equal(toasts[0][1], "Pressure-Point Strike — Pressure-Point Strike: Effect not saved");
  assert.match(toasts[0][2], /The previous choice was restored\./);
});

test("the table's actor message updates the row and active marks without redrawing", () => {
  const {context, list, state} = harness();
  const rowNode = drawRow(context);
  const before = [...list.children];
  const message = {
    type: "actor", actor_id: "actor:test", match_id: "match:1", state_version: 5,
    legal_button_ids: [BUTTON.id], button_states: {[BUTTON.id]: {active: true}},
    attack_modifier_rows: [riderRow({on: true, current: "off"})],
  };

  context.message = message;
  vm.runInContext("onMessage(message)", context);

  assert.equal(context.renders.actions, 0, "the table update does not rebuild the list");
  assert.equal(context.renders.legal, 1, "active/legal marks are re-applied in place");
  assert.equal(list.children[0], rowNode, "the row node itself is kept");
  assert.deepEqual([...list.children], before, "no section or row is re-created");
  assert.equal(list.scrollTop, 240, "scroll position is untouched");
  assert.equal(rowNode.querySelector("[data-button-id]").textContent, `+ Pressure-Point Strike: On · turn off`);
  assert.equal(state.filter, "no_action");
  assert.equal(state.tab, "actions");
});

test("a row drawn before the table connects adopts the live fight and follows the server", () => {
  const {context, list, state} = harness();
  // The sheet can be opened before any fight: the row is drawn with no match scope at all.
  state.actor = null;
  const rowNode = drawRow(context);
  const select = rowNode.querySelector("[data-rider-key]");
  assert.equal(select.dataset.riderKey, `|${BUTTON.id}/effect`, "the row is drawn without a fight's scope");
  assert.equal(select.value, OFF);

  context.message = {
    type: "actor", actor_id: "actor:test", match_id: "match:1", state_version: 5,
    legal_button_ids: [BUTTON.id], button_states: {}, attack_modifier_rows: [riderRow({on: true, current: "off"})],
  };
  vm.runInContext("onMessage(message)", context);

  assert.equal(context.renders.actions, 0, "connecting the table does not rebuild the list");
  assert.equal(list.children[0], rowNode, "the row node itself is kept");
  assert.equal(rowNode.querySelector("[data-button-id]").textContent, `+ Pressure-Point Strike: On · turn off`);
  assert.equal(select.value, ON, "the dropdown follows the server's new selector");
  assert.equal(select.dataset.riderKey, `match:1|${BUTTON.id}/effect`,
    "the control adopts the live fight, so later saves and receipts address this same dropdown");
});

test("a choice picked before the table connects survives the connect and is restored in place when refused", async () => {
  const {context, list, state, toasts} = harness();
  state.actor = null;
  const rowNode = drawRow(context);
  const select = rowNode.querySelector("[data-rider-key]");
  const key = `|${BUTTON.id}/effect`;
  const queue = new PresetQueue({
    send: async () => { throw new Error("That is not a preset this character owns."); },
    changed: vm.runInContext("presetChanged", context),
    error: vm.runInContext("presetError", context),
    pending: vm.runInContext("presetPending", context),
    delay: 10_000,
  });
  context.presetQueue = queue;

  await queue.edit(key, ON, OFF, "");
  assert.equal(select.value, ON, "the pick shows optimistically");

  // The table connects while that save is unsaved: the control adopts the fight, the pending pick still shows.
  context.message = {
    type: "actor", actor_id: "actor:test", match_id: "match:1", state_version: 2,
    legal_button_ids: [BUTTON.id], button_states: {}, attack_modifier_rows: [riderRow({on: false, current: "disadvantage"})],
  };
  vm.runInContext("onMessage(message)", context);
  assert.equal(select.dataset.riderKey, `match:1|${BUTTON.id}/effect`);
  assert.equal(select.value, ON, "an unsaved pick is not flickered back by the server's older value");
  assert.equal(list.children[0], rowNode);

  await assert.rejects(queue.flush(""), /Choose it again before attacking/);

  assert.equal(context.renders.actions, 0, "a refusal does not rebuild the list");
  assert.equal(select.value, OFF, "the refused choice is restored on the control, now under the live fight");
  assert.equal(rowNode.querySelector("[data-button-id]").textContent, `+ Pressure-Point Strike: Off · turn on`);
  assert.equal(toasts.length, 1);
  assert.match(toasts[0][2], /The previous choice was restored\./);
});
