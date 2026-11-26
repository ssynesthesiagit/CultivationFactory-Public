// ATTACKCHIP1: an attack the server offers is a legal chip on the table's action bar, not a greyed one. The bar's
// attackWeaponCard() is run from the real tabletop.js source (vm, no browser); its refusals come from the real
// refusalFor()/reasonFor() in the same file. The four cases: an offered ACTION attack with the Action unused is enabled;
// the same attack with the Action spent is disabled saying so; a server unavailable reason disables it and is shown; an
// attack the server did not offer stays disabled.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {FakeElement} from "../../tests/attacklist1_dom.mjs";
import {attackGroupView, groupAttackRows} from "./attack-groups.js";

const source = fs.readFileSync(new URL("./tabletop.js", import.meta.url), "utf8");
const ATTACK = "action:typed.test.weapon.iron_fist";
const ROW_ID = "act:" + ATTACK;
const REASON = "You have no free hand for the Iron Fist. Free a hand first.";

function extract(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, "missing source boundary: " + start);
  return source.slice(from, to);
}

const row = () => ({
  id: ROW_ID, label: "Iron Fist attack", group: "attacks", kind: "combat", economy: "ACTION",
  combat: {source_definition_id: ATTACK}, detail: {to_hit: "+5", attacks: 1, damage: "1d8+3 bludgeoning", range: "5 ft"},
});

// One card for the Iron Fist: the chips it made, with the disabled state and the hover text each one was given.
function drawCard({offered = true, turn = {action: true}, serverReasons = {}} = {}) {
  const chips = [];
  const app = {attackAsk: null, attackSpent: new Map(), optionDraft: null, menu: {composition: {}},
    state: {button_states: {}, unavailable_reasons: serverReasons}};
  const context = vm.createContext({
    app, Map, Set, document: {createElement: tag => new FakeElement(tag)},
    attackGroupView, groupAttackRows,
    makeButton: (label, detail, options = {}) => {
      chips.push({label, disabled: Boolean(options.disabled), title: String(options.title || "")});
      const button = new FakeElement("button");
      button.label = label;
      return button;
    },
    markActive() {}, rulesTextFor: () => "", additionalRuleText: () => "",
    actionHoverText: (r, options = {}) => [options.rules, ...(options.extra || []), options.note].filter(Boolean).join("\n\n"),
    actionTipCard: () => null, runButton() {}, renderActionBar() {}, projectOf: () => null, api: () => Promise.reject(new Error("no api")),
  });
  vm.runInContext(extract("// ------------------------------------------------------------------ action bar", "function buttonDetail(button) {"), context);
  vm.runInContext(extract("// ------------------------------------------------------------------ ATTACKLIST1: the Attacks section, one card per weapon", "async function renderActionBar(target = $("), context);
  const rows = [row()];
  const groups = new Map(offered ? [[ATTACK, {source_definition_id: ATTACK}]] : []);
  const ctx = {makeButton: context.makeButton, used: new Set(), groups, actor: {id: "actor:test", turn_state: turn, resources: []},
    sheet: {buttons: rows}, menu: {actor_id: "actor:test"}};
  const [weapon] = groupAttackRows(rows);
  vm.runInContext("attackWeaponCard", context)(ctx, weapon);
  assert.ok(chips.length >= 1, "the card drew at least one chip");
  return chips[0];
}

test("an offered ACTION attack with the Action unused is enabled", () => {
  const chip = drawCard({turn: {action: true}});
  assert.equal(chip.disabled, false, "the server offers it and the Action is free: it is a legal chip");
  assert.doesNotMatch(chip.title, /Unavailable now/, "a legal chip carries no refusal hover text");
});

test("an offered ACTION attack with the Action spent is disabled and says the Action is used", () => {
  const chip = drawCard({turn: {action: false}});
  assert.equal(chip.disabled, true);
  assert.match(chip.title, /Action already used this turn/);
});

test("an offered attack with a server unavailable reason is disabled showing that reason", () => {
  const chip = drawCard({turn: {action: true}, serverReasons: {[ROW_ID]: REASON}});
  assert.equal(chip.disabled, true);
  assert.match(chip.title, new RegExp(REASON.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
});

test("an attack the server did not offer stays disabled", () => {
  const chip = drawCard({offered: false, turn: {action: true}});
  assert.equal(chip.disabled, true, "no offered source means no legal chip");
  assert.match(chip.title, /Unavailable now/, "with no specific reason the table still says it is unavailable");
});
