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
    actor: {match_id: "match:test"}, sheet: {actor_id: "actor:test"},
    byId: new Map(attackRows.map(row => [row.id, row])), attackAsk: null, attackGroups: null, attackSpent: new Map(),
  };
  const context = vm.createContext({
    state, Node: FakeElement, WeakMap, Map, Set, unavailableRowsHidden,
    document: {
      createElement: tag => new FakeElement(tag),
      querySelectorAll: selector => (String(selector).startsWith("#sheet") ? sheet.querySelectorAll("[data-button-id]") : sheet.querySelectorAll(selector)),
    },
    $: id => (id === "action-list" ? list : sheet),
    markActive() {}, activate() {},
    presetQueue: {acceptRefresh() {}}, helloTimer: 0, clearTimeout() {}, toast() {},
    refreshActionRowsInPlace: () => vm.runInContext("applyLegal()", context), renderLive() {},
    localStorage: {getItem: () => null, setItem() {}},
    // The rest of the sheet's helpers are not what this test is about: the rows they draw are stubbed, and the hover
    // card is flattened to the text it would show, so the server's reason can be read off the chip.
    describe: () => "",
    plainRules: text => text || "",
    actionHoverText: (row, options = {}) => [options.rules, ...(options.extra || []), options.note].filter(Boolean).join("\n\n"),
    actionTipCard: () => null,
    additionalRuleText: () => "",
    modifierRowFor: buttonId => ({button_id: buttonId, on: buttonId === "rider:on"}),
    actionRow: row => {
      const box = new FakeElement("div");
      if (row.id === "rider:off") {
        box.className = "arow arow-variant arow-rider";
        const button = new FakeElement("button"); button.dataset.buttonId = row.id; box.append(button);
      }
      return box;
    },
    readAttack, attackGroupView, groupAttackRows,
  });
  vm.runInContext([
    "const isCombatish = b => b && (b.kind === 'combat' || b.kind === 'combo');",
    extract("function h(tag, attrs, ...kids)", "function icon("),
    extract("// ------------------------------------------------------------------ ATTACKLIST1: attacks grouped by weapon", "// Hover text (owner 2026-09-25)"),
    extract("function applyLegal()", "function economyPips("),
    extract("function onMessage(msg)", "// ------------------------------------------------------------------ activation"),
  ].join("\n"), context);
  vm.runInContext(extract('$("sheet").addEventListener("click", (event) => {', '  document.addEventListener("change", event => {'), context);
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
  const ui = harness({legal: [...ids].filter(id => !thrown.includes(id)), reasons: Object.fromEntries(thrown.map(id => [id, REASON])), showUnavailable: true});
  const nodes = ui.draw();
  const javelin = findGroup(nodes, JAVELIN);
  const chip = buttons(javelin).find(entry => entry.classList.contains("is-illegal"));
  assert.ok(chip, "the refused mode is greyed");
  assert.equal(chip.hidden, false, "show unavailable displays the refused mode");
  assert.match(chip.getAttribute("aria-label"), /not available/);
  assert.match(String(chip.dataset.tip), new RegExp(REASON.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  // The weapon's other modes stay usable.
  assert.ok(buttons(javelin).some(entry => entry.classList.contains("is-legal")));
  const css = fs.readFileSync(new URL("../static/tabletop/sheet.css", import.meta.url), "utf8");
  assert.match(css, /\.attack-chip\.is-legal\s*\{[^}]*border-color:\s*var\(--legal\)[^}]*box-shadow:[^}]*var\(--legal\)/, "offered chips have the legal highlight");
  // A refused row that is not a chip is still hidden by the Show unavailable preference, exactly as before.
  assert.equal(ui.list.querySelectorAll("[data-button-id]").length, 13, "no chip was removed from the list");
});

test("two attacks ask all-on-this or choose-each, and the answers are the compiled rows", () => {
  const claw = (suffix, attacks) => ({
    id: "act:action:typed.test.weapon.claw" + suffix, label: "Claw attack", group: "attacks", kind: "combat", economy: "ACTION",
    combat: {source_definition_id: "action:typed.test.weapon.claw" + suffix},
    detail: {to_hit: "+5", attacks, damage: "1d8+2", range: "5 ft"},
  });
  const refused = claw("#thrown", 2);
  const rider = {id: "rider:off", parent: "act:action:typed.test.weapon.claw"};
  const clawRows = [claw("", 2), claw(".attack_action_begin", 2), claw(".attack_action_rest", 2), refused, rider];
  const ui = harness({rows: clawRows, legal: clawRows.filter(row => row !== refused).map(row => row.id), reasons: {[refused.id]: REASON}});
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
  assert.ok(buttons(group)[0].classList.contains("is-legal"), "repainting the question preserves legality");
  const assertHiddenPreferences = phase => {
    const chips = group.querySelectorAll("[data-attack-chip]");
    assert.ok(chips.some(chip => chip.classList.contains("is-legal") && !chip.hidden), `${phase}: offered chip stays visible`);
    const refusedChip = chips.find(chip => chip.dataset.buttonId === refused.id);
    assert.ok(refusedChip.classList.contains("is-illegal") && refusedChip.hidden, `${phase}: refused chip is hidden`);
    assert.equal(group.querySelector(".arow-rider").hidden, true, `${phase}: OFF rider is hidden`);
  };
  ui.run("attackChipClick")(buttons(group)[0]);
  ui.sheet.listeners.click({target: group.querySelector("[data-attack-ask]")});
  assert.equal(group.querySelector(".attack-ask"), null);
  assert.ok(buttons(group)[0].classList.contains("is-legal"), "Cancel preserves the offered chip highlight");
  assertHiddenPreferences("Cancel");
  ui.run("attackChipClick")(buttons(group)[0]);
  ui.sheet.listeners.click({target: group.querySelector("[data-attack-answer]")});
  assert.ok(buttons(group)[0].classList.contains("is-legal"), "answering preserves the offered chip highlight");
  assertHiddenPreferences("answer");
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

test("unavailable attacks and empty cards follow the toggle, while offered chips remain", () => {
  const refused = rows.filter(row => row.id.includes("biao_qiang")).map(row => row.id);
  const ui = harness({legal: [...ids].filter(id => !refused.includes(id)), reasons: Object.fromEntries(refused.map(id => [id, REASON]))});
  const nodes = ui.draw();
  const card = findGroup(nodes, JAVELIN);
  assert.ok(buttons(card).every(chip => chip.hidden));
  assert.equal(card.hidden, true);
  assert.ok(buttons(nodes[0]).some(chip => chip.classList.contains("is-legal") && !chip.hidden));
  const variant = new FakeElement("details"); variant.className = "attack-group action-variant-group";
  const chip = new FakeElement("button"); chip.dataset.buttonId = refused[0]; variant.append(chip); ui.list.append(variant);
  ui.run("applyLegal()");
  assert.equal(variant.hidden, true);
  ui.list.querySelector(".unavailable-toggle").listeners.click();
  assert.equal(card.hidden, false);
  assert.equal(variant.hidden, false);
  assert.equal(chip.hidden, false);
  assert.ok(chip.classList.contains("is-illegal"));
  assert.match(chip.dataset.tip, /no javelin/);
});

test("rider preference hides only off riders and persists", () => {
  const ui = harness(); ui.draw();
  const rider = id => { const box = new FakeElement("div"); box.className = "arow arow-variant arow-rider"; const button = new FakeElement("button"); button.dataset.buttonId = id; box.append(button, new FakeElement("select")); ui.list.append(box); return box; };
  const off = rider("rider:off"), on = rider("rider:on");
  ui.run("applyLegal()");
  assert.equal(off.hidden, true); assert.equal(on.hidden, false);
  const toggle = ui.list.querySelector(".rider-toggle");
  assert.match(toggle.textContent, /Show rider options \(2\)/);
  toggle.listeners.click();
  assert.equal(off.hidden, false); assert.equal(on.hidden, false);
});

test("actor messages and later repaints keep offered and refused attacks marked", () => {
  const ui = harness({showUnavailable: true}); ui.state.connected = null; ui.draw();
  const refused = rows.filter(row => row.id.includes("#thrown")).map(row => row.id);
  const message = {type: "actor", actor_id: "actor:test", match_id: "match:test", legal_button_ids: [...ids].filter(id => !refused.includes(id)), unavailable_reasons: Object.fromEntries(refused.map(id => [id, REASON]))};
  ui.run("onMessage")(message);
  const check = () => { const chips = buttons(findGroup(ui.list.children, JAVELIN)); assert.ok(chips.some(c => c.classList.contains("is-legal"))); assert.ok(chips.some(c => c.classList.contains("is-illegal") && c.dataset.tip.includes(REASON))); };
  check(); ui.draw(); check(); ui.run("onMessage")(message); check();
});
