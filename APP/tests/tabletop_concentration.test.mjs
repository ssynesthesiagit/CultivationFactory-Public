import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {concentrationCard, concentrationHelp} from "../static/tabletop/concentration.js";
import {tokenHiddenByFog} from "../static/tabletop/vision.js";

test("fighter sheet names current effects and explains concentration on hover or focus", () => {
  const card = concentrationCard({concentration_effects: ["Burning Weapon", "Moon's Pull"]});
  assert.match(card, /Concentrating on Burning Weapon, Moon&#39;s Pull/);
  assert.match(card, /tabindex="0" data-tip="/);
  for (const text of ["one effect at a time", "starting another concentration effect ends it",
    "Cultivation fighters can hold several effects", "DC 10 or half the damage",
    "up to DC 30", "Constitution saving throw", "Failure ends", "incapacitated", "duration runs out"])
    assert.ok(concentrationHelp.includes(text), text);
});

test("ending concentration removes the line; plain names are escaped", () => {
  assert.equal(concentrationCard({}), "");
  assert.equal(concentrationCard({concentration_effects: []}), "");
  const card = concentrationCard({concentration_effects: ['<effect "name">']});
  assert.match(card, /&lt;effect &quot;name&quot;&gt;/);
  assert.ok(!card.includes('<effect'));
});

test("an opponent's sheet uses the same perception boundary as fog", () => {
  const viewer = {entity_id: "viewer"};
  const enemy = {entity_id: "enemy", concentration_effects: ["Darkness"]};
  const render = perception => concentrationCard(enemy,
    !tokenHiddenByFog(enemy, [viewer], perception, true));
  assert.equal(render({viewer: {creatures: []}}), "");
  assert.match(render({viewer: {creatures: ["enemy"]}}), /Concentrating on Darkness/);
  assert.match(concentrationCard(enemy, !tokenHiddenByFog(enemy, [enemy], {}, true)),
    /Concentrating on Darkness/);
  assert.match(concentrationCard(enemy, !tokenHiddenByFog(enemy, [viewer], {}, false)),
    /Concentrating on Darkness/);
});

test("only the fighter inspector wires the indicator; tokens and turn order have no marks", () => {
  const table = readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");
  const board = readFileSync(new URL("../static/tabletop/board.js", import.meta.url), "utf8");
  assert.match(table, /concentrationCard\(actor, !unseenByViewers\(actor\)\)/);
  assert.equal((table.match(/concentrationCard\(actor/g) || []).length, 1);
  assert.ok(!table.includes("concentrationMark"));
  // board.js may mention concentration in prose; what must not exist is a mark or data use there.
  assert.ok(!board.includes("concentrationMark"));
  assert.ok(!board.includes("concentrationCard"));
  assert.ok(!board.includes("concentration_effects"));
});
