// ATTACKLIST1 (owner-approved, feedback desk FD-18): the ATTACKS list was a flat list of about fifty rows for a
// fighter carrying a Jian, a Xi Jian and four javelins -- every copy of every weapon, in every mode, each javelin row
// also saying "(one attack; choose the rest)" -- so no weapon could be found. The reading that groups them (one row
// per weapon, identical copies merged, modes and add-ons as chips showing only what differs) lives in
// static/tabletop/attack-groups.js and is shared by the table's action bar and the pop-out sheet.
//
// The rows below are the REAL compiled buttons of a CL10 Berserker Long Tongling (Biao Qiang x4, Jian, Xi Jian,
// Brutal Strike, Batter, Heaven-Shaking Batter), captured from combat.factory_compiler.compile_character() +
// combat.tabletop.auto_buttons(). Nothing in this file renames an id: every chip must carry the server's own button.
// The fixture is named *_typed_rows.json because that is what it holds -- typed weapon and talent rows compiled from
// the catalog (weapon definitions, printed talent text), with no owner save, sheet or character-library content -- so
// the public export may ship it (a fixture without "typed" in its name is withheld as uncleared).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {attackGroupView, attackName, chipAsk, chipChoice, groupAttackRows, readAttack} from "../static/tabletop/attack-groups.js";

const rows = JSON.parse(fs.readFileSync(new URL("./fixtures/attacklist1_longtongling_typed_rows.json", import.meta.url), "utf8"));
const ids = new Set(rows.map(row => row.id));
const JAVELIN = "action:typed.f11dfb35d6.weapon.biao_qiang";
const groupOf = (groups, key) => groups.find(group => group.key === key);
const allChips = groups => groups.flatMap(group => attackGroupView(group).chips);

test("forty-one flat rows become four weapons, one row each", () => {
  const groups = groupAttackRows(rows);
  assert.equal(rows.length, 41);
  assert.deepEqual(groups.map(group => group.name), ["Unarmed Strike", "Biao Qiang (Javelin)", "Jian (Straight Sword)", "Xi Jian (Rapier)"]);
  assert.equal(groups.length, 4);
  assert.equal(allChips(groups).length, 13);
});

test("identical copies merge: four javelins are one weapon saying x4", () => {
  const groups = groupAttackRows(rows);
  const javelin = groupOf(groups, JAVELIN);
  assert.equal(javelin.copiesTotal, 4);
  const view = attackGroupView(javelin);
  assert.equal(view.copies, 4);
  assert.equal(view.copiesUsed, 4);
  const melee = view.chips.find(chip => chip.label === "Melee");
  assert.deepEqual(melee.choice.rows.map(row => readAttack(row.id.replace(/^act:/, "")).copy), [1, 2, 3, 4]);
  assert.ok(melee.choice.rows.every(row => row.id.includes("biao_qiang")), "every copy is one of the javelin's own rows");
  // A spent copy stops counting, so the row can say that only some are ready.
  const spentCopies = id => id.includes(".copy2") || id.includes(".copy3") || id.includes(".copy4");
  const partly = attackGroupView(javelin, {usable: row => !spentCopies(row.id)});
  assert.equal(partly.copiesUsed, 1);
  assert.equal(partly.copies, 4);
});

test("a chip is the server's own button: nothing is renamed and nothing is invented", () => {
  const groups = groupAttackRows(rows);
  for (const chip of allChips(groups)) {
    assert.ok(ids.has(chip.rowId), "chip " + chip.label + " must press a compiled button, got " + chip.rowId);
    assert.equal(chip.source, chip.rowId);
  }
  const javelin = attackGroupView(groupOf(groups, JAVELIN));
  const thrown = javelin.chips.find(chip => chip.label === "Thrown");
  assert.equal(thrown.rowId, "act:action:typed.f11dfb35d6.weapon.biao_qiang#thrown");
  const batterThrown = javelin.chips.find(chip => chip.label === "Batter (thrown)");
  assert.equal(batterThrown.rowId, "act:action:typed.f11dfb35d6.weapon.biao_qiang#thrown.batter");
});

test("a chip shows only what differs from the weapon's plain attack", () => {
  const javelin = attackGroupView(groupOf(groupAttackRows(rows), JAVELIN));
  // The chip carries only what the mode changes: the reach always, the numbers only where they differ from the
  // weapon's plain attack (here to-hit and damage are identical, so only the range is printed).
  assert.deepEqual(javelin.chips.map(chip => [chip.label, chip.detail]), [
    ["Melee", "5 ft"],
    ["Thrown", "120 ft"],
    ["Batter", "5 ft"],
    ["Batter (thrown)", "120 ft"],
    ["+ Brutal Strike", "5 ft"],
    ["+ Brutal Strike", "120 ft"],
  ]);
  // Where a number does change, the chip says so.
  const plain = rows.find(row => row.id.endsWith("weapon.biao_qiang"));
  const tossed = rows.find(row => row.id.endsWith("weapon.biao_qiang#thrown"));
  const [harder] = groupAttackRows([plain, {...tossed, detail: {...tossed.detail, to_hit: "+4", damage: "1d4+2"}}]);
  const changed = attackGroupView(harder).chips.find(chip => chip.label === "Thrown");
  assert.match(changed.detail, /\+4 to hit/);
  assert.match(changed.detail, /1d4\+2/);
  assert.ok(javelin.chips.some(chip => chip.kind === "addon"), "Brutal Strike is an add-on chip, not a row of its own");
  assert.ok(!javelin.chips.some(chip => chip.label.includes("choose the rest")), "the note is no longer a row family");
});

test("a mode the table refuses keeps its place in the weapon and says so", () => {
  const groups = groupAttackRows(rows);
  const thrownOnly = row => row.id.includes("#thrown");
  const view = attackGroupView(groupOf(groups, JAVELIN), {usable: row => !thrownOnly(row)});
  const thrown = view.chips.find(chip => chip.label === "Thrown");
  assert.equal(thrown.available, false);
  assert.ok(view.chips.includes(thrown), "a refused mode is greyed in place, never dropped from the weapon");
  // The chip still names the compiled button, so pressing it (or hovering it) reaches the table's own reason.
  assert.equal(thrown.rowId, "act:action:typed.f11dfb35d6.weapon.biao_qiang#thrown");
  assert.equal(view.chips.find(chip => chip.label === "Melee").available, true);
});

test("a talent that changes an attack is not a weapon of its own", () => {
  const toggles = rows.filter(row => row.attack_modifier);
  assert.ok(toggles.length >= 8, "the compiled setting rows are still there for the sheet to draw");
  const groups = groupAttackRows(rows);
  for (const toggle of toggles) {
    assert.ok(!allChips(groups).some(chip => chip.rowId === toggle.id), "a switch is not folded into a weapon's chips");
  }
  assert.equal(groupAttackRows(toggles).length, 0);
});

test("two attacks in the Attack action ask: all on this, or choose each", () => {
  const claw = (suffix, detail) => ({
    id: "act:action:typed.test.weapon.claw" + suffix, label: "Claw attack", group: "attacks", kind: "combat", economy: "ACTION",
    combat: {source_definition_id: "action:typed.test.weapon.claw" + suffix},
    detail: {to_hit: "+5", attacks: 2, damage: "1d8+2", range: "5 ft", ...detail},
  });
  const full = claw("", {});
  const begin = claw(".attack_action_begin", {});
  const rest = claw(".attack_action_rest", {});
  const [group] = groupAttackRows([full, begin, rest]);
  assert.equal(group.name, "Claw");
  const chip = attackGroupView(group).chips[0];
  assert.ok(chip.ask, "two attacks with both answers available must ask");
  assert.equal(chip.ask.attacks, 2);
  assert.equal(chip.ask.allRow.id, full.id, "all on this is the whole Attack action");
  assert.equal(chip.ask.eachRow.id, begin.id, "choose each starts the Attack action");
  // One attack is never asked, and neither is a weapon whose Action is already spent.
  const singleAttack = row => ({...row, detail: {...row.detail, attacks: 1}});
  const [one] = groupAttackRows([singleAttack(full), singleAttack(begin), singleAttack(rest)]);
  assert.equal(chipAsk(chipChoice(one.chips[0])), null);
  const spent = attackGroupView(group, {usable: row => row.id !== full.id});
  assert.equal(spent.chips[0].ask, null, "a spent Action has no all-on-this answer left to offer");
  assert.equal(spent.chips[0].rowId, rest.id, "the click then continues the Attack action that is already under way");
  assert.equal(spent.chips[0].available, true);
});

test("attacks left is a count only when the count is known", () => {
  const claw = suffix => ({
    id: "act:action:typed.test.weapon.claw" + suffix, label: "Claw attack", group: "attacks", kind: "combat",
    combat: {source_definition_id: "action:typed.test.weapon.claw" + suffix},
    detail: {to_hit: "+5", attacks: 2, damage: "1d8+2", range: "5 ft"},
  });
  const full = claw("");
  const begin = claw(".attack_action_begin");
  const rest = claw(".attack_action_rest");
  const [group] = groupAttackRows([full, begin, rest]);
  const fresh = attackGroupView(group);
  assert.equal(fresh.attacks, 2);
  assert.equal(fresh.left, 2);
  assert.equal(fresh.leftKnown, true);
  const started = attackGroupView(group, {usable: row => row.id !== full.id, spent: 1});
  assert.equal(started.left, 1);
  assert.equal(started.leftKnown, true);
  // A surface that did not see the action start cannot know the number, and says so rather than guessing.
  const unknown = attackGroupView(group, {usable: row => row.id !== full.id});
  assert.equal(unknown.leftKnown, false);
});

test("an attack that is not a weapon is grouped by its source", () => {
  const groups = groupAttackRows(rows);
  const unarmed = groupOf(groups, "action:typed.f11dfb35d6.natural.unarmed_strike");
  assert.equal(unarmed.name, "Unarmed Strike");
  assert.equal(unarmed.copiesTotal, 1);
  assert.equal(attackGroupView(unarmed).chips.length, 1);
});

test("a flat label loses its note, never its name", () => {
  const legacy = {id: "act:action:typed.t.weapon.javelin", label: "Biao Qiang (Javelin) attack (one attack; choose the rest)", detail: {range: "5 ft"}};
  assert.equal(attackName(legacy, "action:typed.t.weapon.javelin"), "Biao Qiang (Javelin)");
  const read = readAttack("action:typed.t.weapon.biao_qiang#thrown.batter+2cf802eac0");
  assert.equal(read.family, "action:typed.t.weapon.biao_qiang");
  assert.equal(read.thrown, true);
  assert.equal(read.batter, true);
  assert.equal(read.addOn, "2cf802eac0");
  assert.equal(read.copy, 1);
  assert.equal(readAttack("action:typed.t.weapon.biao_qiang.copy3.attack_action_rest").copy, 3);
});
