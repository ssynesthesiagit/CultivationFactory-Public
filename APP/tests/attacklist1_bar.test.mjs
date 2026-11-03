// ATTACKLIST1: the table's action bar, drawn by the real attackWeaponCard() from tabletop.js, against the real compiled
// rows of a Long Tongling (see attacklist1_groups.test.mjs). The bar and the pop-out sheet draw the same reading
// (attack-groups.js), so this file checks the bar's own part: one card per weapon, a chip per mode pressing the compiled
// button, an unavailable mode greyed in place with the table's reason on its hover card, and the 2-attack question.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {FakeElement} from "./attacklist1_dom.mjs";
import {attackGroupView, groupAttackRows} from "../static/tabletop/attack-groups.js";

const source = fs.readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");
const rows = JSON.parse(fs.readFileSync(new URL("./fixtures/attacklist1_longtongling_typed_rows.json", import.meta.url), "utf8"));
const ids = new Set(rows.map(row => row.id));
const JAVELIN = "action:typed.f11dfb35d6.weapon.biao_qiang";
const REASON = "You have no javelin left to throw. Pick one up first.";

function extract(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, "missing source boundary: " + start);
  return source.slice(from, to);
}

function harness({reason = () => "", buttons = rows} = {}) {
  const pressed = [];
  const renders = [];
  const app = {attackAsk: null, state: {button_states: {}}, attackSpent: new Map()};
  const context = vm.createContext({
    app, Map, Set, document: {createElement: tag => new FakeElement(tag)},
    attackGroupView, groupAttackRows,
    // The table's own helpers are not what this test is about: a button records what it was told and what it presses.
    makeButton: (label, detail, options = {}) => {
      const button = new FakeElement("button");
      button.textContent = label + (detail ? " " + detail : "");
      button.label = label;
      button.detail = detail;
      button.disabled = Boolean(options.disabled);
      button.className = "tt-btn " + (options.cls || "");
      button.dataset.tip = options.title || label;
      button.tipCard = options.tipCard || null;
      button.onClick = options.onClick;
      return button;
    },
    markActive() {},
    rulesTextFor: () => "",
    reasonFor: (actor, row) => reason(row),
    additionalRuleText: () => "",
    actionHoverText: (row, options = {}) => [options.rules, ...(options.extra || []), options.note].filter(Boolean).join("\n\n"),
    actionTipCard: () => null,
    actionRules: (text) => new FakeElement("details"),
    actionSummary: () => "",
    runButton: (row, actorId) => { pressed.push({id: row.id, actorId}); return Promise.resolve({ok: true}); },
    renderActionBar: () => { renders.push(true); },
  });
  vm.runInContext([
    extract("// ------------------------------------------------------------------ ATTACKLIST1: the Attacks section, one card per weapon", "async function renderActionBar(target = $("),
  ].join("\n"), context);
  // The bar treats a weapon as available when the menu holds its source; a refusal is the table's own reason.
  const groups = new Map(buttons.filter(row => row.combat?.source_definition_id)
    .map(row => [row.combat.source_definition_id, {source_definition_id: row.combat.source_definition_id}]));
  const ctx = {makeButton: context.makeButton, used: new Set(), groups, actor: {id: "actor:longtongling"},
    sheet: {buttons: buttons}, menu: {actor_id: "actor:longtongling"}};
  return {
    app, pressed, renders, ctx, used: ctx.used,
    card: (weapon) => vm.runInContext("attackWeaponCard", context)(ctx, weapon),
    groups: () => groupAttackRows(buttons).map(weapon => [weapon, null]),
  };
}

const chipButtons = card => card.querySelectorAll(".tt-attack-chips")[0].querySelectorAll(".tt-btn")
  .filter(button => !button.classList.contains("tt-attack-ask") && button.parent?.classList.contains("tt-attack-chips"));

test("the bar draws one card per weapon, its modes as chips under it", () => {
  const ui = harness();
  const cards = groupAttackRows(rows).map(weapon => ui.card(weapon));
  assert.equal(cards.length, 4, "four weapons, not fifty buttons");
  const javelin = cards.find(card => card.dataset.attackGroup === JAVELIN);
  assert.equal(javelin.querySelector("b").textContent, "Biao Qiang (Javelin)");
  assert.match(javelin.querySelector("small").textContent, /^\u00d74 /);
  const chips = chipButtons(javelin);
  assert.deepEqual(chips.map(chip => chip.label), ["Melee", "Thrown", "Batter", "Batter (thrown)", "+ Brutal Strike", "+ Brutal Strike"]);
  assert.ok([...ui.used].every(source => ids.has(source) || ids.has("act:" + source)), "an aggregated weapon still marks its rows as drawn");
  assert.ok(!chips.some(chip => chip.label.includes("choose the rest")), "the mode note is no longer a button family");
});

test("a chip presses the compiled button it stands for", async () => {
  const ui = harness();
  const cards = groupAttackRows(rows).map(weapon => ui.card(weapon));
  const javelin = cards.find(card => card.dataset.attackGroup === JAVELIN);
  const thrown = chipButtons(javelin).find(chip => chip.label === "Thrown");
  await thrown.onClick();
  assert.deepEqual(ui.pressed, [{id: "act:action:typed.f11dfb35d6.weapon.biao_qiang#thrown", actorId: "actor:longtongling"}]);
});

test("an unavailable mode stays in the card, greyed, with the table's own reason", () => {
  const ui = harness({reason: row => (row.id.includes("#thrown") ? REASON : "")});
  const javelin = groupAttackRows(rows).map(weapon => ui.card(weapon)).find(card => card.dataset.attackGroup === JAVELIN);
  const thrown = chipButtons(javelin).find(chip => chip.label === "Thrown");
  assert.equal(thrown.disabled, true, "the table refused it, so it cannot be pressed");
  assert.match(String(thrown.dataset.tip), new RegExp(REASON.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.equal(chipButtons(javelin).filter(chip => chip.disabled).length, 3, "both thrown modes and the thrown Brutal Strike variant");
  const melee = chipButtons(javelin).find(chip => chip.label === "Melee");
  assert.equal(melee.disabled, false);
});

test("two attacks ask all-on-this or choose-each, and the answers are the compiled rows", async () => {
  const claw = suffix => ({
    id: "act:action:typed.test.weapon.claw" + suffix, label: "Claw attack", group: "attacks", kind: "combat", economy: "ACTION",
    combat: {source_definition_id: "action:typed.test.weapon.claw" + suffix},
    detail: {to_hit: "+5", attacks: 2, damage: "1d8+2", range: "5 ft"},
  });
  const clawRows = [claw(""), claw(".attack_action_begin"), claw(".attack_action_rest")];
  const ui = harness({buttons: clawRows});
  const [weapon] = groupAttackRows(clawRows);
  const card = ui.card(weapon);
  const chip = chipButtons(card)[0];
  assert.equal(chip.dataset.askable, "1", "the bar marks the chip that has a question");
  chip.onClick();
  assert.equal(ui.renders.length, 1, "asking repaints the bar with the question in the weapon's card");
  assert.deepEqual({...ui.app.attackAsk}, {group: "action:typed.test.weapon.claw", chip: ui.app.attackAsk.chip, actor: "actor:longtongling"});
  const asked = ui.card(weapon).querySelector(".tt-attack-ask");
  assert.ok(asked, "the question sits under the weapon's chips");
  assert.match(asked.querySelector("p").textContent, /2 attacks with Claw\./);
  const answers = asked.querySelectorAll(".tt-btn");
  const all = answers.find(button => button.label === "All 2 on this");
  const each = answers.find(button => button.label === "Choose each");
  assert.ok(all && each, "both answers are real buttons");
  all.onClick();
  each.onClick();
  assert.deepEqual(ui.pressed.map(entry => entry.id), [
    "act:action:typed.test.weapon.claw",
    "act:action:typed.test.weapon.claw.attack_action_begin",
  ]);
  assert.equal(ui.app.attackAsk, null, "answering closes the question");
  assert.equal(ui.app.attackSpent.get("action:typed.test.weapon.claw"), 1, "choosing each counts the one attack it sent");
});

test("a weapon says how many of its attacks are left, and only when it counts them", () => {
  const claw = suffix => ({
    id: "act:action:typed.test.weapon.claw" + suffix, label: "Claw attack", group: "attacks", kind: "combat",
    combat: {source_definition_id: "action:typed.test.weapon.claw" + suffix},
    detail: {to_hit: "+5", attacks: 2, damage: "1d8+2", range: "5 ft"},
  });
  const clawRows = [claw(""), claw(".attack_action_begin"), claw(".attack_action_rest")];
  const ui = harness({buttons: clawRows});
  const [weapon] = groupAttackRows(clawRows);
  assert.match(ui.card(weapon).querySelector("small").textContent, /2 attacks left/);
  // Once the Action is under way the server stops offering the whole Action and leaves its continuation: the bar now
  // counts what it saw itself send (it sent one attack).
  ui.ctx.groups = new Map([["action:typed.test.weapon.claw.attack_action_rest",
    {source_definition_id: "action:typed.test.weapon.claw.attack_action_rest"}]]);
  ui.app.attackSpent = new Map([[weapon.key, 1]]);
  assert.match(ui.card(weapon).querySelector("small").textContent, /1 of 2 attacks left/);
  // A bar that did not see the Action start cannot know the number, and says so rather than guessing.
  ui.app.attackSpent = new Map();
  assert.match(ui.card(weapon).querySelector("small").textContent, /· attacks left$/);
});

test("a weapon with one attack never asks", () => {
  const ui = harness();
  const javelin = groupAttackRows(rows).map(weapon => ui.card(weapon)).find(card => card.dataset.attackGroup === JAVELIN);
  assert.ok(chipButtons(javelin).every(chip => chip.dataset.askable === undefined));
});
