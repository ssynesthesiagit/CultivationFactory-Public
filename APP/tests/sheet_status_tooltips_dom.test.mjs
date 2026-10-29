// Runs the actual table message builder and sheet DOM renderer without a live service.
// Python supplies real server presentation rows in the table-boundary regression.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import liveRenderSource from "./sheet_live_render_source.cjs";
import TianxiaSheetViewModel from "../static/sheet_view_model.js";
import {renderTipCard} from "../static/tabletop/rules.js";
import {flightText, heightFeet} from "../static/tabletop/flight-ui.js";

const table = fs.readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");
const sheet = fs.readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");
function section(source, start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `Missing source boundary: ${start}`);
  return source.slice(from, to);
}

class Element {
  constructor(tag) {
    this.tagName = tag; this.attributes = {}; this.children = [];
    this.dataset = {}; this.style = {setProperty() {}}; this.classList = {toggle() {}};
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
  set textContent(value) { this.children = [String(value)]; }
  get textContent() { return this.children.map(child => child instanceof Element ? child.textContent : child).join(""); }
  querySelectorAll(selector) {
    const result = [];
    for (const child of this.children) {
      if (!(child instanceof Element)) continue;
      if (selector.startsWith(".") && child.className?.split(" ").includes(selector.slice(1))) result.push(child);
      result.push(...child.querySelectorAll(selector));
    }
    return result;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
}

const samples = [
  {condition_id: "condition:typed.meld_set", display_name: "Meld: Clearsight",
    detail: "Immune to negative effects of the caster's Darkness talents.\nApplied by Mei, from Meld: Clearsight. While concentrating, up to 1 hour. The table applies the implemented effects."},
  {condition_id: "condition:typed.mark.test.mei", display_name: "Test mark",
    detail: "The next hit gains a bonus < 3 & consumes the mark. Applied by Mei, from Test ability. Until the start of Mei's next turn. The table applies this effect."},
];
const rows = process.env.P6_TOOLTIP_ROWS ? JSON.parse(process.env.P6_TOOLTIP_ROWS) : samples;

function renderer() {
  const defenses = new Element("div");
  const state = {summary: {}, connected: true, actor: null};
  const context = vm.createContext({
    Node: Element,
    document: {createElement: tag => new Element(tag)},
    $: id => id === "defenses" ? defenses : null,
    state, app: {state: null}, conditionInfo: {rows: {}},
    presentation: () => null, conditionTone: () => "buff", isManualActor: () => true,
  });
  vm.runInContext([
    section(table, "const shownCondition =", "// Buffs green"),
    section(table, "const TONE_MEANING =", "function conditionText(row)"),
    section(table, "function conditionText(row)", "// The combat log"),
    section(table, "function actorMessage(actor)", "function broadcastActors()"),
    section(sheet, "function h(tag, attrs, ...kids)", "function icon("),
    section(sheet, "function resourcePools(", "function renderSaves()"),
    section(sheet, "function renderDefenses()", "function renderSkills()"),
  ].join("\n"), context);
  function render(conditions) {
    context.actor = {entity_id: "test-holder", hit_points: {current: 10, maximum: 10}, conditions};
    const message = vm.runInContext("actorMessage(actor)", context);
    // JSON round trip also guards against relying on references across the channel.
    state.actor = JSON.parse(JSON.stringify(message));
    vm.runInContext("renderDefenses()", context);
    const pills = [];
    function visit(node) {
      if (!(node instanceof Element)) return;
      if (node.className?.split(" ").includes("cond")) pills.push(node);
      node.children.forEach(visit);
    }
    visit(defenses);
    return pills;
  }
  return {render};
}

test("sheet condition elements carry the complete server tooltip after table transfer", () => {
  const pills = renderer().render(rows);
  assert.equal(pills.length, rows.length);
  for (const [index, row] of rows.entries()) {
    assert.ok(row.detail, `Server description missing: ${row.display_name}`);
    // The sheet must carry the COMPLETE server tooltip. conditionText appends the plain colour
    // legend after it, so the detail must be the whole prefix, not the whole string.
    assert.ok(pills[index].dataset.tip.startsWith(row.detail),
      `Tooltip does not carry the server description: ${pills[index].dataset.tip}`);
    assert.equal(pills[index].attributes.title, undefined, 'the shared card replaces the native tooltip');
    assert.deepEqual(pills[index].children, [row.display_name]);
    assert.doesNotMatch(pills[index].dataset.tip, /No automatic effect; see its source/);
  }
});

test("sheet replaces expired status elements and refreshes their tooltips", () => {
  const {render} = renderer();
  render(samples);
  const changed = {...samples[0], detail: "Updated lifetime: until removed."};
  assert.ok(render([changed])[0].dataset.tip.startsWith(changed.detail),
    `Refreshed tooltip lost the server description: ${render([changed])[0].dataset.tip}`);
  assert.equal(render([]).length, 0);
});

test("sheet renderStats and renderLive refresh both AC displays and zero walking Speed", () => {
  const roots = new Map(["abilities", "vitals", "defenses", "link-pill", "link-text", "conn-banner", "turn-banner",
    // renderLive() refreshes the header (sheet.js renderHeader) as well as the stats.
    "portrait-text", "char-name", "char-sub", "char-meta"]
    .map(id => [id, new Element("div")]));
  function byId(id) {
    if (roots.has(id)) return roots.get(id);
    function find(node) {
      if (node.attributes.id === id) return node;
      for (const child of node.children) {
        if (child instanceof Element) { const match = find(child); if (match) return match; }
      }
      return null;
    }
    return find(roots.get("vitals"));
  }
  const vitals = roots.get("vitals"), defenses = roots.get("defenses");
  const context = vm.createContext({
    // Bindings sheet.js imports or defines outside the extracted sections (the AC card and its shared card).
    TianxiaSheetViewModel, renderTipCard, flightText, heightFeet,
    // renderLive refreshes the sheet header; the header itself has its own coverage.
    renderHeader: () => {},
    armorTipCard: (breakdown, actor) => (doc, options) => renderTipCard(doc, TianxiaSheetViewModel.armorCard(breakdown, actor), options),
    sheetHoverCard: {isOpen: false, trigger: null}, sheetTipTargets: {show() {}},
    Node: Element, document: {
      createElement: tag => new Element(tag), createElementNS: (_ns, tag) => new Element(tag),
      getElementById: byId,
      querySelector: selector => selector.includes('flight-live') ? vitals.querySelector('.flight-live')
        : vitals.querySelector(".ac").querySelector(".stat-big"),
      querySelectorAll: () => vitals.querySelectorAll(".stat"),
    },
  });
  vm.runInContext(liveRenderSource, context);
  vm.runInContext("renderStats(); renderLive();", context);
  assert.equal(vitals.querySelector(".ac").querySelector(".stat-big").textContent, "12");
  assert.match(defenses.textContent, /Armor Class 12/);
  for (const [ac, speed] of [[14, 5], [17, 0]]) {
    vm.runInContext(`state.actor = {armor_class: ${ac}, speed_ft: ${speed}}; renderLive();`, context);
    assert.equal(vitals.querySelector(".ac").querySelector(".stat-big").textContent, String(ac));
    assert.match(defenses.textContent, new RegExp(`Armor Class ${ac}`));
    assert.doesNotMatch(defenses.textContent, /Armor Class 12/);
    const walking = vitals.querySelectorAll(".stat").find(row => row.querySelector(".stat-label")?.textContent === "Walking");
    assert.equal(walking.querySelector(".stat-big").textContent, `${speed}ft`);
  }
  vm.runInContext("state.actor = {fly_speed_ft: 30, altitude_ft: 10, hover: true}; renderLive();", context);
  const flyLine = byId("walk-fly");
  assert.equal(flyLine.textContent, "Fly 30 ft");
  assert.match(flyLine.dataset.tip, /Fly speed: 30 ft.*hover/);
  assert.equal(byId("height-num").textContent, "10");
  assert.match(byId("height-box").dataset.tip, /Height above the ground: 10 ft/);
  assert.equal(vitals.querySelectorAll(".flight-live").length, 0);
  vm.runInContext("state.actor = {fly_speed_ft: 0, altitude_ft: 0}; renderLive();", context);
  assert.equal(byId("walk-fly").textContent, "");
  assert.equal(byId("height-num").textContent, "0");
});
