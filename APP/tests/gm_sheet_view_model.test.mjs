// Focused tests for the GM-style Character Sheet view model.
// Run: node --test APP/tests/gm_sheet_view_model.test.mjs
//
// Synthetic GM-sheet fixture with catalog-derived records.
import test from "node:test";
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import path from "node:path";
import {fileURLToPath} from "node:url";

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const vm = require(path.join(here, "..", "static", "sheet_view_model.js"));
const scratch = require(path.join(here, "fixtures", "gm_sheet", "scratch_owner_sheet_snapshot.fixture.json"));
const libraryRows = require(path.join(here, "fixtures", "gm_sheet", "scratch_library_rows.fixture.json"));
const notesGearShapes = require(path.join(here, "fixtures", "gm_sheet", "notes_gear_shapes.fixture.json"));

const SCRATCH_PROJECT_ID = "00000000-0000-4000-8000-000000000002";

function sheetPayloadFromFixture() {
  // Mirror GET /api/characters/{id}/sheet fields the renderer consumes.
  return {
    schema_version: "TianxiaFoundry.OwnerCharacterSheetServiceResponse.v2",
    project_id: SCRATCH_PROJECT_ID,
    name: scratch.identity.display_name,
    build_status: "CHARACTER_SHEET_READY",
    plain_summary: "Character Sheet Ready. GM tactical authoring is the next step; GM export remains unavailable.",
    identity: {
      name: scratch.identity.display_name,
      title: scratch.identity.title,
      concept: scratch.identity.concept,
      current_cl: scratch.identity.cultivation_level,
      current_realm: scratch.identity.realm,
      path: scratch.identity.path,
      species: scratch.identity.species,
      key_ability: scratch.identity.key_ability,
    },
    workflow: {active_run: null, latest_run: null},
    sections: {},
    owner_character_sheet: scratch,
  };
}

test("placeholder names are recognized exactly", () => {
  for (const value of ["", "   ", "AI-proposed character", "ai-proposed character", "Unnamed Character"]) {
    assert.equal(vm.isPlaceholderName(value), true, `expected placeholder: ${JSON.stringify(value)}`);
  }
  for (const value of ["Wayfinder", "Shen Lihuo", "AI helper"]) {
    assert.equal(vm.isPlaceholderName(value), false, `expected real name: ${value}`);
  }
});

test("final-name precedence prefers the character-list overlay over the working name", () => {
  const resolved = vm.resolveOwnerFinalName({
    characterListName: "Wayfinder",
    libraryName: "AI-proposed character",
  });
  assert.equal(resolved, "Wayfinder");
});

test("final-name precedence falls back to the resolved workflow name", () => {
  const resolved = vm.resolveOwnerFinalName({
    characterListName: "",
    resolvedWorkflowName: "Wayfinder",
    libraryName: "AI-proposed character",
  });
  assert.equal(resolved, "Wayfinder");
});

test("every-placeholder inputs resolve to empty instead of an invented name", () => {
  const resolved = vm.resolveOwnerFinalName({
    characterListName: undefined,
    resolvedWorkflowName: null,
    libraryName: "AI-proposed character",
  });
  assert.equal(resolved, "");
});

test("library fixture reproduces the reported bug shape before the join", () => {
  const row = libraryRows.rows.find(row => row.project_id === SCRATCH_PROJECT_ID);
  assert.equal(row.name, "AI-proposed character");
});

test("scratch view model exposes the finalized identity", () => {
  const model = vm.buildSheetViewModel(sheetPayloadFromFixture());
  assert.equal(model.name, "Wayfinder");
  assert.equal(model.concept.includes("curious apprentice who studies old maps"), true);
  assert.equal(model.cl, 1);
  assert.equal(model.realmLabel, "Mortal Realm");
  assert.equal(model.pathLabel, "Qi Cultivation");
  assert.equal(model.species, "Human");
  assert.equal(model.keyAbility, "INT");
  assert.equal(model.state.tone, "ready");
});

test("at-a-glance tiles carry the compiled play values and nothing invented", () => {
  const model = vm.buildSheetViewModel(sheetPayloadFromFixture());
  const byId = Object.fromEntries(model.tiles.map(tile => [tile.id, tile.value]));
  assert.deepEqual(byId, {
    ac: "12",
    hp: "9/9",
    initiative: "+2",
    speed: "30 ft",
    pb: "+2",
    resource: "2/2",
    technique_attack: "+3",
    save_dc: "11",
  });
  assert.deepEqual(model.abilityChips, [
    {ability: "STR", score: 15, modifier: "+2"},
    {ability: "DEX", score: 14, modifier: "+2"},
    {ability: "CON", score: 13, modifier: "+1"},
    {ability: "INT", score: 12, modifier: "+1"},
    {ability: "WIS", score: 10, modifier: "+0"},
    {ability: "CHA", score: 10, modifier: "+0"},
  ]);
});

test("tab derivation exposes the stable eighteen mechanics surfaces", () => {
  const model = vm.buildSheetViewModel(sheetPayloadFromFixture());
  assert.deepEqual(model.tabs.map(tab => tab.id), vm.COMPLETE_CHARACTER_SURFACE_IDS);
  assert.deepEqual(model.tabs.map(tab => tab.label), vm.COMPLETE_CHARACTER_SURFACE_IDS.map(id => vm.COMPLETE_CHARACTER_SURFACE_LABELS[id]));
  assert.equal(model.tabs.every(tab => tab.available === false), true, "missing envelope keeps every surface explicitly unavailable");
  const again = JSON.stringify(vm.buildSheetViewModel(sheetPayloadFromFixture()));
  assert.equal(again, JSON.stringify(model), "view model must be deterministic for identical input");
});

test("learned abilities group learned content first with expandable text", () => {
  const model = vm.buildSheetViewModel(sheetPayloadFromFixture());
  assert.deepEqual(
    model.abilityGroups.map(group => group.key),
    ["talents", "background_talent", "path_features", "spheres", "sphere_automatic_components"],
  );
  const talents = model.abilityGroups.find(group => group.key === "talents");
  assert.equal(talents.cards.length, 2);
  assert.equal(talents.cards[0].name.length > 0, true);
  assert.equal(talents.cards[0].summary.length > 0, true);
  assert.equal(talents.cards[0].fullText.length > 0, true);
  const spheres = model.abilityGroups.find(group => group.key === "spheres");
  assert.deepEqual(spheres.cards.map(card => card.name).sort(), ["Beastmastery", "Scoundrel"]);
});

test("cultivation surface reports method, foundation, and acquisition counts", () => {
  const model = vm.buildSheetViewModel(sheetPayloadFromFixture());
  assert.equal(model.methodLabel, "Outer Court Twin-Current Primer");
  assert.equal(model.foundationLabel, "Empty Bowl Soul Anchor");
  assert.deepEqual(model.counts, {spheres: 2, talents: 2, insights: 0, automaticComponents: 6});
});


test("Notes & Gear normalization matches tab presence for all supported shapes", () => {
  const expected = {
    notes_only: {notes: 1, items: 0, visible: true},
    items_only: {notes: 0, items: 1, visible: true},
    equipment_only: {notes: 0, items: 1, visible: true},
    mixed: {notes: 1, items: 3, visible: true},
    empty: {notes: 0, items: 0, visible: false},
  };
  for (const [shape, snapshot] of Object.entries(notesGearShapes)) {
    const payload = sheetPayloadFromFixture();
    payload.owner_character_sheet = snapshot;
    const model = vm.buildSheetViewModel(payload);
    assert.equal(model.notesGear.notes.length, expected[shape].notes, `${shape} notes`);
    assert.equal(model.notesGear.items.length, expected[shape].items, `${shape} items`);
    assert.equal(model.tabs.length, vm.COMPLETE_CHARACTER_SURFACE_IDS.length, `${shape} stable mechanics tab count`);
    assert.equal(model.tabs.some(tab => tab.id === "notes_gear"), false, `${shape} must not reintroduce the retired Notes & Gear tab`);
  }
});

test("Notes & Gear keeps technical-only records out of the presentation model", () => {
  const model = vm.buildSheetViewModel({...sheetPayloadFromFixture(), owner_character_sheet: notesGearShapes.empty});
  assert.deepEqual(model.notesGear, {notes: [], items: [], hasContent: false});
  assert.equal(JSON.stringify(model).includes("item.raw.only"), false);
  assert.equal(JSON.stringify(model).includes("receipt_hash"), false);
});

test("Factory Armor Class uses the combat compiler display value and explains its equipment bonuses", () => {
  const payload = sheetPayloadFromFixture();
  payload.display_owner_character_sheet = structuredClone(payload.owner_character_sheet);
  payload.display_owner_character_sheet.ability_scores_and_statistics.combat_armor_class = {
    value: 15,
    tooltip: "Combat Armor Class includes the armor your character wears, its refinement, and any qualifying paired-weapon bonus.",
  };
  const model = vm.buildSheetViewModel(payload);
  const ac = model.tiles.find(tile => tile.id === "ac");
  assert.equal(ac.value, "15");
  assert.match(ac.tooltip, /armor your character wears/);
});

test("Factory Armor Class prefers compiled value in the populated API section", () => {
  const payload = sheetPayloadFromFixture();
  payload.sections = {abilities_statistics: {status: "ready", data: {
    armor_class: {value: 12},
    combat_armor_class: {value: 15, tooltip: "Compiled combat AC includes worn armor and qualifying bonuses."},
  }}};
  const model = vm.buildSheetViewModel(payload);
  const ac = model.tiles.find(tile => tile.id === "ac");
  assert.equal(ac.value, "15");
  assert.match(ac.tooltip, /Compiled combat AC/);
});

test("unavailable compiled AC is explicit instead of falling back to sealed AC", () => {
  const payload = sheetPayloadFromFixture();
  payload.sections = {abilities_statistics: {status: "ready", data: {
    armor_class: {value: 12}, combat_armor_class: {value: null, tooltip: "AC from combat unavailable."},
  }}};
  const model = vm.buildSheetViewModel(payload);
  const ac = model.tiles.find(tile => tile.id === "ac");
  assert.equal(ac.value, "Unavailable");
  assert.equal(ac.tooltip, "AC from combat unavailable.");
});
