// No browser: exercise the shipped library DOM builder with complete owner rules.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {test} from "node:test";

const root = new URL("../static/tabletop/", import.meta.url);
const load = async name => import(new URL(name, root));
const {renderRules, cleanRules, ruleSummary} = await load("rules.js");
const {layoutText} = await load("presentation.js");
const printed = JSON.parse(readFileSync(new URL("../authority/typed_mechanics/rules_text.json", import.meta.url), "utf8"));
const ids = ["tianxia.path.body_refining.feature.core_tempering_expression", "TAL_UNMAKING_BLACK_TRACE"];
// Standalone client expectations are independent of server formatting. The
// Python service regression also pipes its real response through this renderer.
const entries = process.argv.includes("--service") ? JSON.parse(readFileSync(0, "utf8")) :
  ids.map(id => ({id, name: id === ids[0] ? "Core Tempering Expression" : "Black Trace",
    text: printed[id], hover: {text: printed[id]}, status: "info"}));
function h(tag, attrs, ...kids) {
  return {tag, attrs, kids: kids.flat(Infinity).filter(k => k != null && k !== false), append(...nodes) {this.kids.push(...nodes);},
    get textContent() {return this.kids.map(k => typeof k === "string" ? k : k.textContent).join("");}};
}
function find(node, tag) {
  return [node, ...node.kids.flatMap(k => typeof k === "string" ? [] : find(k, tag))].filter(n => n.tag === tag);
}
const source = readFileSync(new URL("sheet.js", root), "utf8");
const context = vm.createContext({h, renderRules, cleanRules, ruleSummary, layoutText,
  state: {libOpen: new Set(ids), byId: new Map()}, LIB_STATUS: {info: {cls: "", title: "", label: "Rules"}}});
vm.runInContext(source.slice(source.indexOf("function inlineMd("), source.indexOf("function renderLibrary()")), context);

for (const entry of entries) test(`library retains sections and associated rules: ${entry.name}`, () => {
  const node = context.libCard(entry, "");
  const ruleNode = find(node, "div").find(n => n.attrs?.class === "lib-text");
  assert.ok(ruleNode);
  const headings = find(ruleNode, "p").filter(n => n.attrs?.class === "lib-h").map(n => n.textContent);
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
      const at = ruleNode.kids.findIndex(n => n.attrs?.class === "lib-h" && n.textContent === heading);
      let end = at + 1;
      while (end < ruleNode.kids.length && ruleNode.kids[end].attrs?.class !== "lib-h") end++;
      assert.ok(at >= 0);
      assert.ok(ruleNode.kids.slice(at + 1, end).map(n => n.textContent).join("\n").includes(rule), heading);
    }
    assert.equal(find(ruleNode, "ul").length, 4);
    assert.equal(find(ruleNode, "li").length, 12);
  } else {
    const tables = find(ruleNode, "table");
    assert.equal(tables.length, 2);
    assert.deepEqual(tables.map(t => find(t, "th").map(n => n.textContent)),
      [["Realm", "Safe Black Trace Damage"], ["Realm", "Unbound Trace Damage"]]);
    for (const [table, dice] of [[tables[0], [1, 2, 3, 4]], [tables[1], [2, 4, 6, 8]]]) {
      assert.deepEqual(find(table, "td").map(n => n.textContent),
        ["Mortal", "Foundation", "Core Formation", "Nascent Soul"].flatMap((realm, i) =>
          [realm, `${dice[i]}d10 + your Unmaking key ability modifier`]));
    }
    const heading = ruleNode.kids.findIndex(n => n.textContent === "Unbound Trace");
    assert.ok(heading > ruleNode.kids.indexOf(tables[0]) && heading < ruleNode.kids.indexOf(tables[1]));
    assert.deepEqual(find(ruleNode, "li").map(n => n.textContent), [
      "gain 1 Black Vein Strain;", "take Ruin self-damage equal to 1d6 + your Proficiency Bonus;",
      "one suitable focus, needle, talisman, weapon, or External Channel gains 1 Crack."]);
  }
});
