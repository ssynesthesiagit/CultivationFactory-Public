// SHEETAVAIL1: the pop-out sheet greys every row the table marks unavailable, including the "No action"
// rest-of-the-Attack rows after both attacks of the Attack action are spent (owner 2026-10-20: "those shouldnt be
// clickable if i dont have any actions"). The real sheet.js applyLegal/activate run against a tiny fake DOM, with the
// table's own `unavailable_reasons` text. It is greyed, never hidden here (the existing Show unavailable preference
// still decides visibility), the server's plain reason is on hover, and a click says it instead of round-tripping.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {unavailableRowsHidden} from "../static/tabletop/sheet-polish.js";

const sheetSource = fs.readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");
const REASON = "Both attacks from your Attack action are used.";
const IRON = "act:action:typed.test.natural.iron_fist";
const REST = "act:action:typed.test.natural.iron_fist.attack_action_rest";
const BONUS = "act:action:typed.test.bonus_action";
const BARE = "act:action:typed.test.modifier_row";  // a row drawn with no hover text of its own

class Element {
  constructor(tag = "div") {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.hidden = false;
    this.className = ""; this.style = {setProperty() {}};
    this.classList = {
      toggle: (name, force) => {
        const classes = new Set(this.className.split(/\s+/).filter(Boolean));
        if (force) classes.add(name); else classes.delete(name);
        this.className = [...classes].join(" ");
      },
      contains: name => this.className.split(/\s+/).includes(name),
    };
  }
  append(...children) { this.children.push(...children); }
  prepend(child) { this.children.unshift(child); }
  createElement(tag) { return new Element(tag); }
  set textContent(value) { this.children = [String(value)]; }
  get textContent() { return this.children.map(child => child instanceof Element ? child.textContent : child).join(""); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  hasAttribute(name) { return name in this.attributes; }
  get nextElementSibling() { return null; }
  addEventListener(name, fn) { this[`on${name}`] = fn; }
  remove() {}
  querySelectorAll(selector) {
    const result = [];
    for (const child of this.children) {
      if (!(child instanceof Element)) continue;
      const hasButtonId = selector.includes("[data-button-id]");
      const illegal = selector.includes(".is-illegal");
      const toggle = selector === ".unavailable-toggle";
      if ((toggle && child.classList.contains("unavailable-toggle")) ||
          (!toggle && hasButtonId && child.dataset.buttonId && (!illegal || child.classList.contains("is-illegal")))) result.push(child);
      result.push(...child.querySelectorAll(selector));
    }
    return result;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
}

function harness({legal = [], reasons = {}} = {}) {
  const row = (id, tip = null) => {
    const button = new Element("button");
    button.dataset.buttonId = id;
    if (tip != null) {
      button.dataset.tip = tip;
      button.tipCard = doc => {
        const card = doc.createElement("div");
        card.className = "tc";
        card.append(doc.createElement("p"));
        return card;
      };
    }
    return button;
  };
  const rows = [
    row(IRON, "Iron Fist attack\nA normal unarmed strike."),
    row(REST, "Iron Fist attack (rest of the Attack action)\nOne more attack of your Attack action."),
    row(BONUS, "A bonus action"),
    row(BARE),
  ];
  const list = new Element("div");
  list.append(...rows);
  const state = {
    connected: true, legal: new Set(legal), unavailable: reasons, showUnavailable: true, actor: null,
    byId: new Map([
      [IRON, {kind: "combat", label: "Iron Fist attack"}],
      [REST, {kind: "combat", label: "Iron Fist attack (rest of the Attack action)"}],
      [BONUS, {kind: "combat", label: "A bonus action"}],
      [BARE, {kind: "combat", label: "A modifier row"}],
    ]),
  };
  const toasts = [];
  const context = vm.createContext({
    state, Node: Element, WeakMap, Set, unavailableRowsHidden,
    document: {createElement: tag => new Element(tag), querySelectorAll: () => rows},
    localStorage: {getItem: () => null, setItem() {}},
    $: id => id === "action-list" ? list : null,
    markActive() {},
    toast: (...args) => toasts.push(args),
    presetQueue: {flush: async () => { throw new Error("a refused row must not flush presets"); }},
    post: message => { throw new Error(`a refused row must not post: ${JSON.stringify(message)}`); },
    pulse() {},
  });
  const extract = (start, end) => {
    const from = sheetSource.indexOf(start); const to = sheetSource.indexOf(end, from + start.length);
    assert.ok(from >= 0 && to > from, `Missing source boundary: ${start}`);
    return sheetSource.slice(from, to);
  };
  vm.runInContext([
    "const isCombatish = b => b && (b.kind === 'combat' || b.kind === 'combo');",
    extract("function h(tag, attrs, ...kids)", "function icon("),
    extract("function comboLegal(b)", "function economyPips("),
    extract("async function activate(", "async function doRoll("),
  ].join("\n"), context);
  return {rows, list, state, toasts, applyLegal: () => vm.runInContext("applyLegal()", context),
          activate: (id, el) => vm.runInContext("activate", context)(id, el)};
}

test("after both attacks of the Attack action, every rest row is greyed with the server's reason", () => {
  const ui = harness({legal: [IRON], reasons: {[REST]: REASON}});
  ui.applyLegal();
  const [iron, rest, bonus] = ui.rows;
  assert.equal(iron.classList.contains("is-legal"), true);
  assert.equal(iron.classList.contains("is-illegal"), false);
  assert.equal(iron.getAttribute("aria-description"), null);
  assert.equal(rest.classList.contains("is-illegal"), true);
  assert.equal(rest.classList.contains("is-legal"), false);
  assert.equal(rest.getAttribute("aria-description"), `Not available: ${REASON}`);
  assert.match(rest.dataset.tip, /Not available: Both attacks from your Attack action are used\./);
  const card = rest.tipCard(new Element("doc"), {});
  assert.equal(card.children[0].className, "tip-unavailable");
  assert.equal(card.children[0].textContent, `Not available: ${REASON}`);
  // A row that is merely not in the menu keeps the older neutral wording, with no invented reason.
  assert.equal(bonus.classList.contains("is-illegal"), true);
  assert.doesNotMatch(bonus.dataset.tip, /Not available/);
});

test("after one of two attacks the rest row stays usable", () => {
  const ui = harness({legal: [IRON, REST], reasons: {}});
  ui.applyLegal();
  const rest = ui.rows[1];
  assert.equal(rest.classList.contains("is-legal"), true);
  assert.equal(rest.classList.contains("is-illegal"), false);
  assert.equal(rest.getAttribute("aria-description"), null);
  assert.doesNotMatch(rest.dataset.tip, /Not available/);
  const card = rest.tipCard(new Element("doc"), {});
  assert.equal(card.children.some(child => child.className === "tip-unavailable"), false);
});

test("the reason clears when the table says the row is usable again", () => {
  const ui = harness({legal: [IRON], reasons: {[REST]: REASON}});
  ui.applyLegal();
  assert.match(ui.rows[1].dataset.tip, /Not available/);
  ui.state.legal = new Set([IRON, REST]);
  ui.state.unavailable = {};
  ui.applyLegal();
  const rest = ui.rows[1];
  assert.equal(rest.classList.contains("is-legal"), true);
  assert.equal(rest.classList.contains("is-illegal"), false);
  assert.equal(rest.getAttribute("aria-description"), null);
  assert.equal(rest.dataset.tip, "Iron Fist attack (rest of the Attack action)\nOne more attack of your Attack action.");
});

test("a row with no hover text of its own drops the refusal text once usable", () => {
  const ui = harness({legal: [IRON], reasons: {[BARE]: REASON}});
  ui.applyLegal();
  assert.equal(ui.rows[3].dataset.tip, `Not available: ${REASON}`);
  assert.equal(ui.rows[3].classList.contains("is-illegal"), true);
  ui.state.legal = new Set([IRON, BARE]);
  ui.state.unavailable = {};
  ui.applyLegal();
  assert.equal(ui.rows[3].dataset.tip, undefined);
  assert.equal(ui.rows[3].classList.contains("is-legal"), true);
});

test("clicking a row the table refuses says why instead of sending it", async () => {
  const ui = harness({legal: [IRON], reasons: {[REST]: REASON}});
  ui.applyLegal();
  await ui.activate(REST, ui.rows[1]);
  assert.equal(ui.toasts.length, 1);
  assert.equal(ui.toasts[0][0], "warn");
  assert.equal(ui.toasts[0][1], "Iron Fist attack (rest of the Attack action)");
  assert.equal(ui.toasts[0][2], REASON);
  assert.equal(ui.rows[1].classList.contains("sent"), false);
});
