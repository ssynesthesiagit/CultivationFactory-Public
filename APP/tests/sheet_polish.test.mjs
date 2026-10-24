import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {unavailableRowsHidden} from "../static/tabletop/sheet-polish.js";

const sheetSource = fs.readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");

class Element {
  constructor(tag = "div") {
    this.tagName = tag; this.children = []; this.dataset = {}; this.attributes = {}; this.hidden = false; this.className = "";
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
  set textContent(value) { this.children = [String(value)]; }
  get textContent() { return this.children.map(child => child instanceof Element ? child.textContent : child).join(""); }
  prepend(child) { child.parent = this; this.children.unshift(child); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, fn) { this[`on${name}`] = fn; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
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

function actionListHarness(savedChoice = null) {
  const rows = ["strike", "spell", "guard"].map(buttonId => {
    const row = new Element("button"); row.dataset.buttonId = buttonId; row.className = ""; return row;
  });
  const list = new Element("div"); list.children.push(...rows);
  const storage = new Map(savedChoice === null ? [] : [["tianxia-sheet-show-unavailable", savedChoice]]);
  const state = {
    connected: true, legal: new Set(["strike", "guard"]), showUnavailable: false,
    actor: null, byId: new Map(rows.map(row => [row.dataset.buttonId, {kind: "combat"}])),
  };
  const context = vm.createContext({
    state, Node: Element, unavailableRowsHidden,
    document: {createElement: tag => new Element(tag), querySelectorAll: () => rows},
    localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value)},
    $: id => id === "action-list" ? list : null, markActive() {},
  });
  const extract = (start, end) => {
    const from = sheetSource.indexOf(start); const to = sheetSource.indexOf(end, from + start.length);
    assert.ok(from >= 0 && to > from, `Missing source boundary: ${start}`);
    return sheetSource.slice(from, to);
  };
  vm.runInContext([
    "const isCombatish = b => b && (b.kind === 'combat' || b.kind === 'combo');",
    extract("function h(tag, attrs, ...kids)", "function icon("),
    extract("function applyLegal()", "function economyPips("),
  ].join("\n"), context);
  if (savedChoice !== null) {
    state.showUnavailable = storage.get("tianxia-sheet-show-unavailable") === "true";
  }
  return {rows, list, state, storage, applyLegal: () => vm.runInContext("applyLegal()", context)};
}

test("unavailable actions hide only when connected, present, and not explicitly shown", () => {
  assert.equal(unavailableRowsHidden(true, 2, false), true);
  assert.equal(unavailableRowsHidden(true, 2, true), false);
  assert.equal(unavailableRowsHidden(false, 2, false), false);
  assert.equal(unavailableRowsHidden(null, 2, false), false);
  assert.equal(unavailableRowsHidden(true, 0, false), false);
});

test("real legality update hides, toggles, restores preference, and clears rows offline", () => {
  const ui = actionListHarness();
  ui.applyLegal();
  assert.deepEqual(ui.rows.map(row => row.hidden), [false, true, false]);
  let toggle = ui.list.querySelector(".unavailable-toggle");
  assert.equal(toggle.textContent, "Show unavailable (1)");
  toggle.onclick();
  assert.deepEqual(ui.rows.map(row => row.hidden), [false, false, false]);
  assert.equal(ui.storage.get("tianxia-sheet-show-unavailable"), "true");
  assert.equal(ui.list.querySelector(".unavailable-toggle").textContent, "Hide unavailable (1)");

  const restored = actionListHarness("true");
  restored.state.showUnavailable = true;
  restored.applyLegal();
  assert.deepEqual(restored.rows.map(row => row.hidden), [false, false, false]);
  assert.equal(restored.list.querySelector(".unavailable-toggle").textContent, "Hide unavailable (1)");

  restored.state.connected = false;
  restored.state.legal = null;
  restored.applyLegal();
  assert.deepEqual(restored.rows.map(row => row.hidden), [false, false, false]);
  assert.equal(restored.list.querySelector(".unavailable-toggle"), null);
});

test("legality recovery reveals rows that were already hidden", async t => {
  const hiddenUnavailableHarness = () => {
    const ui = actionListHarness();
    ui.rows[1].hidden = true;
    ui.rows[1].classList.toggle("is-illegal", true);
    return ui;
  };

  await t.test("offline", () => {
    const ui = hiddenUnavailableHarness();
    ui.state.connected = false;
    ui.state.legal = null;

    ui.applyLegal();

    assert.deepEqual(ui.rows.map(row => row.hidden), [false, false, false]);
    assert.equal(ui.list.querySelector(".unavailable-toggle"), null);
  });

  await t.test("connected with unknown legality", () => {
    const ui = hiddenUnavailableHarness();
    ui.state.legal = null;

    ui.applyLegal();

    assert.deepEqual(ui.rows.map(row => row.hidden), [false, false, false]);
    assert.equal(ui.list.querySelector(".unavailable-toggle"), null);
  });

  await t.test("a hidden action becomes legal while another remains unavailable", () => {
    const ui = hiddenUnavailableHarness();
    ui.rows[0].hidden = true;
    ui.rows[0].classList.toggle("is-illegal", true);
    ui.rows[2].hidden = true;
    ui.rows[2].classList.toggle("is-illegal", true);
    ui.state.legal = new Set(["strike", "guard"]);

    ui.applyLegal();

    assert.deepEqual(ui.rows.map(row => row.hidden), [false, true, false]);
    assert.equal(ui.list.querySelector(".unavailable-toggle").textContent, "Show unavailable (1)");
    assert.equal(ui.rows[1].classList.contains("is-illegal"), true);
  });
});
