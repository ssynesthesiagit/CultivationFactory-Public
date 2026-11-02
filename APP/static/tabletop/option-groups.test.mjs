import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {retainMenuInspection} from "./assisted-menu.js";
import {expandMovementGrid} from "./movement-grid.js";
import {groupOptionRows} from "./option-groups.js";
import {reconcileBar} from "./kept-bar.js";
import {unavailableRowsHidden} from "./sheet-polish.js";

const sheetSource = row => row.combat?.source_definition_id;

test("pickers sit under their ability and keep their menu order", () => {
  const groups = [
    {source_definition_id: "cultivate", label: "Cultivate Blossom"},
    {source_definition_id: "pick.medicinal", label: "Blossom: Medicinal Blossom (1 CP)", parent: "cultivate"},
    {source_definition_id: "dash", label: "Dash"},
    {source_definition_id: "seed.piercing", label: "Seed damage: Piercing", parent: "cultivate"},
  ];
  const rows = groupOptionRows(groups);
  assert.deepEqual(rows.map(row => row.group.label), ["Cultivate Blossom", "Dash"]);
  assert.deepEqual(rows[0].children.map(child => child.label), ["Blossom: Medicinal Blossom (1 CP)", "Seed damage: Piercing"]);
  assert.deepEqual(rows[1].children, []);
});

test("a picker whose ability is not in the menu stays top-level", () => {
  const rows = groupOptionRows([{source_definition_id: "pick.poison", label: "Seed damage: Poison", parent: "gone"}]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].group.label, "Seed damage: Poison");
});

test("a child never attaches to a different row that happens to share its parent's id", () => {
  // Two rows share source id "cultivate" (a stale custom button left over alongside the fresh server row, say).
  // The picker names "cultivate" as its parent: it must not silently resolve to either of the colliding rows.
  const rows = [
    {source_definition_id: "cultivate", label: "Cultivate Blossom (stale)"},
    {source_definition_id: "cultivate", label: "Cultivate Blossom"},
    {source_definition_id: "pick.medicinal", label: "Blossom: Medicinal Blossom (1 CP)", parent: "cultivate"},
  ];
  const grouped = groupOptionRows(rows);
  assert.deepEqual(grouped.map(row => row.group.label),
    ["Cultivate Blossom (stale)", "Cultivate Blossom", "Blossom: Medicinal Blossom (1 CP)"]);
  assert.deepEqual(grouped.every(row => row.children.length === 0), true, "the picker attaches to neither colliding row");
});

test("only one level nests: a chain, a self-parent and a cycle keep every row visible", () => {
  const rows = [
    {source_definition_id: "A", label: "A"},
    {source_definition_id: "B", label: "B", parent: "A"},
    {source_definition_id: "C", label: "C", parent: "B"},
    {source_definition_id: "S", label: "S", parent: "S"},
    {source_definition_id: "X", label: "X", parent: "Y"},
    {source_definition_id: "Y", label: "Y", parent: "X"},
  ];
  const grouped = groupOptionRows(rows);
  assert.deepEqual(grouped.map(row => row.group.label), ["A", "C", "S", "X", "Y"]);
  assert.deepEqual(grouped[0].children.map(child => child.label), ["B"]);
  const drawn = grouped.flatMap(row => [row.group.label, ...row.children.map(child => child.label)]).sort();
  assert.deepEqual(drawn, ["A", "B", "C", "S", "X", "Y"]);
});

test("sheet buttons group by their combat source and their server parent", () => {
  // Sheet buttons are keyed act:<source>; the ability is found by combat.source_definition_id, the picker's parent is a source id.
  const buttons = [
    {id: "act:cultivate", label: "Cultivate Blossom", combat: {source_definition_id: "cultivate"}},
    {id: "act:pick.medicinal", label: "Blossom: Medicinal Blossom (1 CP)", parent: "cultivate", combat: {source_definition_id: "pick.medicinal"}},
    {id: "act:pick.thorned", label: "Blossom: Thorned Bloom (2 CP)", parent: "cultivate", combat: {source_definition_id: "pick.thorned"}},
    {id: "act:dash", label: "Dash", combat: {source_definition_id: "dash"}},
  ];
  const rows = groupOptionRows(buttons, sheetSource, row => row.parent);
  assert.deepEqual(rows.map(row => row.group.label), ["Cultivate Blossom", "Dash"]);
  assert.deepEqual(rows[0].children.map(child => child.label), ["Blossom: Medicinal Blossom (1 CP)", "Blossom: Thorned Bloom (2 CP)"]);
});

test("each picker is drawn once: a child whose ability is drawn is not also a top-level row", () => {
  const buttons = [
    {id: "act:cultivate", label: "Cultivate Blossom", group: "actions", combat: {source_definition_id: "cultivate"}},
    {id: "act:pick.medicinal", label: "Blossom: Medicinal Blossom (1 CP)", group: "actions", tags: ["choice"], parent: "cultivate",
      combat: {source_definition_id: "pick.medicinal"}},
    {id: "act:pick.poison", label: "Seed damage: Poison", group: "actions", tags: ["choice"], parent: "gone",
      combat: {source_definition_id: "pick.poison"}},
  ];
  const rows = groupOptionRows(buttons, sheetSource, row => row.parent);
  const drawn = rows.flatMap(row => [row.group.id, ...row.children.map(child => child.id)]);
  assert.deepEqual(drawn.sort(), ["act:cultivate", "act:pick.medicinal", "act:pick.poison"]);
});

// Minimal DOM with the tree, class and text the real renderers read back.
function makeDocument() {
  const registry = new Map();
  class El {
    constructor(tag) { this.tagName = tag; this.children = []; this.parentNode = null; this.className = ""; this.textContent = ""; this.innerHTMLValue = ""; this.dataset = {}; this.style = {}; this.attributes = {}; this.hidden = false; }
    setAttribute(name, value) {
      this.attributes[name] = String(value);
      if (name === "id") registry.set(String(value), this);
    }
    hasAttribute(name) { return name in this.attributes; }
    addEventListener() {}
    remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((c) => c !== this); }
    prepend(node) { if (node instanceof El) { node.parentNode = this; this.children.unshift(node); } }
    get nextElementSibling() {
      if (!this.parentNode) return null;
      const siblings = this.parentNode.children.filter((c) => c instanceof El);
      const at = siblings.indexOf(this);
      return at === -1 ? null : (siblings[at + 1] ?? null);
    }
    get classList() { return {add: (...c) => { this.className = [this.className, ...c].filter(Boolean).join(" "); }, remove() {}, toggle() {}, contains: c => this.className.split(" ").includes(c)}; }
    set innerHTML(markup) {
      this.children = [];
      const tags = [...String(markup).matchAll(/<(\w+)(?:\s+class="([^"]*)")?>/g)];
      for (const [, tag, cls] of tags) { const el = new El(tag); el.className = cls || ""; el.parentNode = this; this.children.push(el); }
    }
    get innerHTML() { return this.innerHTMLValue; }
    get lastChild() { return this.children[this.children.length - 1] ?? null; }
    appendChild(node) {
      if (node instanceof El) { node.parentNode = this; this.children.push(node); } else if (node != null && node !== false) this.children.push(String(node));
      return node;
    }
    querySelectorAll(selector) {
      // Each compound term is a class (".x"), an attribute presence check ("[x]") or a tag name; every term must match.
      const terms = selector.match(/\.[\w-]+|\[[\w-]+\]|^[a-zA-Z][\w-]*/g) || [];
      const matches = el => terms.every((term) => term.startsWith(".") ? el.className.split(" ").includes(term.slice(1))
        : term.startsWith("[") ? el.hasAttribute(term.slice(1, -1)) : el.tagName === term);
      const out = [];
      const walk = node => { for (const child of node.children) if (child instanceof El) { if (matches(child)) out.push(child); walk(child); } };
      walk(this);
      return out;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
  }
  return {createElement: tag => new El(tag), El, getElementById: id => registry.get(id) ?? null};
}

function extractFunction(source, header, endMarker) {
  const from = source.indexOf(header);
  assert.notEqual(from, -1, `${header} must exist`);
  return source.slice(from, source.indexOf(endMarker, from));
}

test("the sheet Actions list draws each picker once, indented under its ability", () => {
  const source = readFileSync(new URL("./sheet.js", import.meta.url), "utf8");
  const {El} = makeDocument();
  const h = (tag, attrs, ...kids) => {
    const el = new El(tag);
    el.className = attrs?.class || "";
    for (const kid of kids.flat()) el.appendChild(kid);
    return el;
  };
  const actionRow = button => { const row = h("div", {class: "arow"}); row.textContent = button.label; return row; };
  const actionGroupSection = new Function("h", "groupOptionRows", "actionRow", "reactionRows", "reactionsNote", "norm",
    `${extractFunction(source, "function actionGroupSection(g, items)", "\nfunction renderActions()")}\nreturn actionGroupSection;`)(
    h, groupOptionRows, actionRow, () => [], () => "", value => String(value).toLowerCase());
  const items = [
    {id: "act:cultivate", label: "Cultivate Blossom", combat: {source_definition_id: "cultivate"}},
    {id: "act:pick.medicinal", label: "Blossom: Medicinal Blossom (1 CP)", parent: "cultivate", combat: {source_definition_id: "pick.medicinal"}},
    {id: "act:pick.thorned", label: "Blossom: Thorned Bloom (2 CP)", parent: "cultivate", combat: {source_definition_id: "pick.thorned"}},
    {id: "act:dash", label: "Dash", combat: {source_definition_id: "dash"}},
  ];
  const section = actionGroupSection({key: "attacks", title: "Attacks"}, items);
  const rows = section.querySelectorAll(".arow");
  for (const label of ["Cultivate Blossom", "Blossom: Medicinal Blossom (1 CP)", "Blossom: Thorned Bloom (2 CP)", "Dash"]) {
    assert.equal(rows.filter(row => row.textContent === label).length, 1, `${label} is drawn once`);
  }
  const indented = section.querySelectorAll(".arow-child").map(wrapper => wrapper.children[0].textContent);
  assert.deepEqual(indented, ["Blossom: Medicinal Blossom (1 CP)", "Blossom: Thorned Bloom (2 CP)"]);
  assert.equal(rows.find(row => row.textContent === "Dash").parentNode.className.includes("arow-child"), false, "an unrelated ability is not indented");
});

test("the table action bar draws no picker: pickers live in the ability's Options panel, as Darkness's talents do", () => {
  const source = readFileSync(new URL("./tabletop.js", import.meta.url), "utf8");
  const slice = (from, to) => {
    const start = source.indexOf(from);
    assert.notEqual(start, -1, `${from} must exist`);
    const end = source.indexOf(to, start);
    assert.notEqual(end, -1, `${to} must follow it`);
    return source.slice(start, end);
  };
  // The real code from renderActionBar: makeButton, the sheetButtons filter, inSection, drawButton, the section loop and
  // the Other list (tabletop.js makeButton..extra). Free helpers are stubbed. The Move group is skipped: it needs
  // layout the stub lacks and nothing in the picker code reads it.
  const pickerSrc = `${slice("  const sections = [", "  const html = document")}${slice("  const makeButton = (label", "  const moveGroup")}${slice("  const optionRows = draftOptionRows", "  // An ability's choices")}`;
  const drawTable = new Function("env", `
    const {document, sheet, menu, actor, app, groups, used, hidden, rulesTextFor, buttonDetail, actionHoverText, reasonFor, actionTipCard, actionRules, actionSummary, additionalRuleText, markActive, runButton} = env;
    const draftOptionRows = () => [];
    const html = document.createElement("div");
    html.className = "tt-ab-groups";
    ${pickerSrc}
    return {html};
  `);

  const {createElement} = makeDocument();
  const document = {createElement};
  const combat = source => ({source_definition_id: source});
  const sheetButtons = [
    {id: "act:cultivate", label: "Cultivate Blossom", kind: "combat", group: "actions", combat: combat("cultivate")},
    {id: "act:pick.medicinal", label: "Blossom: Medicinal Blossom (1 CP)", kind: "combat", group: "actions", tags: ["choice"], parent: "cultivate", combat: combat("pick.medicinal")},
    {id: "act:pick.thorned", label: "Blossom: Thorned Bloom (2 CP)", kind: "combat", group: "actions", tags: ["choice"], parent: "cultivate", combat: combat("pick.thorned")},
    {id: "act:dash", label: "Dash", kind: "combat", group: "actions", combat: combat("dash")},
  ];
  const menu = {actor_id: "blossom-1", actions: ["cultivate", "pick.medicinal", "pick.thorned", "dash"].map(source => ({source_definition_id: source, label: source}))};
  const {html} = drawTable({
    document, sheet: {buttons: sheetButtons, layout: {hidden: []}}, menu, actor: {display_name: "Blossom"},
    app: {state: {}}, groups: new Map(menu.actions.map(group => [group.source_definition_id, group])), used: new Set(), hidden: new Set(),
    rulesTextFor: () => "", buttonDetail: () => "", actionHoverText: () => "", reasonFor: () => "", actionTipCard: () => null,
    actionRules: () => document.createElement("div"), actionSummary: () => "", additionalRuleText: () => "", markActive: () => {}, runButton: () => {},
  });
  const labelOf = card => card.children[0]?.children[0]?.textContent ?? "";
  const pickerLabels = ["Blossom: Medicinal Blossom (1 CP)", "Blossom: Thorned Bloom (2 CP)"];
  const everyLabel = html.querySelectorAll(".tt-action-card").map(labelOf);
  assert.deepEqual(everyLabel, ["Cultivate Blossom", "Dash"], "only the ability and its unrelated neighbour are bar buttons");
  assert.equal(html.querySelectorAll(".tt-option-children").length, 0, "no nested column in the bar");
  for (const label of pickerLabels) {
    assert.equal(everyLabel.includes(label), false, `${label} is not a bar button`);
  }
});

test("the sheet keeps a picker top-level when its ability is not in the list", () => {
  const source = readFileSync(new URL("./sheet.js", import.meta.url), "utf8");
  const {El} = makeDocument();
  const h = (tag, attrs, ...kids) => { const el = new El(tag); el.className = attrs?.class || ""; for (const kid of kids.flat()) el.appendChild(kid); return el; };
  const actionRow = button => { const row = h("div", {class: "arow"}); row.textContent = button.label; return row; };
  const actionGroupSection = new Function("h", "groupOptionRows", "actionRow", "reactionRows", "reactionsNote", "norm",
    `${extractFunction(source, "function actionGroupSection(g, items)", "\nfunction renderActions()")}\nreturn actionGroupSection;`)(
    h, groupOptionRows, actionRow, () => [], () => "", value => String(value).toLowerCase());
  const section = actionGroupSection({key: "attacks", title: "Attacks"},
    [{id: "act:pick.poison", label: "Seed damage: Poison", parent: "gone", combat: {source_definition_id: "pick.poison"}}]);
  assert.equal(section.querySelectorAll(".arow-child").length, 0);
  assert.equal(section.querySelectorAll(".arow").filter(row => row.textContent === "Seed damage: Poison").length, 1);
});

test("the sheet restores a hidden ability's row when its picker is still shown (owner 2026-10-13)", () => {
  const source = readFileSync(new URL("./sheet.js", import.meta.url), "utf8");
  const groupButtons = new Function("state", `${extractFunction(source, "function groupButtons(key)", "\nfunction renderFilters")}\nreturn groupButtons;`)({
    buttons: [
      {id: "act:cultivate", group: "actions", label: "Cultivate Blossom", combat: {source_definition_id: "cultivate"}},
      {id: "act:pick.medicinal", group: "actions", label: "Blossom: Medicinal Blossom (1 CP)", parent: "cultivate", combat: {source_definition_id: "pick.medicinal"}},
      {id: "act:dash", group: "actions", label: "Dash", combat: {source_definition_id: "dash"}},
    ],
    // The owner's old layout hid "Cultivate Blossom" itself (from before its picker moved under it); the picker was never hidden.
    hidden: new Set(["act:cultivate"]),
  });
  const ids = groupButtons("actions").map(row => row.id);
  assert.deepEqual(ids.sort(), ["act:cultivate", "act:dash", "act:pick.medicinal"], "the hidden ability is restored because its picker still needs it");
});

test("the sheet keeps a whole hidden family hidden: parent and child both hidden (review r1, finding 1)", () => {
  const source = readFileSync(new URL("./sheet.js", import.meta.url), "utf8");
  const groupButtons = new Function("state", `${extractFunction(source, "function groupButtons(key)", "\nfunction renderFilters")}\nreturn groupButtons;`)({
    buttons: [
      {id: "act:cultivate", group: "actions", label: "Cultivate Blossom", combat: {source_definition_id: "cultivate"}},
      {id: "act:pick.medicinal", group: "actions", label: "Blossom: Medicinal Blossom (1 CP)", parent: "cultivate", combat: {source_definition_id: "pick.medicinal"}},
      {id: "act:dash", group: "actions", label: "Dash", combat: {source_definition_id: "dash"}},
    ],
    // The owner hid the whole family: the ability and its one picker. Neither should come back.
    hidden: new Set(["act:cultivate", "act:pick.medicinal"]),
  });
  assert.deepEqual(groupButtons("actions").map(row => row.id), ["act:dash"],
    "a hidden child names no requirement, so the family stays fully hidden");
});

test("the sheet does not restore a hidden ability for an unrelated hidden row", () => {
  const source = readFileSync(new URL("./sheet.js", import.meta.url), "utf8");
  const groupButtons = new Function("state", `${extractFunction(source, "function groupButtons(key)", "\nfunction renderFilters")}\nreturn groupButtons;`)({
    buttons: [
      {id: "act:cultivate", group: "actions", label: "Cultivate Blossom", combat: {source_definition_id: "cultivate"}},
      {id: "act:pick.medicinal", group: "actions", label: "Blossom: Medicinal Blossom (1 CP)", parent: "cultivate", combat: {source_definition_id: "pick.medicinal"}},
      {id: "act:dash", group: "actions", label: "Dash", combat: {source_definition_id: "dash"}},
    ],
    // Hiding an unrelated ability must not resurrect "Cultivate Blossom", which was never hidden.
    hidden: new Set(["act:dash"]),
  });
  assert.deepEqual(groupButtons("actions").map(row => row.id).sort(), ["act:cultivate", "act:pick.medicinal"]);
});

test("the sheet still hides an ability with no children", () => {
  const source = readFileSync(new URL("./sheet.js", import.meta.url), "utf8");
  const groupButtons = new Function("state", `${extractFunction(source, "function groupButtons(key)", "\nfunction renderFilters")}\nreturn groupButtons;`)({
    buttons: [
      {id: "act:dash", group: "actions", label: "Dash", combat: {source_definition_id: "dash"}},
      {id: "act:hide", group: "actions", label: "Hide", combat: {source_definition_id: "hide"}},
    ],
    hidden: new Set(["act:hide"]),
  });
  assert.deepEqual(groupButtons("actions").map(row => row.id), ["act:dash"]);
});

test("the table action bar restores a hidden ability's cast button when it has a picker (owner 2026-10-13)", () => {
  const source = readFileSync(new URL("./tabletop.js", import.meta.url), "utf8");
  const slice = (from, to) => {
    const start = source.indexOf(from);
    assert.notEqual(start, -1, `${from} must exist`);
    const end = source.indexOf(to, start);
    assert.notEqual(end, -1, `${to} must follow it`);
    return source.slice(start, end);
  };
  const filterSrc = slice("  const hidden = new Set(sheet?.layout?.hidden", "  const sections = [")
    + slice("  const neededAsParent = new Set((sheet?.buttons", "  const inSection =");
  const buildSheetButtons = new Function("sheet", `const menu = {actor_id: "hero"}; const draftOptionRows = () => [];\n${filterSrc}\nreturn sheetButtons;`);
  const sheetButtons = [
    {id: "act:cultivate", label: "Cultivate Blossom", kind: "combat", group: "actions", combat: {source_definition_id: "cultivate"}},
    {id: "act:pick.medicinal", label: "Blossom: Medicinal Blossom (1 CP)", kind: "combat", group: "actions", parent: "cultivate", combat: {source_definition_id: "pick.medicinal"}},
    {id: "act:dash", label: "Dash", kind: "combat", group: "actions", combat: {source_definition_id: "dash"}},
  ];
  const built = buildSheetButtons({buttons: sheetButtons, layout: {hidden: ["act:cultivate"]}});
  assert.deepEqual(built.map(row => row.id).sort(), ["act:cultivate", "act:dash"],
    "Cultivate Blossom casts from the bar again because its picker still needs it; the picker itself stays off the bar");
});

test("the bar keeps a whole hidden family off: parent and child both hidden (review r1, finding 1)", () => {
  const source = readFileSync(new URL("./tabletop.js", import.meta.url), "utf8");
  const slice = (from, to) => {
    const start = source.indexOf(from);
    assert.notEqual(start, -1, `${from} must exist`);
    const end = source.indexOf(to, start);
    assert.notEqual(end, -1, `${to} must follow it`);
    return source.slice(start, end);
  };
  const filterSrc = slice("  const hidden = new Set(sheet?.layout?.hidden", "  const sections = [")
    + slice("  const neededAsParent = new Set((sheet?.buttons", "  const inSection =");
  const buildSheetButtons = new Function("sheet", `const menu = {actor_id: "hero"}; const draftOptionRows = () => [];\n${filterSrc}\nreturn sheetButtons;`);
  const sheetButtons = [
    {id: "act:cultivate", label: "Cultivate Blossom", kind: "combat", group: "actions", combat: {source_definition_id: "cultivate"}},
    {id: "act:pick.medicinal", label: "Blossom: Medicinal Blossom (1 CP)", kind: "combat", group: "actions", parent: "cultivate", combat: {source_definition_id: "pick.medicinal"}},
    {id: "act:dash", label: "Dash", kind: "combat", group: "actions", combat: {source_definition_id: "dash"}},
  ];
  // The owner hid the whole family from the bar: the ability and its one picker.
  const built = buildSheetButtons({buttons: sheetButtons, layout: {hidden: ["act:cultivate", "act:pick.medicinal"]}});
  assert.deepEqual(built.map(row => row.id), ["act:dash"], "a hidden child names no requirement, so the family stays off the bar");
});

test("the bar does not restore a hidden ability for an unrelated hidden row", () => {
  const source = readFileSync(new URL("./tabletop.js", import.meta.url), "utf8");
  const slice = (from, to) => {
    const start = source.indexOf(from);
    assert.notEqual(start, -1, `${from} must exist`);
    const end = source.indexOf(to, start);
    assert.notEqual(end, -1, `${to} must follow it`);
    return source.slice(start, end);
  };
  const filterSrc = slice("  const hidden = new Set(sheet?.layout?.hidden", "  const sections = [")
    + slice("  const neededAsParent = new Set((sheet?.buttons", "  const inSection =");
  const buildSheetButtons = new Function("sheet", `const menu = {actor_id: "hero"}; const draftOptionRows = () => [];\n${filterSrc}\nreturn sheetButtons;`);
  const sheetButtons = [
    {id: "act:cultivate", label: "Cultivate Blossom", kind: "combat", group: "actions", combat: {source_definition_id: "cultivate"}},
    {id: "act:pick.medicinal", label: "Blossom: Medicinal Blossom (1 CP)", kind: "combat", group: "actions", parent: "cultivate", combat: {source_definition_id: "pick.medicinal"}},
    {id: "act:dash", label: "Dash", kind: "combat", group: "actions", combat: {source_definition_id: "dash"}},
  ];
  const built = buildSheetButtons({buttons: sheetButtons, layout: {hidden: ["act:dash"]}});
  assert.deepEqual(built.map(row => row.id).sort(), ["act:cultivate"], "Dash is hidden on the bar; Cultivate Blossom was never hidden and needs no restoring");
});

test("updateUnavailableRows keeps an illegal parent visible for an available child, hides an unrelated illegal row, and the toggle still reveals it (review r1, finding 2)", () => {
  const sheetSource = readFileSync(new URL("./sheet.js", import.meta.url), "utf8");
  const {El, createElement, getElementById} = makeDocument();
  const h = (tag, attrs, ...kids) => {
    const el = new El(tag);
    for (const [name, value] of Object.entries(attrs || {})) {
      if (name === "class") el.className = value || "";
      else if (value != null && value !== false) el.setAttribute(name, value);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.appendChild(kid);
    return el;
  };
  // A stub actionRow that still produces the real shape updateUnavailableRows reads: a button carrying
  // data-button-id, starting illegal exactly where applyLegal would have left it.
  const actionRow = (button) => {
    const row = h("button", {class: `arow${button.illegal ? " is-illegal" : ""}`});
    row.setAttribute("data-button-id", button.id);
    row.textContent = button.label;
    return row;
  };
  const actionGroupSection = new Function("h", "groupOptionRows", "actionRow", "reactionRows", "reactionsNote", "norm",
    `${extractFunction(sheetSource, "function actionGroupSection(g, items)", "\nfunction renderActions()")}\nreturn actionGroupSection;`)(
    h, groupOptionRows, actionRow, () => [], () => "", value => String(value).toLowerCase());
  const items = [
    // Cultivate Blossom is illegal this turn (its Action is spent), but its picker stays available.
    {id: "act:cultivate", label: "Cultivate Blossom", illegal: true, combat: {source_definition_id: "cultivate"}},
    {id: "act:pick.medicinal", label: "Blossom: Medicinal Blossom (1 CP)", parent: "cultivate", combat: {source_definition_id: "pick.medicinal"}},
    // Dash is illegal and has no children: an ordinary unavailable row, unaffected by the header exemption.
    {id: "act:dash", label: "Dash", illegal: true, combat: {source_definition_id: "dash"}},
  ];
  const section = actionGroupSection({key: "actions", title: "Actions"}, items);
  const actionList = createElement("div");
  actionList.setAttribute("id", "action-list");
  actionList.appendChild(section);
  const $ = (id) => getElementById(id);
  const state = {connected: true, showUnavailable: false};
  const updateUnavailableRows = new Function("$", "h", "state", "unavailableRowsHidden",
    `${extractFunction(sheetSource, "function updateUnavailableRows()", "\nfunction economyPips")}\nreturn updateUnavailableRows;`)(
    $, h, state, unavailableRowsHidden);
  updateUnavailableRows();
  const byLabel = (label) => actionList.querySelectorAll("[data-button-id]").find((row) => row.textContent === label);
  assert.equal(byLabel("Cultivate Blossom").hidden, false, "the illegal parent stays visible because its picker still needs it");
  assert.equal(byLabel("Blossom: Medicinal Blossom (1 CP)").hidden, false, "the available child is never hidden");
  assert.equal(byLabel("Dash").hidden, true, "an unrelated illegal row with no children still hides");
  state.showUnavailable = true;
  updateUnavailableRows();
  assert.equal(byLabel("Dash").hidden, false, "the unavailable-rows toggle still reveals a hidden row");
  assert.equal(byLabel("Cultivate Blossom").hidden, false, "the parent header was never hidden, so toggling leaves it visible");
});

// BARSCROLL1: an unchanged poll must not rebuild the action bar, and a real rebuild must keep the groups scroller.
// render() kept the received menu by reference. Opening a lazy group writes into that same row (useGroup,
// expandSource, retainMenuInspection), so the next identical poll no longer matched, the bar rebuilt, and the
// scroller snapped back to the start. These run the real render, renderObservedState and keepActionBar from tabletop.js.
const barScrollSource = readFileSync(new URL("./tabletop.js", import.meta.url), "utf8");
function barScrollFunction(name) {
  const start = barScrollSource.search(new RegExp(`(?:async )?function ${name}\\(`));
  assert.notEqual(start, -1, `${name} must exist in tabletop.js`);
  return barScrollSource.slice(start, barScrollSource.indexOf("\n}", start) + 2);
}
function barScrollPoll(sequence) {
  return {
    last_sequence: sequence,
    presentation: {match_id: "m1", display_name: "Fight", current_actor_id: "hero", round_number: 1, zones: [],
      actors: [{entity_id: "hero", display_name: "Hero", active: true, team: 0, position: {x: 1, y: 1, z: 0}}]},
    menu: {manual: true, actor_id: "hero", decision_id: "d1", state_version: 3, control_mode: "manual", turn_mode: "manual",
      actions: [{source_definition_id: "door", label: "Open Door", lazy: true},
        {source_definition_id: "dash", label: "Dash", lazy: false, options: [{id: "dash"}]}],
      moves: []},
  };
}
function barScrollHarness(app) {
  const counts = {actionBar: 0};
  const classList = {contains: () => false, add() {}, remove() {}, toggle() {}};
  const ctx = vm.createContext({
    app, retainMenuInspection, expandMovementGrid, JSON, Object, Array, String, Boolean, Map, Set, Uint8Array,
    $: () => ({textContent: "", innerHTML: "", classList, querySelector: () => null}),
    requestAnimationFrame() {},
    board: {setRoofView() {}, setMap() {}, fit() {}, setRemembered() {}},
    modelOwner: () => false, isManualActor: () => true, isGMView: () => false, teamIndex: () => 0, serverDriving: () => false,
    actorById: id => (app.state?.presentation?.actors || []).find(actor => actor.entity_id === id) || null,
    mapFromState: () => ({width: 2, height: 2, walls: [], objects: [], trees: [], decor: [], background: {url: ""},
      cells: {blocked: [0, 0, 0, 0], sight: [0, 0, 0, 0]}, centerlineCells: [], floors: []}),
    wallSightCells: () => [], opacityGrid: () => [], rememberFog: () => [],
    reconcileViewerIdentity: () => false, reconcileOptionDraft() {}, broadcastDraftStates() {}, invalidateTargeting() {},
    renderCommitNotice() {}, renderZones() {}, renderTokens() {}, renderInitiative() {}, renderRoster() {}, renderInspector() {},
    renderItemsPanel() {}, renderShapePanel() {}, scheduleAutoPlay() {}, renderHighlights() {}, broadcastActors() {},
    renderPip() {}, scheduleSeatPoll() {}, requestDeferredMenu() {}, keepActionBar() {},
    renderActionBar() { counts.actionBar++; },
  });
  vm.runInContext([barScrollFunction("render"), barScrollFunction("renderObservedState")].join("\n"), ctx);
  return {ctx, counts};
}

test("an unchanged poll does not rebuild the action bar after a lazy group was opened", () => {
  const app = {matchId: "m1", state: null, menu: null, receivedState: null, selected: new Set(), fog: "all",
    movePositions: new Map(), lastSequence: 0, seatStatus: null};
  const {ctx, counts} = barScrollHarness(app);
  ctx.render(barScrollPoll(5));
  assert.equal(counts.actionBar, 1, "the first render draws the bar once");
  // The player opens Open Door: useGroup writes the expanded group into the live row in place.
  Object.assign(app.menu.actions[0], {lazy: false, expanded_from_lazy: true, options: [{id: "door.open"}]});
  counts.actionBar = 0;
  ctx.renderObservedState(barScrollPoll(5));
  ctx.renderObservedState(barScrollPoll(5));
  assert.equal(counts.actionBar, 0, "an unchanged poll must not rebuild the bar (the groups scroller would snap back)");
  ctx.renderObservedState(barScrollPoll(6));
  assert.equal(counts.actionBar, 1, "a real change still redraws the bar");
  assert.equal(app.menu.actions[0].options.length, 1, "the opened group stays open across a real change");
});

test("a free choice that redraws the bar keeps the groups scroller where the player left it", () => {
  const element = className => ({className, scrollTop: 0, scrollLeft: 0, childNodes: [],
    querySelector(selector) { return selector === ".tt-ab-groups" ? this.childNodes.find(node => node.className === "tt-ab-groups") || null : null; },
    querySelectorAll(selector) {
      assert.notEqual(selector, "button", "different signatures must not take the copySelection path");
      return [];
    },
    cloneNode() { return {querySelectorAll: () => [], innerHTML: this.childNodes.map(node => node.className + node.childNodes.map(child => child.className).join()).join()}; },
    replaceChildren(...nodes) { this.childNodes = nodes; }});
  const live = element("tt-actionbar");
  const oldGroups = element("tt-ab-groups");
  oldGroups.scrollLeft = 240;
  live.childNodes = [oldGroups];
  const ctx = vm.createContext({
    $: () => live,
    document: {createElement: () => element("")},
    renderActionBar: async probe => { const groups = element("tt-ab-groups"); groups.childNodes = [element("new-control")]; probe.childNodes = [groups]; },
    reconcileBar,
  });
  vm.runInContext(barScrollFunction("keepActionBar"), ctx);
  return ctx.keepActionBar().then(() => {
    const groups = live.childNodes.find(node => node.className === "tt-ab-groups");
    assert.notEqual(groups, oldGroups, "the redraw replaced the scroller");
    assert.equal(groups.scrollLeft, 240, "the scroll position survives the rebuild");
  });
});

test("a bar that waits for its menu keeps the player's place in the groups scroller", async () => {
  const groupsOf = bar => bar.childNodes.find(node => node.className === "tt-ab-groups") || null;
  const bar = {className: "tt-actionbar", childNodes: [], groupsScroll: undefined, html: "",
    querySelector(selector) { return selector === ".tt-ab-groups" ? groupsOf(this) : {textContent: ""}; },
    replaceChildren(...nodes) { this.childNodes = nodes; },
    set innerHTML(value) { this.html = value; }, get innerHTML() { return this.html; }};
  bar.childNodes = [{className: "tt-ab-groups", scrollLeft: 240}];
  const env = {$: () => bar, app: {menu: null, state: {menu_pending: true}},
    presentation: () => ({current_actor_id: "hero"}), currentViewer: () => ({ready: true}),
    actorById: () => ({display_name: "Hero"}), modelOwner: () => null, serverDriving: () => false,
    isManualActor: () => true, automaticSlot: () => false};
  // The waiting bar drops its scroller for the loading line; the place stays on the bar for the menu that returns.
  const run = new Function(...Object.keys(env), "let menuLoadingTimer = null; let menuLoadingActor = 'hero'; "
    + barScrollFunction("renderActionBar") + "\nreturn renderActionBar;")(...Object.values(env));
  await run();
  assert.match(bar.innerHTML, /Loading your choices/);
  assert.equal(groupsOf(bar), null, "the waiting bar has no scroller");
  assert.equal(bar.groupsScroll, 240, "the player's place is remembered while the bar waits");
});
