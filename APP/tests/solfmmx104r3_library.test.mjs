// No browser: exercise the shipped library DOM builder with complete owner rules.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {test} from "node:test";
import {installDOM} from "./objects_dom_stub.mjs";

const root = new URL("../static/tabletop/", import.meta.url);
const load = async name => import(new URL(name, root));
const {renderRules, cleanRules, ruleSummary, renderTipCard, actionCardModel} = await load("rules.js");
const {layoutText} = await load("presentation.js");
const printed = JSON.parse(readFileSync(new URL("../authority/typed_mechanics/rules_text.json", import.meta.url), "utf8"));
const ids = ["tianxia.path.body_refining.feature.core_tempering_expression", "TAL_UNMAKING_BLACK_TRACE"];
// Standalone client expectations are independent of server formatting. The
// Python service regression also pipes its real response through this renderer.
const entries = process.argv.includes("--service") ? JSON.parse(readFileSync(0, "utf8")) :
  ids.map(id => ({id, name: id === ids[0] ? "Core Tempering Expression" : "Black Trace",
    text: printed[id], hover: {text: printed[id]}, status: "info"}));
const document = installDOM("<body></body>");
function h(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value != null && value !== false) node.setAttribute(key, value);
  }
  node.append(...kids.flat(Infinity).filter(k => k != null && k !== false));
  return node;
}
// The shared stub stores each node's own text separately from its descendants.
const textOf = node => node.textContent + (node.childNodes || []).map(textOf).join("");
const find = (node, selector) => node.querySelectorAll(selector);
const source = readFileSync(new URL("sheet.js", root), "utf8");
const context = vm.createContext({document, h, renderRules, cleanRules, ruleSummary, layoutText, renderTipCard, actionCardModel,
  state: {libOpen: new Set(ids), byId: new Map(), libPick: new Map()}, LIB_STATUS: {info: {cls: "", title: "", label: "Rules"}}});
vm.runInContext(source.slice(source.indexOf("function inlineMd("), source.indexOf("function renderLibrary()")), context);

for (const entry of entries) test(`library retains sections and associated rules: ${entry.name}`, () => {
  const node = context.libCard(entry, "");
  if (process.argv.includes("--service")) {
    const card = entry.hover.player_card;
    assert.ok(card);
    assert.equal(layoutText(entry.hover), card.text);
    const rendered = node.querySelector(".player-card");
    assert.ok(rendered);
    const html = rendered.parentNode.innerHTML;
    assert.equal(html, card.html);
    // The shared DOM keeps innerHTML but does not parse its text nodes.
    // Compare the visible overview, excluding the title and collapsed Rules.
    const overview = html.split("</h3>")[1].split("<details>")[0]
      .replace(/<\/(?:p|h4|li)>/g, " ").replace(/<[^>]*>/g, "")
      .replace(/&(?:amp|lt|gt|quot|#x27|#39);/g, entity =>
        ({"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#x27;": "'", "&#39;": "'"})[entity]);
    const normalize = text => text.replace(/^\s*-\s+/gm, "").replace(/\s+/g, " ").trim();
    assert.equal(normalize(overview), normalize(card.text));
    return;
  }
  const ruleNode = node.querySelector(".lib-text");
  assert.ok(ruleNode);
  const headings = find(ruleNode, ".lib-h").map(textOf);
  const expectedHeadings = printed[entry.id].split("\n").filter(l => /^#+ /.test(l)).map(l => l.replace(/^#+ /, ""));
  assert.deepEqual(headings, expectedHeadings);
  assert.equal(layoutText(entry.hover), printed[entry.id].trim());
  if (entry.id === ids[0]) {
    // Assert association within each option, rather than just presence anywhere.
    for (const [heading, rule] of [
      ["Golden Bell Circulation", "Gain +2 AC."],
      ["Perfected Golden Bell - CL17", "Stamina Guard uses d12s instead of d10s."],
      ["Blood-Furnace Circulation", "regain Hit Points equal to your Proficiency Bonus."],
      ["Perfected Blood Furnace - CL17", "2 x Proficiency Bonus"],
      ["Mountain-Rending Pulse", "1d8"],
      ["Perfected Mountain-Rending Pulse - CL17", "2d8"],
    ]) {
      const at = ruleNode.childNodes.findIndex(n => n.classList?.contains("lib-h") && textOf(n) === heading);
      let end = at + 1;
      while (end < ruleNode.childNodes.length && !ruleNode.childNodes[end].classList?.contains("lib-h")) end++;
      assert.ok(at >= 0);
      assert.ok(ruleNode.childNodes.slice(at + 1, end).map(textOf).join("\n").includes(rule), heading);
    }
    assert.equal(find(ruleNode, "ul").length, 4);
    assert.equal(find(ruleNode, "li").length, 12);
  } else {
    const tables = find(ruleNode, "table");
    assert.equal(tables.length, 2);
    assert.deepEqual(tables.map(t => find(t, "th").map(textOf)),
      [["Realm", "Safe Black Trace Damage"], ["Realm", "Unbound Trace Damage"]]);
    for (const [table, dice] of [[tables[0], [1, 2, 3, 4]], [tables[1], [2, 4, 6, 8]]]) {
      assert.deepEqual(find(table, "td").map(textOf),
        ["Mortal", "Foundation", "Core Formation", "Nascent Soul"].flatMap((realm, i) =>
          [realm, `${dice[i]}d10 + your Unmaking key ability modifier`]));
    }
    const heading = ruleNode.childNodes.findIndex(n => textOf(n) === "Unbound Trace");
    assert.ok(heading > ruleNode.childNodes.indexOf(tables[0]) && heading < ruleNode.childNodes.indexOf(tables[1]));
    assert.deepEqual(find(ruleNode, "li").map(textOf), [
      "gain 1 Black Vein Strain;", "take Ruin self-damage equal to 1d6 + your Proficiency Bonus;",
      "one suitable focus, needle, talisman, weapon, or External Channel gains 1 Crack."]);
    assert.ok(ruleNode.childNodes.some(n => n.tagName === "P" && textOf(n) === "You may Overdraw when Unbound Trace hits."));
  }
});
