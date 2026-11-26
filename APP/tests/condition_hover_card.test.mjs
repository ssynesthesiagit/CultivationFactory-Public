// Execute the shipped hover-card renderer in Node; no browser or GUI is launched.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../static/tabletop/board.js", import.meta.url), "utf8");
const css = fs.readFileSync(new URL("../static/tabletop/tabletop.css", import.meta.url), "utf8");
const start = source.indexOf("  function showCard(");
const end = source.indexOf("\n  function setTokens(", start);
assert.ok(start >= 0 && end > start, "hover-card renderer boundaries exist");

for (const [tone, name, color] of [
  ["beneficial", "Dodge", "--cf-buff"],
  ["harmful", "Lethargic", "--cf-debuff"],
  ["neutral", "Concentration", "--muted"],
]) {
  test(`hover card renders ${name} and applicable ${tone} CSS`, () => {
    const card = {node: {style: {}, classList: {toggle() {}}, offsetHeight: 40}};
    const hover = {open({build}) { build(card.node); card.node.hidden = false; }, close() { card.node.hidden = true; }};
    const context = vm.createContext({card, hover, tokens: new Map(), map: {}, displayedCreature: entry => entry.data,
      onRoof: () => false, flightText: () => "", escapeText: text => String(text ?? "").replace(/[&<>\"]/g, ch => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;"})[ch]), window: {innerWidth: 1000, innerHeight: 800}});
    vm.runInContext(source.slice(start, end), context);
    context.entry = {
      data: {name: "Bearer", hp: 10, maxHp: 10, conditions: [{tone, name, text: "Effect < safe & clear"}]},
      node: {getBoundingClientRect: () => ({left: 100, width: 64, top: 200, bottom: 264})},
    };
    vm.runInContext("showCard(entry)", context);
    assert.equal(card.node.hidden, false);
    const rowClass = card.node.innerHTML.match(/class="tt-card-cond-row (is-[^"]+)"/)[1];
    assert.equal(rowClass, `is-${tone}`);
    assert.ok(card.node.innerHTML.includes(`>${name}</span>`));
    assert.ok(card.node.innerHTML.includes("Effect &lt; safe &amp; clear"));
    // Resolve the relevant shipped selectors in source order against the actual rendered classes.
    let declarations = "";
    for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const selectors = match[1].replace(/\/\*[\s\S]*?\*\//g, "").split(",").map(s => s.trim());
      if (selectors.includes(".tt-card-cond") || selectors.includes(`.tt-card-cond-row.${rowClass} .tt-card-cond`)) {
        declarations = match[2];
      }
    }
    assert.ok(declarations.includes(color), `${rowClass} must use ${color}: ${declarations}`);
    if (tone === "beneficial") assert.ok(!declarations.includes("--danger"));
  });
}
