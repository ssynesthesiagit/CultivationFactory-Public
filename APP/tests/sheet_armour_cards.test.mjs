// Focused renderer gate for the sheet's Armor Class and Speed cards (MMX73f1).
// Run: node --test APP/tests/sheet_armour_cards.test.mjs
//
// Executes the REAL APP/static/app.js under the repo's permissive in-process DOM stub and renders
// both player-facing paths that show these numbers: the owner sheet's overview cards
// (ownerOverviewContent) and the GM build panel's Defenses card (gmBuildCombatPanel). No browser.
//
// The MMX73 pre-merge review found that the lane's tests never read either card, so reverting the
// renderer left the suite green while the player read the wrong Armor Class. These tests read the
// rendered text of the actual cards.
import test, {after} from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const APP = path.resolve(here, "..");
const {documentStub} = await import("./gm_sheet_dom_stub/domstub.js");

function readStatic(name) {
  return fs.readFileSync(path.join(APP, "static", name), "utf8");
}

const intervals = new Set();
after(() => { for (const timer of intervals) clearInterval(timer); });
const sandbox = {
  console,
  setTimeout,
  clearTimeout,
  setInterval(fn, delay) {
    const timer = setInterval(fn, delay);
    intervals.add(timer);
    return timer;
  },
  clearInterval(timer) { clearInterval(timer); intervals.delete(timer); },
  AbortController,
  Image: class { constructor() { this.src = ""; } },
  __TIANXIA_LIBRARY_ENRICHMENT_TIMEOUT_MS__: 5000,
  fetch: async () => { throw new Error("network disabled in renderer gate"); },
  Option: class {
    constructor(text = "", value = "") { this.textContent = text; this.value = value; this.selected = false; this.disabled = false; }
  },
  location: {assign() {}, reload() {}},
  navigator: {userAgent: "renderer-gate"},
  document: documentStub,
  localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.addEventListener = () => {};
sandbox.removeEventListener = () => {};
vm.createContext(sandbox);
for (const file of ["sphere_talent_logic.js", "sheet_view_model.js", "complete_request_save.js", "character_search.js"]) {
  vm.runInContext(readStatic(file), sandbox, {filename: file});
}
// The permissive stub does not parse HTML select options; seed the one option
// read by the existing manual-lineage initializer before loading app.js.
documentStub.getElementById("guidedManualLineageTrainingTypes").options = [{selected: false}];
vm.runInContext(readStatic("app.js"), sandbox, {filename: "app.js"});

// ------------------------------------------------------------------ rendered-text helpers

// FakeElement keeps textContent per node, so the readable text of a card is its own text plus the
// text of every descendant -- the same walk gm_sheet_renderer_dom.test.mjs uses.
function deepText(el) {
  if (!el) return "";
  let out = el.textContent ? String(el.textContent) : "";
  for (const child of el.children || []) out += ` ${deepText(child)}`;
  return out.replace(/\s+/g, " ").trim();
}

test("SOL191 real Scratch sheet AC tile exposes its base terms and separate conditional bonus", () => {
  const fixture = JSON.parse(fs.readFileSync(path.join(here, "fixtures/gm_sheet/scratch_owner_sheet_snapshot.fixture.json"), "utf8"));
  const host = documentStub.createElement("div");
  sandbox.acSheet = {project_id: "ac-regression", owner_character_sheet: fixture};
  sandbox.acHost = host;
  vm.runInContext("renderOwnerSheet(acSheet, acHost)", sandbox);
  const nodes = [];
  const visit = node => { nodes.push(node); for (const child of node.children || []) visit(child); };
  visit(host);
  const tile = nodes.find(node => node.dataset?.tip?.includes("Armor Class (AC)"));
  assert.ok(tile, "the actual owner rail must carry the breakdown, not just a formatter unit test");
  assert.match(tile.dataset.tip, /10 base \+ 2 Dexterity modifier = 12/);
  assert.match(tile.dataset.tip, /while unarmored/);
  assert.match(tile.dataset.tip, /Conditional bonuses[\s\S]*Qi Armor[\s\S]*\+3/);
  assert.equal(tile.title || "", "");
  assert.equal(tile.getAttribute("role"), "button");
  assert.equal(tile.getAttribute("data-tip-click"), "");
});

test("SOL191 current AC includes named temporary effects without assuming cover is standing AC", () => {
  const record = {value: 14, combat_terms: [{source: "unarmored calculation", value: 12}, {source: "shield", value: 2}]};
  const text = sandbox.TianxiaSheetViewModel.armorBreakdown(record,
    {armor_class: 21, armor_base: 14, armor_modifiers: [{source: "Shield spell", value: 5}]});
  assert.match(text, /12 unarmored calculation \+ 2 shield = 14/);
  assert.match(text, /Current AC in this fight: 21/);
  assert.match(text, /Shield spell: \+5 AC/);
  assert.match(text, /Other active defenses: \+2/);
  assert.match(text, /Cover.*when that attack resolves/);
  assert.doesNotMatch(text, /undefined|NaN/);
});

// The text of the card carrying this heading, or "" when the view has no such card.
// Walked directly rather than through querySelectorAll: the shared stub matches class and data
// selectors but not a bare tag name, and the cards are identified by their own heading.
function cardText(root, title) {
  const stack = [root];
  while (stack.length) {
    const node = stack.shift();
    for (const child of node.children || []) {
      if (child.tagName === "ARTICLE") {
        const heading = (child.children || []).find(part => part.tagName === "H5");
        if (heading && deepText(heading) === title) return deepText(child);
      }
      stack.push(child);
    }
  }
  return "";
}

// The statistics block exactly as CharacterSheetService._publish_worn_armour writes it.
function stats({ac, speed}) {
  return {
    armor_class: ac,
    hit_points: {maximum: 20, current: 20},
    speed,
    abilities: [],
    primary_resource: {name: "Stamina", current: 10, maximum: 10},
  };
}

// The MMX73 case: Imperial Plate (AC 18) + Shield (+2) against a Strength 10, on a character whose
// unarmored calculation is 17 with a standing +1 folded in, so base_value(17) and value(18) differ.
const WORN = {
  ac: {
    base_value: 17,
    value: 18,
    effective_value: 20,
    unarmored_value: 18,
    worn: true,
    worn_armor: "Imperial Plate Battle Dress",
    worn_note: "Wearing Imperial Plate Battle Dress (Armor Class 18) and a Shield (+2) gives an Armor Class of 20.",
  },
  speed: {
    walking_ft: 30,
    effective_walking_ft: 20,
    worn_note: "Imperial Plate Battle Dress needs Strength 15 to wear and this character has 10, so it costs 10 ft of walking Speed: 20 ft instead of 30 ft.",
  },
};

// A sheet written before the lane: no effective or unarmored value, no penalized Speed.
const LEGACY = {
  ac: {base_value: 17, value: 18},
  speed: {walking_ft: 30},
};

function ownerCards(block) {
  return sandbox.ownerOverviewContent({
    identity: {proficiency_bonus: 2},
    // The rest of the overview surface is not under test here; it must be present so the renderer
    // reaches the cards above it. These two are the only fields the summary strip reads.
    snapshot: {explicit_none_systems: [], equipment: []},
    surfaceData: () => null,
    stats: stats(block),
  });
}

function gmDefenses(block) {
  const panel = sandbox.gmBuildCombatPanel(
    {abilityChips: [], actionsIndex: []},
    {owner_character_sheet: {ability_scores_and_statistics: stats(block)}},
  );
  return cardText(panel, "Defenses and attacks");
}

// ------------------------------------------------------------------------------- the owner card

test("the owner Armor Class card shows the fighting AC and the real unarmored total", () => {
  const card = cardText(ownerCards(WORN), "Armor Class");

  assert.match(card, /AC 20 \(unarmored 18\)/);
  // The review's exact complaint: base_value 17 is the calculation before the standing +1, and
  // calling it the unarmored total told the player to compare 17 against their unarmoured 18.
  assert.doesNotMatch(card, /unarmored 17/);
  assert.match(card, /Wearing Imperial Plate Battle Dress \(Armor Class 18\) and a Shield \(\+2\) gives an Armor Class of 20\./);
});

test("the owner Speed card shows the penalized Speed and what it would be without the armour", () => {
  const card = cardText(ownerCards(WORN), "Speed");

  assert.match(card, /20 ft walking\./);
  assert.match(card, /Your armour slows you: 30 ft without it\./);
  assert.match(card, /needs Strength 15 to wear and this character has 10/);
  assert.doesNotMatch(card, /30 ft walking\./);
});

test("a sheet with no armour shows no alternative to compare against", () => {
  const card = cardText(ownerCards({ac: {base_value: 13, value: 14, effective_value: 14, unarmored_value: 14},
    speed: {walking_ft: 30, effective_walking_ft: 30}}), "Armor Class");

  assert.match(card, /AC 14\./);
  assert.doesNotMatch(card, /unarmored/);
  assert.doesNotMatch(card, /base 13/);
});

test("a sheet written before the lane keeps its own number and is never called unarmored", () => {
  const armor = cardText(ownerCards(LEGACY), "Armor Class");
  const speed = cardText(ownerCards(LEGACY), "Speed");

  // base_value is not the unarmored total, so it is labelled "base" and never "unarmored".
  assert.match(armor, /AC 18 \(base 17\)/);
  assert.doesNotMatch(armor, /unarmored/);
  assert.match(speed, /30 ft walking\./);
  assert.doesNotMatch(speed, /Your armour slows you/);
});

test("a sheet with no recorded Armor Class or Speed says so instead of showing a number", () => {
  const empty = {ac: {base_value: null, value: null}, speed: {walking_ft: null}};

  assert.match(cardText(ownerCards(empty), "Armor Class"), /Not recorded\./);
  assert.match(cardText(ownerCards(empty), "Speed"), /Not recorded\./);
});

// ------------------------------------------------------------------------------- the GM panel

test("the GM Defenses card shows the same Armor Class, Speed and explanations as the owner's card", () => {
  const panel = gmDefenses(WORN);

  assert.match(panel, /Armor Class 20 \(unarmored 18\)\./);
  assert.doesNotMatch(panel, /unarmored 17/);
  assert.match(panel, /Wearing Imperial Plate Battle Dress \(Armor Class 18\) and a Shield \(\+2\) gives an Armor Class of 20\./);
  assert.match(panel, /Walking speed 20 ft\./);
  assert.match(panel, /needs Strength 15 to wear and this character has 10/);
});

test("the GM Defenses card keeps a legacy sheet's own number and never labels base_value unarmored", () => {
  const panel = gmDefenses(LEGACY);

  assert.match(panel, /Armor Class 18 \(base 17\)\./);
  assert.doesNotMatch(panel, /unarmored/);
  assert.match(panel, /Walking speed 30 ft\./);
  assert.doesNotMatch(panel, /Walking speed 20 ft\./);
});

// ------------------------------------------------------------------ one derivation, two consumers

test("the owner card and the GM panel agree on every number they share", () => {
  for (const block of [WORN, LEGACY]) {
    const owner = cardText(ownerCards(block), "Armor Class");
    const gm = gmDefenses(block);
    // The two cards phrase the same shared sentence differently ("AC 20 ...." / "Armor Class
    // 20 ...."), so the comparison is over the number and its alternative, never the wording.
    const ownerNumbers = owner.match(/AC ([\d][^.]*)\./)[1];
    assert.equal(gm.includes(`Armor Class ${ownerNumbers}.`), true,
      `owner "AC ${ownerNumbers}." must appear as "Armor Class ${ownerNumbers}." in the GM panel`);
  }
});
