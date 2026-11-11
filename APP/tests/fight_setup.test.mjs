import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {canAddFighter, MAX_FIGHTERS_PER_SIDE} from "../static/tabletop/limits.js";
import {playerError} from "../static/tabletop/error-text.js";
import {setupControlHtml, splitSetupControl, MODEL_PREFIX} from "../static/tabletop/seats.js";

test("fight setup caps each side at ten and disables the add button", async () => {
  assert.equal(MAX_FIGHTERS_PER_SIDE, 10);
  assert.equal(canAddFighter(9), true);
  assert.equal(canAddFighter(10), false);
  const source = await readFile(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");
  // Execute the real builder and its event handlers with an in-process DOM.
  // This is an interaction regression, not a browser/rendering claim.
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.handlers = {}; this.value = ""; this.dataset = {}; }
    set innerHTML(value) {
      this.children = [];
      if (value.startsWith("<h4>")) {
        const slots = new Element("div"); slots.className = "tt-slots";
        this.append(new Element("h4"), slots, new Element("button"));
      }
    }
    append(...elements) { elements.forEach(element => this.appendChild(element)); }
    appendChild(element) { element.parent = this; this.children.push(element); }
    replaceChildren(...elements) { this.children = []; this.append(...elements); }
    setAttribute(name, value) { this[name] = value; }
    addEventListener(name, handler) { this.handlers[name] = handler; }
    click() { if (!this.disabled) this.handlers.click?.(); }
    remove() { this.parent.children.splice(this.parent.children.indexOf(this), 1); }
    querySelector(selector) {
      return this.children.find(element => selector.startsWith(".")
        ? element.className === selector.slice(1) : element.tag === selector);
    }
  }
  const host = new Element("div");
  const sides = [];
  const context = vm.createContext({
    builderBuilt: false, canAddFighter, app: {providers: []}, loadProviders: async () => {}, setupControlHtml, splitSetupControl, MODEL_PREFIX,
    // The builder reads the model list's retry state (provider-list.js, SEATLIST1) for its "retrying" note.
    providerList: {state: {unavailable: false}},
    document: {createElement: tag => new Element(tag)}, $: () => host,
    api: async path => path.endsWith("factory-characters") ? [{project_id: "hero", display_name: "Hero"}] : {maps: [], builtin: []},
    escapeHtml: value => value, updatePresetSaveButtons: () => {},
    // "+ Add fighter" also opens the fighter picker (OPUSUI2); closing it here picks nobody, the slot stays.
    fighterPicker: {open() {}, fillSlotFace() {}}, applyPick() {},
    singleTeamBar: side => { sides.push(side); return new Element("div"); },
    presetBar: () => new Element("div"),
  });
  const builder = source.slice(source.indexOf("async function buildFightBuilder()"), source.indexOf("// Both team and whole-setup saves"));
  assert.ok(builder.startsWith("async function buildFightBuilder()"));
  vm.runInContext(builder, context);
  await vm.runInContext("buildFightBuilder()", context);
  assert.equal(sides.length, 2);
  for (const side of sides) {
    const add = side.host.parent.querySelector("button");
    for (let i = 1; i < 10; i++) add.click();
    assert.equal(side.slots.length, 10);
    assert.equal(add.disabled, true);
    assert.equal(add.title, "Up to 10 fighters per side");
    add.click();
    side.addSlot(); // programmatic/preset additions share the same guard
    assert.equal(side.slots.length, 10);
    side.slots[4].slot.children.find(element => element["aria-label"] === "Remove fighter").click();
    assert.equal(side.slots.length, 9);
    assert.equal(add.disabled, false);
    add.click();
    assert.equal(side.slots.length, 10);
    assert.equal(add.disabled, true);
    assert.equal(side.host.children.length, 10);
  }
});

test("fight setup explains an over-limit validation error and other invalid choices", () => {
  const tooMany = playerError({
    status: 422, path: "/api/combat/factory-matches",
    requestBody: {project_ids: Array.from({length: 11}, (_, index) => `hero-${index}`)},
    validationErrors: [{loc: ["body", "project_ids"], type: "too_long"}],
  });
  assert.equal(tooMany, "Team 1 has 11 fighters; the most is 10.");
  const tooManyOpponents = playerError({
    status: 422, path: "/api/combat/factory-matches",
    requestBody: {opponent_actor_ids: Array.from({length: 11}, (_, index) => `actor:${index}`)},
    validationErrors: [{loc: ["body", "opponent_actor_ids"], type: "too_long"}],
  });
  assert.equal(tooManyOpponents, "Team 2 has 11 fighters; the most is 10.");
  const invalid = playerError({
    status: 422, path: "/api/combat/factory-matches",
    validationErrors: [{loc: ["body", "arena_id"], type: "string_type"}],
  });
  assert.equal(invalid, "Choose an arena from the map list.");
  assert.doesNotMatch(invalid, /REQUEST_SCHEMA_INVALID|project_ids|arena_id/);
});

test("a map with no room explains itself instead of a generic failure", () => {
  const noRoom = playerError({
    code: "COMBAT_SETUP_NO_ROOM", status: 422, path: "/api/combat/factory-matches",
  });
  assert.match(noRoom, /no room/i);
  assert.match(noRoom, /larger map|fewer fighters|take a fighter off/i);
  assert.doesNotMatch(noRoom, /COMBAT_SETUP_NO_ROOM|422|subsystem|combat\.factory/);
  // The same code on another route keeps its own plain wording.
  assert.equal(playerError({code: "COMBAT_SETUP_NO_ROOM", status: 400, path: "/api/other"}), noRoom);
});
