// ATTACKLIST1: the table's action bar, drawn by the real attackWeaponCard() from tabletop.js, against the real compiled
// rows of a Long Tongling (see attacklist1_groups.test.mjs). The bar and the pop-out sheet draw the same reading
// (attack-groups.js), so this file checks the bar's own part: one card per weapon, a chip per mode pressing the compiled
// button, an unavailable mode greyed in place with the table's reason on its hover card, and the 2-attack question.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {FakeElement} from "./attacklist1_dom.mjs";
import {attackGroupView, groupAttackRows, renderVariantGroups} from "../static/tabletop/attack-groups.js";

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

// The bar's own shells: an element that reads the fixed markup a section group writes (an h3 and a .tt-ab-buttons)
// and knows its last child, which is all the section loop touches. Everything else under test stays the real source.
class BarElement extends FakeElement {
  set innerHTML(markup) {
    this.markup = String(markup);
    this.replaceChildren();
    for (const [, tag, attrs] of this.markup.matchAll(/<(\w+)\b([^>]*)>/g)) {
      const node = new BarElement(tag);
      node.className = /class="([^"]*)"/.exec(attrs)?.[1] || "";
      this.appendChild(node);
    }
  }
  get innerHTML() { return this.markup || ""; }
  get lastChild() { return this.children[this.children.length - 1] ?? null; }
}

function harness({reason = () => "", buttons = rows, refusal = () => null} = {}) {
  const pressed = [];
  const renders = [];
  const toasts = [];
  const app = {attackAsk: null, state: {button_states: {}}, attackSpent: new Map()};
  const context = vm.createContext({
    app, Map, Set, document: {createElement: tag => new BarElement(tag)},
    attackGroupView, groupAttackRows, renderVariantGroups,
    bindPress: (button, onClick) => button.addEventListener("click", onClick),
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
    buttonDetail: row => row.id.includes("weapon") ? "attack" : "",
    rulesTextFor: () => "",
    buttonBlock: (actor, row) => reason(row),
    reasonFor: (actor, row) => reason(row),
    additionalRuleText: () => "",
    actionHoverText: (row, options = {}) => [options.rules, ...(options.extra || []), options.note].filter(Boolean).join("\n\n"),
    actionTipCard: () => null,
    actionRules: (text) => new FakeElement("details"),
    actionSummary: () => "",
    // The table's answer to a press: ok, or a refusal with the table's own words (TBREFUSE1).
    runButton: (row, actorId) => {
      pressed.push({id: row.id, actorId});
      const message = refusal(row);
      return Promise.resolve(message ? {ok: false, message} : {ok: true, message: "done"});
    },
    toast: (message, error) => { toasts.push({message, error: Boolean(error)}); },
    handlePresetMessage: () => false,
    actorById: () => null,
    actorMessage: () => ({}),
    appendTableLine: () => {},
    renderActionBar: () => { renders.push(true); },
  });
  vm.runInContext([
    extract("// ------------------------------------------------------------------ ATTACKLIST1: the Attacks section, one card per weapon", "async function renderActionBar(target = $("),
  ].join("\n"), context);
  // The table's press path (TBREFUSE1: runButton, then one error toast for a refusal). Main has no pressButton and its
  // callers call runButton directly, so the same tests run there and show the missing toast.
  if (source.includes("async function pressButton(")) vm.runInContext(extract("async function pressButton(", "async function runButton("), context);
  // renderActionBar's own section loop, unmodified: its sections table, its real makeButton, its sheet-button filter
  // and its drawButton. Only the few reads they make of the rest of the page are substituted, so what a test draws is
  // the bar's real routing.
  vm.runInContext("function drawSections(sheet, menu, actor, app, groups, used, hidden) {\n"
    + "  const html = document.createElement('div');\n"
    + "  html.className = 'tt-ab-groups';\n"
    + "  const draftOptionRows = () => [];\n"
    + extract("  const sections = [", "  const html = document")
    + extract("  const makeButton = (label", "  const moveGroup")
    + extract("  const neededAsParent = new Set(", "  // A picker drawn under its ability")
    + "  return html;\n}", context);
  // The bar treats a weapon as available when the menu holds its source; a refusal is the table's own reason.
  const groups = new Map(buttons.filter(row => row.combat?.source_definition_id)
    .map(row => [row.combat.source_definition_id, {source_definition_id: row.combat.source_definition_id}]));
  const ctx = {makeButton: context.makeButton, used: new Set(), groups, actor: {id: "actor:longtongling"},
    sheet: {buttons: buttons}, menu: {actor_id: "actor:longtongling"}};
  return {
    app, pressed, renders, toasts, ctx, used: ctx.used,
    // The table's own channel handler, run against this harness's app (its channel is set by the test).
    run: source => vm.runInContext(source, context),
    card: (weapon) => vm.runInContext("attackWeaponCard", context)(ctx, weapon),
    drawSections: vm.runInContext("drawSections", context),
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

// ------------------------------------------------------------------ VARIANTS26: a variant of a weapon is a chip
// The Attacks section holds weapon rows, so an integrated weapon's alternate form (Constitution, Dexterity, a
// delivery) is a chip on that weapon's card, and a stowed weapon is never offered. The bar once sent every row that
// carried a structured variant to the shared family renderer: that took an integrated weapon's forms out of its card
// (the chips the owner approved were gone) and drew a stowed weapon's form as a button of its own (lead's screenshot
// check on VARIANTS26F7).
const BI_SHOU = "action:typed.a1b2c3d4.weapon.bi_shou";
const STAFF = "action:typed.e5f6a7b8.weapon.gun";
const DRAW = "The Gun (Staff) is stowed. Draw it before you attack with it.";

const attackRow = (source, label, detail, variant) => ({
  id: "act:" + source, label, group: "attacks", kind: "combat", economy: "ACTION",
  combat: {source_definition_id: source}, detail, ...(variant ? {variant} : {}),
});
const form = (baseKey, baseLabel, axis, key, label) => ({
  base_key: baseKey, base_label: baseLabel, choices: [{axis, key, label, costs: []}],
});
const IN_HAND = [
  attackRow(BI_SHOU, "Bi Shou", {to_hit: "+4", damage: "1d4+2", range: "5 ft"}),
  attackRow(BI_SHOU + "#thrown", "Bi Shou thrown", {to_hit: "+4", damage: "1d4+2", range: "60 ft"},
    form(BI_SHOU, "Bi Shou", "delivery", "thrown", "Thrown")),
  attackRow(BI_SHOU + "#integrated_con", "Bi Shou (Constitution)", {to_hit: "+6", damage: "1d4+4", range: "5 ft"},
    form(BI_SHOU, "Bi Shou", "ability", "constitution", "Constitution")),
  attackRow(BI_SHOU + "#integrated_dex", "Bi Shou (Dexterity)", {to_hit: "+5", damage: "1d4+3", range: "5 ft"},
    form(BI_SHOU, "Bi Shou", "ability", "dexterity", "Dexterity")),
];
const STOWED = [
  attackRow(STAFF, "Gun (Staff)", {to_hit: "+3", damage: "1d6+1", range: "5 ft"}),
  attackRow(STAFF + "#integrated_con", "Gun (Staff) (Constitution)", {to_hit: "+5", damage: "1d6+3", range: "5 ft"},
    form(STAFF, "Gun (Staff)", "ability", "constitution", "Constitution")),
];

function attacksSection(ui, sheetRows, offered) {
  const groups = new Map(offered.map(row => [row.combat.source_definition_id,
    {source_definition_id: row.combat.source_definition_id}]));
  const bar = ui.drawSections({buttons: sheetRows, layout: {}}, {actor_id: "actor:lingfeng", actions: offered},
    {id: "actor:lingfeng"}, ui.app, groups, new Set(), new Set());
  return bar.children.find(group => group.querySelector("h3")?.textContent === "Attacks");
}

test("an integrated weapon keeps one card, its variants are chips, and a stowed weapon is not offered", async () => {
  const ui = harness({reason: row => (row.id.includes(".weapon.gun") ? DRAW : "")});
  const attacks = attacksSection(ui, [...IN_HAND, ...STOWED], IN_HAND);
  assert.ok(attacks, "the Attacks section is drawn");
  const cards = attacks.querySelectorAll(".tt-attack-group");
  assert.deepEqual(cards.map(card => card.dataset.attackGroup).sort(), [BI_SHOU, STAFF].sort(),
    "one card per weapon, not one card per variant");
  const flat = attacks.querySelectorAll(".tt-action-card").filter(card => !card.classList.contains("tt-attack-group"));
  assert.deepEqual(flat.map(card => card.querySelector("b").textContent), [],
    "no attack here is a bare button: a variant is a chip under its weapon, never a button of its own");

  const biShou = cards.find(card => card.dataset.attackGroup === BI_SHOU);
  const chips = chipButtons(biShou);
  const name = chip => chip.querySelector("b").textContent;  // these are the bar's real buttons, not the harness stub
  assert.deepEqual(chips.map(name).sort(), ["Constitution", "Dexterity", "Melee", "Thrown"],
    "the weapon's four forms are four chips on its one card, named as the sheet names them");
  await chips.find(chip => name(chip) === "Constitution").listeners.click();  // the press the bar bound to it
  assert.equal(ui.pressed.at(-1).id, "act:" + BI_SHOU + "#integrated_con",
    "the chip presses the compiled button of the form it stands for");

  const gun = cards.find(card => card.dataset.attackGroup === STAFF);
  const stowed = chipButtons(gun);
  assert.equal(stowed.length, 2, "the stowed weapon keeps its own card, forms and all");
  assert.ok(stowed.every(chip => chip.disabled), "but nothing on it can be pressed: the weapon is not in hand");
  assert.ok(stowed.every(chip => String(chip.dataset.tip).includes(DRAW)), "and each chip says why");
});

// ------------------------------------------------------------------ TBREFUSE1: a refused press says why, once
// The table answers every press with runButton's result. A refusal (an AI-controlled fighter, a busy window, a stale
// menu) is shown as one error toast by pressButton, the one place a player's press runs. Before, three bar callers
// dropped the result, so the player saw nothing; the pop-out sheet's channel handler was the only caller that showed it.
const REFUSED = "Lingfeng is under the table's control right now.";
const settle = () => new Promise(resolve => setImmediate(resolve));
const CLAW = suffix => ({
  id: "act:action:typed.test.weapon.claw" + suffix, label: "Claw attack", group: "attacks", kind: "combat", economy: "ACTION",
  combat: {source_definition_id: "action:typed.test.weapon.claw" + suffix},
  detail: {to_hit: "+5", attacks: 2, damage: "1d8+2", range: "5 ft"},
});
const BLESS = {
  id: "act:action:typed.test.bless", label: "Bless", group: "actions", kind: "combat", economy: "ACTION",
  combat: {source_definition_id: "action:typed.test.bless"}, detail: {},
};

test("a bar button the table refuses says why, once", async () => {
  const ui = harness({buttons: [BLESS], refusal: () => REFUSED});
  const groups = new Map([[BLESS.combat.source_definition_id, {source_definition_id: BLESS.combat.source_definition_id}]]);
  const bar = ui.drawSections({buttons: [BLESS], layout: {}}, {actor_id: "actor:longtongling", actions: [BLESS]},
    {id: "actor:longtongling"}, ui.app, groups, new Set(), new Set());
  const button = bar.querySelectorAll(".tt-btn").find(node => node.label === "Bless");
  assert.ok(button, "the action is drawn on the bar");
  button.listeners.click();
  await settle();
  assert.deepEqual(ui.pressed.map(entry => entry.id), [BLESS.id], "the press reached the table");
  assert.deepEqual(ui.toasts, [{message: REFUSED, error: true}], "the refusal is shown once, as an error");
});

test("an attack chip the table refuses says why, once", async () => {
  const ui = harness({refusal: row => (row.id.includes("#thrown") ? REFUSED : null)});
  const javelin = groupAttackRows(rows).map(weapon => ui.card(weapon)).find(card => card.dataset.attackGroup === JAVELIN);
  const thrown = chipButtons(javelin).find(chip => chip.label === "Thrown");
  thrown.onClick();
  await settle();
  assert.equal(ui.pressed.length, 1, "the press reached the table");
  assert.deepEqual(ui.toasts, [{message: REFUSED, error: true}], "the chip shows the refusal once");
});

test("an answer to the attack question that the table refuses says why, once", async () => {
  const clawRows = [CLAW(""), CLAW(".attack_action_begin"), CLAW(".attack_action_rest")];
  const ui = harness({buttons: clawRows, refusal: () => REFUSED});
  const [weapon] = groupAttackRows(clawRows);
  chipButtons(ui.card(weapon))[0].onClick();
  const all = ui.card(weapon).querySelector(".tt-attack-ask").querySelectorAll(".tt-btn").find(button => button.label === "All 2 on this");
  all.onClick();
  await settle();
  assert.equal(ui.pressed.length, 1, "the answer reached the table");
  assert.deepEqual(ui.toasts, [{message: REFUSED, error: true}], "the question's answer shows the refusal once");
});

test("a refused press from the pop-out sheet adds exactly one error toast", async () => {
  const ui = harness({buttons: [BLESS], refusal: () => REFUSED});
  const posted = [];
  let receive = null;
  ui.app.channel = {postMessage: message => posted.push(message), addEventListener: (_type, fn) => { receive = fn; }};
  ui.run(extract("app.channel?.addEventListener(\"message\", async event => {", "\n});") + "\n});");
  await receive({data: {type: "button", button: BLESS, actor_id: "actor:longtongling", button_id: BLESS.id}});
  assert.deepEqual(ui.toasts, [{message: REFUSED, error: true}], "one error toast, not two");
  assert.deepEqual(posted, [{type: "result", actor_id: "actor:longtongling", button_id: BLESS.id, ok: false, message: REFUSED}],
    "the sheet still hears the refusal");
});

