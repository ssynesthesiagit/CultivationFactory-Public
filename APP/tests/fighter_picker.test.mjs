// node --test APP/tests/fighter_picker.test.mjs  (run by tests/test_fighter_picker.py)
// The fighter picker in Fights > New fight (OPUSUI2, owner 2026-10-04): search, filters, sorting, recency, and a pick
// that creates exactly the fight the old "— choose —" dropdown created.
import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {canAddFighter} from "../static/tabletop/limits.js";
import {setupControlHtml, splitSetupControl, MODEL_PREFIX} from "../static/tabletop/seats.js";
import {
  applyPick, cardLabel, describe, filterCharacters, initialsOf, matchesQuery, pathOptions, recencyIndex, recentlyUsed,
  sortCharacters,
} from "../static/tabletop/fighter-picker.js";

const ROWS = [
  {project_id: "a", display_name: "Lin Qiao", cultivation_level: 5, path: "Qi Cultivation", subpath: "Cinder Heart Cultivator",
    spheres: ["Fire", "Scoundrel"], edited_at: "2026-09-01T10:00:00Z"},
  {project_id: "b", display_name: "Bai Yún", cultivation_level: 9, path: "Body Cultivation", subpath: null,
    spheres: ["Iron Fist"], edited_at: "2026-10-02T08:00:00Z"},
  {project_id: "c", display_name: "Chen Lan", cultivation_level: 3, path: "Qi Cultivation", subpath: "Storm Caller",
    spheres: ["Lightning"], edited_at: null},
  {project_id: "d", display_name: "Ash Wei", cultivation_level: null, path: null, spheres: []},
];
test('every Path is searchable and filterable, with legacy rows unchanged', () => {
  const multi = {...ROWS[0], paths: ['Qi Cultivation', 'Body Refining', 'Soul Cultivation']};
  const rows = [multi, ROWS[1], ROWS[3]];
  assert.deepEqual(pathOptions(rows), ['Body Cultivation', 'Body Refining', 'Qi Cultivation', 'Soul Cultivation']);
  assert.deepEqual(filterCharacters(rows, {path: 'Body Refining'}), [multi]);
  assert.deepEqual(filterCharacters(rows, {path: 'Soul Cultivation'}), [multi]);
  assert.deepEqual(filterCharacters(rows, {path: 'Body Cultivation'}), [ROWS[1]]);
  assert.ok(matchesQuery(multi, 'soul'));
  assert.equal(describe(multi), describe(ROWS[0]));
});
const FIGHTS = [
  {match_id: "m1", created_at: "2026-09-20T12:00:00Z", updated_at: "2026-09-21T12:00:00Z",
    participant_control_modes: {"actor:factory.c": "MANUAL", "actor:factory.a": "LOCAL_AUTO", "actor:other.x": "MANUAL"}},
  {match_id: "m2", created_at: "2026-10-03T09:00:00Z", participant_control_modes: {"actor:factory.c": "LOCAL_AUTO"}},
  {match_id: "m3", participant_control_modes: {"actor:factory.d": "MANUAL"}},  // no dates: ignored
];
const ids = rows => rows.map(row => row.project_id);

test("search matches name, Path, Subpath and Sphere; every word must match; accents and case are ignored", () => {
  assert.deepEqual(ids(filterCharacters(ROWS, {query: "lin"})), ["a"]);
  assert.deepEqual(ids(filterCharacters(ROWS, {query: "body"})), ["b"]);
  assert.deepEqual(ids(filterCharacters(ROWS, {query: "storm"})), ["c"]);
  assert.deepEqual(ids(filterCharacters(ROWS, {query: "iron fist"})), ["b"]);
  assert.deepEqual(ids(filterCharacters(ROWS, {query: "yun"})), ["b"]);  // "Yún"
  assert.deepEqual(ids(filterCharacters(ROWS, {query: "QI fire"})), ["a"]);
  assert.deepEqual(ids(filterCharacters(ROWS, {query: "qi water"})), []);
  assert.deepEqual(ids(filterCharacters(ROWS, {query: "   "})), ["a", "b", "c", "d"]);
  assert.equal(matchesQuery(ROWS[3], "ash"), true);
});

test("Path and CL filters; a character without a CL is left out once a CL bound is set", () => {
  assert.deepEqual(pathOptions(ROWS), ["Body Cultivation", "Qi Cultivation"]);
  assert.deepEqual(ids(filterCharacters(ROWS, {path: "Qi Cultivation"})), ["a", "c"]);
  assert.deepEqual(ids(filterCharacters(ROWS, {clMin: "4"})), ["a", "b"]);
  assert.deepEqual(ids(filterCharacters(ROWS, {clMax: 5})), ["a", "c"]);
  assert.deepEqual(ids(filterCharacters(ROWS, {clMin: 4, clMax: 6, path: "Qi Cultivation", query: "cinder"})), ["a"]);
  assert.deepEqual(ids(filterCharacters(ROWS, {clMin: "", clMax: ""})), ["a", "b", "c", "d"]);
});

test("recency: the latest of the character's own edit and the fights it played; Recent sorts newest first", () => {
  const recency = recencyIndex(ROWS, FIGHTS);
  assert.deepEqual(recency.a, {played: "2026-09-21T12:00:00Z", recent: "2026-09-21T12:00:00Z"});
  assert.deepEqual(recency.b, {played: null, recent: "2026-10-02T08:00:00Z"});
  assert.deepEqual(recency.c, {played: "2026-10-03T09:00:00Z", recent: "2026-10-03T09:00:00Z"});
  assert.deepEqual(recency.d, {played: null, recent: null});
  assert.deepEqual(ids(sortCharacters(ROWS, "recent", recency)), ["c", "b", "a", "d"]);
  assert.deepEqual(ids(sortCharacters(ROWS, "name", recency)), ["d", "b", "c", "a"]);
  assert.deepEqual(ids(sortCharacters(ROWS, "cl", recency)), ["b", "a", "c", "d"]);
  // With no dates at all, Recent falls back to the name order (stable, never random).
  assert.deepEqual(ids(sortCharacters(ROWS, "recent", recencyIndex(ROWS.map(row => ({...row, edited_at: null})), []))),
    ["d", "b", "c", "a"]);
  assert.deepEqual(ids(recentlyUsed(ROWS, recency)), ["c", "a"]);
  assert.deepEqual(ids(recentlyUsed(ROWS, recency, 1)), ["c"]);
  assert.deepEqual(ids(ROWS), ["a", "b", "c", "d"], "sorting does not reorder the caller's list");
});

test("sorting and searching 150 characters stays quick", () => {
  const many = Array.from({length: 150}, (_, index) => ({project_id: `p${index}`, display_name: `Hero ${index}`,
    cultivation_level: index % 20 + 1, path: index % 2 ? "Qi Cultivation" : "Body Cultivation", spheres: ["Fire", "Water"],
    edited_at: `2026-09-${String(index % 28 + 1).padStart(2, "0")}T00:00:00Z`}));
  const started = performance.now();
  for (let round = 0; round < 50; round++) sortCharacters(filterCharacters(many, {query: "hero 1"}), "recent", recencyIndex(many, FIGHTS));
  assert.ok(performance.now() - started < 1000);
  assert.equal(filterCharacters(many, {query: "hero 14"}).length, 12);  // 14, 114, 140-149
});

test("card words read plainly", () => {
  assert.equal(describe(ROWS[0]), "CL 5 · Qi Cultivation · Cinder Heart Cultivator");
  assert.equal(describe(ROWS[3]), "");
  assert.equal(initialsOf("Lin Qiao"), "LQ");
  assert.equal(initialsOf("Ash"), "A");
  assert.equal(initialsOf(""), "?");
  assert.equal(cardLabel(ROWS[0], "Team 2"),
    "Add Lin Qiao, CL 5 · Qi Cultivation · Cinder Heart Cultivator; Spheres: Fire, Scoundrel to Team 2");
  assert.match(cardLabel(ROWS[1], "Team 1", true), /Already in this fight\.$/);
  assert.doesNotMatch(cardLabel(ROWS[0], "Team 1"), /project|actor:|tianxia\./);
});

// ---------------------------------------------------------------- the real builder, old dropdown vs picker
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.handlers = {}; this.value = ""; this.attributes = {}; this.dataset = {}; }
  set innerHTML(value) {
    this.children = [];
    if (value.startsWith("<h4>")) {
      const slots = new Element("div"); slots.className = "tt-slots";
      this.append(new Element("h4"), slots, new Element("button"));
    }
  }
  append(...elements) { elements.forEach(element => this.appendChild(element)); }
  appendChild(element) { if (typeof element === "object") { element.parent = this; this.children.push(element); } }
  replaceChildren(...elements) { this.children = []; this.append(...elements); }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  dispatchEvent(event) { this.handlers[event.type]?.(event); }
  click() { if (!this.disabled) return this.handlers.click?.(); }
  remove() { this.parent.children.splice(this.parent.children.indexOf(this), 1); }
  close() {}
  querySelector(selector) {
    return this.children.find(element => selector.startsWith(".") ? element.className === selector.slice(1) : element.tag === selector);
  }
}

async function builder() {
  const source = await readFile(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");
  const host = new Element("div");
  const sides = [], posts = [], loads = [], picker = {opened: [], faces: []};
  const context = vm.createContext({
    builderBuilt: false, canAddFighter, applyPick, FACTORY: "actor:factory.", Event, enc: encodeURIComponent,
    app: {providers: []}, loadProviders: async () => {}, setupControlHtml, splitSetupControl, MODEL_PREFIX,
    // The builder reads the model list's retry state (provider-list.js, SEATLIST1) for its "retrying" note.
    providerList: {state: {unavailable: false}},
    document: {createElement: tag => new Element(tag)}, $: selector => (selector === "#ttBuilder" ? host : new Element("dialog")),
    api: async (path, options) => {
      if (path.endsWith("factory-characters")) return ROWS;
      if (path.endsWith("/maps")) return {maps: [], builtin: [{arena_id: "arena", display_name: "Field"}]};
      posts.push(JSON.parse(JSON.stringify(options.body)));
      return {match_id: "new"};
    },
    escapeHtml: value => value, updatePresetSaveButtons: () => {}, toast: message => { throw new Error(message); },
    loadPrefight: entry => loads.push(entry.who.value), serializePrefight: () => [], loadMatch: async () => true,
    singleTeamBar: side => { sides.push(side); return new Element("div"); },
    presetBar: () => new Element("div"),
    fighterPicker: {open: options => picker.opened.push(options), fillSlotFace: (button, row) => picker.faces.push([button, row?.project_id])},
  });
  const code = source.slice(source.indexOf("async function buildFightBuilder()"), source.indexOf("// Both team and whole-setup saves"));
  vm.runInContext(code, context);
  await vm.runInContext("buildFightBuilder()", context);
  const create = host.children.at(-1).children.find(element => element.textContent === "Create fight");
  return {sides, posts, loads, picker, create};
}
const faceOf = entry => entry.slot.children.find(element => element.className === "tt-slot-face");
const removeOf = entry => entry.slot.children.find(element => element.attributes["aria-label"] === "Remove fighter");

test("a pick from the picker creates the same fight as the old dropdown", async () => {
  // Old way: choose in each slot's dropdown (its change event) and set You/AI in the control dropdown.
  const old = await builder();
  old.sides[0].slots[0].who.value = "a"; old.sides[0].slots[0].who.handlers.change({type: "change"});
  old.sides[0].slots[0].control.value = "LOCAL_AUTO";
  old.sides[0].addSlot();
  old.sides[0].slots[1].who.value = "c"; old.sides[0].slots[1].who.handlers.change({type: "change"});
  old.sides[1].slots[0].who.value = "b"; old.sides[1].slots[0].who.handlers.change({type: "change"});
  await old.create.click();

  // New way: click the slot face / "+ Add fighter", then a card in the picker.
  const now = await builder();
  const [left, right] = now.sides;
  assert.equal(left.slots[0].who.hidden, true, "the dropdown stays as the slot's value but is hidden");
  faceOf(left.slots[0]).click();
  let opened = now.picker.opened.at(-1);
  assert.equal(opened.teamName, "Team 1");
  assert.equal(opened.mode, "MANUAL", "Team 1 defaults to You, as before");
  assert.deepEqual([...opened.taken], []);
  assert.equal(opened.onPick({pid: "a", mode: "LOCAL_AUTO"}), true);
  assert.equal(left.slots.length, 1, "the slot clicked is filled, not a new one");
  left.host.parent.querySelector("button").click();  // + Add fighter
  assert.equal(left.slots.length, 2);
  opened = now.picker.opened.at(-1);
  assert.deepEqual([...opened.taken], ["a"]);
  opened.onPick({pid: "c", mode: "MANUAL"});
  faceOf(right.slots[0]).click();
  opened = now.picker.opened.at(-1);
  assert.equal(opened.mode, "LOCAL_AUTO", "Team 2 defaults to AI, as before");
  assert.deepEqual([...opened.taken].sort(), ["a", "c"], "fighters already on either side are marked");
  opened.onPick({pid: "b", mode: "LOCAL_AUTO"});
  assert.deepEqual(now.picker.faces.at(-1)[1], "b", "the slot face shows the picked character");
  await now.create.click();

  assert.equal(old.posts.length, 1);
  assert.deepEqual([...now.loads], [...old.loads], "each pick loads the fighter's casts before the fight, as the dropdown did");
  assert.deepEqual([...now.loads], ["a", "c", "b"]);
  assert.deepEqual(now.posts, old.posts);
  assert.deepEqual(now.posts[0].project_ids, ["a", "c"]);
  assert.deepEqual(now.posts[0].opponent_actor_ids, ["actor:factory.b"]);
  assert.deepEqual(now.posts[0].control_modes, {"actor:factory.a": "LOCAL_AUTO", "actor:factory.c": "MANUAL", "actor:factory.b": "LOCAL_AUTO"});
});

test("+ Add fighter: closing the picker without a pick takes the new slot away; Keep open adds a slot per pick", async () => {
  const {sides, picker} = await builder();
  const [left] = sides;
  const add = left.host.parent.querySelector("button");
  add.click();
  assert.equal(left.slots.length, 2);
  picker.opened.at(-1).onCancel();
  assert.equal(left.slots.length, 1, "a cancelled add leaves no empty slot behind");
  faceOf(left.slots[0]).click();
  picker.opened.at(-1).onCancel();
  assert.equal(left.slots.length, 1, "the team's own slot is never removed by a cancel");
  add.click();
  const opened = picker.opened.at(-1);
  opened.onPick({pid: "a", mode: "MANUAL"});
  opened.onPick({pid: "b", mode: "LOCAL_AUTO"});  // with "Keep open", each further pick takes a new slot
  assert.deepEqual([...left.slots].map(entry => entry.who.value), ["", "a", "b"]);
  assert.deepEqual([...left.slots].map(entry => entry.control.value), ["MANUAL", "MANUAL", "LOCAL_AUTO"]);
  // Up to the per-side limit: the picker is told when no more fit.
  for (let index = 0; index < 6; index++) assert.equal(opened.onPick({pid: `x${index}`, mode: "MANUAL"}), true);
  assert.equal(opened.onPick({pid: "x6", mode: "MANUAL"}), false);
  assert.equal(left.slots.length, 10);
  assert.equal(opened.onPick({pid: "x7", mode: "MANUAL"}), false);
  assert.equal(left.slots.length, 10);
  // The remove button still takes a fighter off.
  removeOf(left.slots[1]).click();
  assert.equal(left.slots.length, 9);
});
