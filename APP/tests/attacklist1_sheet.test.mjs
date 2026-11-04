// ATTACKLIST1: the pop-out sheet's ATTACKS section, drawn from the real sheet.js, against the real compiled rows of a
// Long Tongling (see attacklist1_groups.test.mjs). Three things the owner asked for are checked here and nowhere else:
//   - one row per weapon, its modes and add-ons as chips under it, every chip pressing a compiled button;
//   - a mode the table refuses stays in its weapon, greyed, with the table's own reason on hover (never hidden);
//   - with more than one attack in the Attack action the first click asks "all of them on this, or choose each?".
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {spawnSync} from "node:child_process";
import {unavailableRowsHidden} from "../static/tabletop/sheet-polish.js";
import {FakeElement} from "./attacklist1_dom.mjs";
import {attackGroupView, groupAttackRows, readAttack} from "../static/tabletop/attack-groups.js";

const sheetSource = fs.readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");
const rows = JSON.parse(fs.readFileSync(new URL("./fixtures/attacklist1_longtongling_typed_rows.json", import.meta.url), "utf8"));
const ids = new Set(rows.map(row => row.id));
const JAVELIN = "action:typed.f11dfb35d6.weapon.biao_qiang";
const REASON = "You have no javelin left to throw. Pick one up first.";

test("sheet and table modules parse as complete ES modules", () => {
  for (const file of ["static/tabletop/sheet.js", "static/tabletop/tabletop.js"]) {
    const result = spawnSync("node", ["--check", file], {cwd: new URL("..", import.meta.url), encoding: "utf8"});
    assert.equal(result.status, 0, `${file} must parse: ${result.stderr}`);
  }
});

function extract(start, end) {
  const from = sheetSource.indexOf(start);
  const to = sheetSource.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, "missing source boundary: " + start);
  return sheetSource.slice(from, to);
}

function harness({rows: attackRows = rows, legal = null, reasons = {}, showUnavailable = false} = {}) {
  const list = new FakeElement("div");
  list.setAttribute("id", "action-list");
  const sheet = new FakeElement("div");
  sheet.setAttribute("id", "sheet");
  sheet.append(list);
  const state = {
    connected: true, legal: new Set(legal || attackRows.map(row => row.id)), unavailable: reasons, showUnavailable,
    actor: {match_id: "match:test"},
    byId: new Map(attackRows.map(row => [row.id, row])), attackAsk: null, attackGroups: null, attackSpent: new Map(),
  };
  const context = vm.createContext({
    state, Node: FakeElement, WeakMap, Map, Set, unavailableRowsHidden,
    document: {
      createElement: tag => new FakeElement(tag),
      querySelectorAll: selector => (String(selector).startsWith("#sheet") ? sheet.querySelectorAll("[data-button-id]") : sheet.querySelectorAll(selector)),
    },
    $: id => (id === "action-list" ? list : sheet),
    markActive() {},
    localStorage: {getItem: () => null, setItem() {}},
    // The rest of the sheet's helpers are not what this test is about: the rows they draw are stubbed, and the hover
    // card is flattened to the text it would show, so the server's reason can be read off the chip.
    describe: () => "",
    plainRules: text => text || "",
    actionHoverText: (row, options = {}) => [options.rules, ...(options.extra || []), options.note].filter(Boolean).join("\n\n"),
    actionTipCard: () => null,
    additionalRuleText: () => "",
    modifierRowFor: buttonId => ({button_id: buttonId, on: false}),
    actionRow: () => new FakeElement("div"),
    readAttack, attackGroupView, groupAttackRows,
  });
  vm.runInContext([
    "const isCombatish = b => b && (b.kind === 'combat' || b.kind === 'combo');",
    extract("function h(tag, attrs, ...kids)", "function icon("),
    extract("// ------------------------------------------------------------------ ATTACKLIST1: attacks grouped by weapon", "// Hover text (owner 2026-09-25)"),
    extract("function applyLegal()", "function economyPips("),
  ].join("\n"), context);
  const run = code => vm.runInContext(code, context);
  const groups = () => run("attackSectionNodes(rows)");
  return {
    state, list, sheet, run,
    draw: () => { const nodes = run("attackSectionNodes")(attackRows); list.replaceChildren(...nodes); run("applyLegal")(); return nodes; },
    groups,
  };
}

const findGroup = (nodes, key) => nodes.find(node => node.dataset.attackGroup === key);
const buttons = node => node.querySelectorAll("[data-button-id]");

test("the ATTACKS section draws one row per weapon with its modes as chips", () => {
  const ui = harness();
  const nodes = ui.draw();
  assert.equal(nodes.length, 4);
  assert.deepEqual(nodes.map(node => node.querySelector(".attack-name").textContent),
    ["Unarmed Strike", "Biao Qiang (Javelin)", "Jian (Straight Sword)", "Xi Jian (Rapier)"]);
  const javelin = findGroup(nodes, JAVELIN);
  const chips = buttons(javelin);
  assert.deepEqual(chips.map(chip => chip.querySelector(".attack-chip-label").textContent),
    ["Melee", "Thrown", "Batter", "Batter (thrown)", "+ Brutal Strike", "+ Brutal Strike"]);
  assert.equal(javelin.querySelector(".attack-copies").textContent, "\u00d74");
  assert.ok(chips.every(chip => ids.has(chip.dataset.buttonId)), "every chip presses a compiled button");
  // The flat rows are gone: no chip repeats an attack as its own NAME row, and the mode note is no longer a row family.
  assert.ok(!chips.some(chip => chip.textContent.includes("choose the rest")));
  assert.equal(buttons(ui.list).length, 13);
});

test("a chip the table refuses stays in its weapon, greyed, with the table's own reason", () => {
  const thrown = rows.filter(row => row.id.includes("#thrown")).map(row => row.id);
  const ui = harness({legal: [...ids].filter(id => !thrown.includes(id)), reasons: Object.fromEntries(thrown.map(id => [id, REASON])), showUnavailable: false});
  const nodes = ui.draw();
  const javelin = findGroup(nodes, JAVELIN);
  const chip = buttons(javelin).find(entry => entry.classList.contains("is-illegal"));
  assert.ok(chip, "the refused mode is greyed");
  assert.equal(chip.hidden, false, "a refused mode is never hidden: the weapon would lose a mode");
  assert.match(chip.getAttribute("aria-label"), /not available/);
  assert.match(String(chip.dataset.tip), new RegExp(REASON.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  // The weapon's other modes stay usable.
  assert.ok(buttons(javelin).some(entry => entry.classList.contains("is-legal")));
  // A refused row that is not a chip is still hidden by the Show unavailable preference, exactly as before.
  assert.equal(ui.list.querySelectorAll("[data-button-id]").length, 13, "no chip was removed from the list");
});

test("two attacks ask all-on-this or choose-each, and the answers are the compiled rows", () => {
  const claw = (suffix, attacks) => ({
    id: "act:action:typed.test.weapon.claw" + suffix, label: "Claw attack", group: "attacks", kind: "combat", economy: "ACTION",
    combat: {source_definition_id: "action:typed.test.weapon.claw" + suffix},
    detail: {to_hit: "+5", attacks, damage: "1d8+2", range: "5 ft"},
  });
  const clawRows = [claw("", 2), claw(".attack_action_begin", 2), claw(".attack_action_rest", 2)];
  const ui = harness({rows: clawRows});
  const nodes = ui.draw();
  const group = nodes[0];
  const chip = buttons(group)[0];
  assert.equal(group.querySelector(".attack-left").textContent, "2 attacks left", "the weapon says how many attacks are left");
  assert.ok(chip.querySelector(".attack-chip-more"), "the chip says it has a question");
  assert.equal(ui.run("attackChipClick")(chip), true, "the first click asks instead of pressing the button");
  assert.equal(ui.state.attackAsk.group, "action:typed.test.weapon.claw");
  const asked = group.querySelector(".attack-ask");
  assert.ok(asked, "the question is drawn in the weapon's own row");
  assert.match(asked.querySelector(".attack-ask-q").textContent, /2 attacks with Claw\. Use them all on this one, or choose each attack\?/);
  const answers = asked.querySelectorAll("[data-button-id]").map(node => node.dataset.buttonId);
  assert.deepEqual(answers, [
    "act:action:typed.test.weapon.claw",
    "act:action:typed.test.weapon.claw.attack_action_begin",
  ]);
  // Each answer is marked so the sheet's own click handler closes the question and presses the row it names.
  assert.deepEqual(asked.querySelectorAll("[data-attack-answer]").map(node => node.dataset.attackAnswer), ["all", "each"]);
  // Asking repaints the row, so the second click is the one a person would actually make: on the live chip.
  const live = buttons(group)[0];
  assert.equal(ui.run("attackChipClick")(live), true, "the same click closes the question again");
  assert.equal(group.querySelector(".attack-ask"), null);
});

test("a weapon with one attack just presses its button", () => {
  const ui = harness();
  const nodes = ui.draw();
  const chip = buttons(nodes[0])[0];
  assert.equal(ui.run("attackChipClick")(chip), false, "one attack never asks; the click goes to the row itself");
  assert.equal(ui.state.attackAsk, null);
});

test("a chip greys itself when the sheet is not connected, and never hides", () => {
  const ui = harness();
  ui.state.connected = false;
  const nodes = ui.draw();
  assert.equal(buttons(findGroup(nodes, JAVELIN)).length, 6);
  assert.ok(buttons(findGroup(nodes, JAVELIN)).every(chip => !chip.hidden));
});
