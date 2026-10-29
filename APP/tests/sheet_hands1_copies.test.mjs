// SHEETHANDS1: the pop-out sheet draws one row per physical weapon kind ("Biao Qiang (Javelin) ×2"),
// hides the compiler's per-copy rows, and points the drawn row at the copy the table actually offers.
// The real sheet.js groupButtons/applyLegal run against a tiny fake DOM, using the table's own reasons.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {unavailableRowsHidden} from "../static/tabletop/sheet-polish.js";

const source = fs.readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");
const BASE = "act:action:typed.test.weapon.biao_qiang";
const COPY2 = BASE + ".copy2";
const THROWN = BASE + "#thrown";
const THROWN2 = BASE + ".copy2#thrown";
const LABEL = "Biao Qiang (Javelin) ×2";
const RECOVER = "The weapon needed for this action is unavailable; recover it before attacking with it.";
const DRAW = "Draw Biao Qiang (Javelin) (copy 2) before attacking with it (no Action).";

class Element {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attributes = {};
    this.hidden = false; this.className = ""; this.style = {setProperty() {}};
    this.classList = {
      add: name => { if (!this.classList.contains(name)) this.className = [this.className, name].filter(Boolean).join(" "); },
      toggle: (name, force) => {
        const has = this.classList.contains(name);
        const want = force === undefined ? !has : Boolean(force);
        this.className = this.className.split(/\s+/).filter(n => n && n !== name).concat(want ? [name] : []).join(" ");
      },
      contains: name => this.className.split(/\s+/).filter(Boolean).includes(name),
    };
  }
  append(...kids) { this.children.push(...kids); }
  prepend(kid) { this.children.unshift(kid); }
  set textContent(value) { this.children = [String(value)]; }
  get textContent() { return this.children.map(child => child instanceof Element ? child.textContent : child).join(""); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  hasAttribute(name) { return name in this.attributes; }
  get nextElementSibling() { return null; }
  addEventListener() {}
  remove() { this.removed = true; }
  querySelectorAll(selector) {
    const found = [];
    for (const child of this.children) {
      if (!(child instanceof Element)) continue;
      const hasButtonId = selector.includes("[data-button-id]");
      const illegal = selector.includes(".is-illegal");
      const toggle = selector === ".unavailable-toggle";
      const copyLabel = selector === "[data-copy-label]";
      if ((toggle && child.classList.contains("unavailable-toggle"))
          || (hasButtonId && child.dataset.buttonId && (!illegal || child.classList.contains("is-illegal")))
          || (copyLabel && child.dataset.copyLabel)) found.push(child);
      found.push(...child.querySelectorAll(selector));
    }
    return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
}

function harness({legal = [], reasons = {}, copies = [BASE, COPY2]} = {}) {
  const label = new Element("span");
  label.dataset.copyLabel = "1";
  label.textContent = LABEL;
  const row = new Element("button");
  row.dataset.buttonId = BASE;
  row.append(label);
  const list = new Element("div");
  list.append(row);
  const base = {id: BASE, label: LABEL, kind: "combat", group: "attacks", copies: [BASE, COPY2],
                copy_keys: [BASE, COPY2], detail: {}};
  const copy2 = {...base, id: COPY2, copy_of: BASE};
  const state = {
    connected: true, legal: new Set(legal), unavailable: reasons, showUnavailable: true,
    actor: {weapon_copies: copies}, hidden: new Set(), buttons: [base, copy2],
    byId: new Map([[BASE, base], [COPY2, copy2]]),
  };
  const context = vm.createContext({
    state, Node: Element, WeakMap, Set, unavailableRowsHidden,
    document: {createElement: tag => new Element(tag), querySelectorAll: () => [row]},
    localStorage: {getItem: () => null, setItem() {}},
    $: id => id === "action-list" ? list : null,
    markActive() {},
    toast() {},
  });
  const extract = (start, end) => {
    const from = source.indexOf(start); const to = source.indexOf(end, from + start.length);
    assert.ok(from >= 0 && to > from, `Missing source boundary: ${start}`);
    return source.slice(from, to);
  };
  vm.runInContext([
    extract("function groupButtons(key)", "function renderFilters()"),
    "const isCombatish = b => b && (b.kind === 'combat' || b.kind === 'combo');",
    extract("function h(tag, attrs, ...kids)", "function icon("),
    extract("function weaponCopyKeys(b)", "function economyPips("),
  ].join("\n"), context);
  return {row, label, list, state,
          applyLegal: () => vm.runInContext("applyLegal()", context),
          groupButtons: key => vm.runInContext("groupButtons", context)(key)};
}

test("one drawn row hides the per-copy rows", () => {
  const ui = harness();
  assert.deepEqual(ui.groupButtons("attacks").map(row => row.id), [BASE]);
});

test("both copies carried: the row says ×2 and stays on the drawn copy", () => {
  const ui = harness({legal: [BASE]});
  ui.applyLegal();
  assert.equal(ui.row.dataset.buttonId, BASE);
  assert.equal(ui.label.textContent, "Biao Qiang (Javelin) ×2");
  assert.equal(ui.row.classList.contains("is-legal"), true);
});

test("stowed: the row is greyed with the draw reason", () => {
  const ui = harness({reasons: {[BASE]: DRAW, [COPY2]: DRAW}});
  ui.applyLegal();
  assert.equal(ui.row.dataset.buttonId, BASE);
  assert.equal(ui.label.textContent, "Biao Qiang (Javelin) ×2");
  assert.equal(ui.row.classList.contains("is-illegal"), true);
  assert.equal(ui.row.getAttribute("aria-description"), `Not available: ${DRAW}`);
});

test("after throwing copy 1 the count is ×1 and the row points at the carried spare", () => {
  const ui = harness({reasons: {[BASE]: RECOVER, [COPY2]: DRAW}, copies: [COPY2]});
  ui.applyLegal();
  assert.equal(ui.row.dataset.buttonId, COPY2);
  assert.equal(ui.label.textContent, "Biao Qiang (Javelin) ×1");
  assert.equal(ui.row.classList.contains("is-illegal"), true);
  // The spare's own reason, not the thrown copy's "recover it".
  assert.equal(ui.row.getAttribute("aria-description"), `Not available: ${DRAW}`);
});

test("a thrown row counts the carried copies behind its variant ids", () => {
  const ui = harness({reasons: {[THROWN]: RECOVER, [THROWN2]: DRAW}, copies: [COPY2]});
  const row = ui.state.buttons[0];
  row.copies = [THROWN, THROWN2];
  row.copy_keys = [BASE, COPY2];
  row.label = "Biao Qiang (Javelin) thrown ×2";
  const thrown = {...row, copies: undefined, copy_keys: undefined, copy_of: undefined};
  ui.state.byId.set(THROWN, {...thrown, id: THROWN});
  ui.state.byId.set(THROWN2, {...thrown, id: THROWN2});
  ui.applyLegal();
  assert.equal(ui.row.dataset.buttonId, THROWN2);
  assert.equal(ui.label.textContent, "Biao Qiang (Javelin) thrown ×1");
  assert.equal(ui.row.classList.contains("is-illegal"), true);
  assert.equal(ui.row.getAttribute("aria-description"), `Not available: ${DRAW}`);
});

test("drawing the spare makes the ×1 row usable on the spare's id", () => {
  const ui = harness({legal: [COPY2], copies: [COPY2]});
  ui.applyLegal();
  assert.equal(ui.row.dataset.buttonId, COPY2);
  assert.equal(ui.label.textContent, "Biao Qiang (Javelin) ×1");
  assert.equal(ui.row.classList.contains("is-legal"), true);
  assert.equal(ui.row.getAttribute("aria-description"), null);
});
