// SHEETAVAIL2: every row the table refuses is greyed with the server's own words, whatever kind of row it is.
// Owner report: the "Capoeira Spin: stand and make one Unarmed Strike" Bonus Action row looked usable while the
// character was standing, and clicking it failed (the server answered no_engine_issued_candidate). The sheet reads
// the table's unavailable_reasons map (static/tabletop/tabletop.js actorMessage), so a row is greyed once the table
// names a reason for it -- and this test pins that single rule for action rows: it depends on the row being the
// table's own "act:<source>" button, never on the row's kind or on any one ability. The real sheet.js applyLegal and
// activate run against a tiny fake DOM.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {unavailableRowsHidden} from "../static/tabletop/sheet-polish.js";

const sheetSource = fs.readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");
const PRONE = "You must be Prone to use this.";
const CAPOEIRA = "act:action:typed.test.sheetavail2.capoeira_spin";
const TECHNIQUE = "act:action:typed.test.sheetavail2.technique";
const UNDEFINED_ROW = "act:action:typed.test.sheetavail2.not_in_by_id";
const END_TURN = "turn:end";

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
    row(CAPOEIRA, "Capoeira Spin: stand and make one Unarmed Strike\nBonus Action, only if you started this turn Prone."),
    row(TECHNIQUE, "A technique row"),
    row(UNDEFINED_ROW),
    row(END_TURN, "End turn"),
  ];
  const list = new Element("div");
  list.append(...rows);
  const state = {
    connected: true, legal: new Set(legal), unavailable: reasons, showUnavailable: true,
    actor: {actor_id: "actor:test.owner", match_id: "match:test"},
    sheet: {actor_id: "actor:test.owner"},
    byId: new Map([
      [CAPOEIRA, {id: CAPOEIRA, kind: "combat", label: "Capoeira Spin: stand and make one Unarmed Strike"}],
      // A row kind the availability rule must not care about: the table's id, not its kind, makes it an action row.
      [TECHNIQUE, {id: TECHNIQUE, kind: "technique", label: "A technique row"}],
      [END_TURN, {id: END_TURN, kind: "system", label: "End Turn"}],
    ]),
  };
  const toasts = [];
  const posted = [];
  const context = vm.createContext({
    state, Node: Element, WeakMap, Set, unavailableRowsHidden,
    document: {createElement: tag => new Element(tag), querySelectorAll: () => rows},
    localStorage: {getItem: () => null, setItem() {}},
    $: id => id === "action-list" ? list : null,
    markActive() {},
    toast: (...args) => toasts.push(args),
    presetQueue: {flush: async () => {}},
    post: message => posted.push(message),
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
  return {rows, list, state, toasts, posted, applyLegal: () => vm.runInContext("applyLegal()", context),
          activate: (id, el) => vm.runInContext("activate", context)(id, el)};
}

test("a standing character's Capoeira Spin row is greyed with the named condition, never sent", async () => {
  const ui = harness({legal: [END_TURN], reasons: {[CAPOEIRA]: PRONE}});
  ui.applyLegal();
  const [capoeira] = ui.rows;
  assert.equal(capoeira.classList.contains("is-illegal"), true);
  assert.equal(capoeira.classList.contains("is-legal"), false);
  assert.equal(capoeira.getAttribute("aria-description"), `Not available: ${PRONE}`);
  // The row keeps its own rules card and the server's sentence goes first on it.
  assert.equal(capoeira.dataset.tip,
    `Capoeira Spin: stand and make one Unarmed Strike\nBonus Action, only if you started this turn Prone.\n\nNot available: ${PRONE}`);
  const card = capoeira.tipCard(new Element("doc"), {});
  assert.equal(card.children[0].className, "tip-unavailable");
  assert.equal(card.children[0].textContent, `Not available: ${PRONE}`);
  // Clicking says why instead of round-tripping to a refusal.
  await ui.activate(CAPOEIRA, capoeira);
  assert.deepEqual(ui.toasts, [["warn", "Capoeira Spin: stand and make one Unarmed Strike", PRONE, 5200]]);
  assert.equal(ui.posted.length, 0);
});

test("the same row is usable, and sends, once the character is Prone and the table lists it", async () => {
  const ui = harness({legal: [CAPOEIRA, END_TURN], reasons: {}});
  ui.applyLegal();
  const [capoeira] = ui.rows;
  assert.equal(capoeira.classList.contains("is-legal"), true);
  assert.equal(capoeira.classList.contains("is-illegal"), false);
  assert.equal(capoeira.getAttribute("aria-description"), null);
  assert.doesNotMatch(capoeira.dataset.tip, /Not available/);
  await ui.activate(CAPOEIRA, capoeira);
  assert.equal(ui.toasts.length, 0);
  assert.equal(ui.posted.length, 1);
  assert.equal(ui.posted[0].button_id, CAPOEIRA);
});

test("the rule is the table's id, not the row's kind: another kind of action row is greyed the same way", () => {
  const ui = harness({legal: [END_TURN], reasons: {[TECHNIQUE]: PRONE, [UNDEFINED_ROW]: PRONE}});
  ui.applyLegal();
  const [, technique, undefinedRow] = ui.rows;
  for (const row of [technique, undefinedRow]) {
    assert.equal(row.classList.contains("is-illegal"), true);
    assert.equal(row.getAttribute("aria-description"), `Not available: ${PRONE}`);
  }
});

test("Turn: End stays out of the refusal wording when the table lists it", () => {
  const ui = harness({legal: [END_TURN], reasons: {[CAPOEIRA]: PRONE}});
  ui.applyLegal();
  const endTurn = ui.rows[3];
  assert.equal(endTurn.classList.contains("is-legal"), true);
  assert.equal(endTurn.getAttribute("aria-description"), null);
});
