// No browser: real sheet-service payload through the shipped library DOM builder.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import {test} from "node:test";
import {readStdinPayload} from "./node_stdin.mjs";

const root = new URL("../static/tabletop/", import.meta.url);
const load = async name => import(new URL(name, root));
const {renderRules, cleanRules, ruleSummary} = await load("rules.js");
const {layoutText} = await load("presentation.js");
const printed = JSON.parse(readFileSync(new URL("../authority/typed_mechanics/rules_text.json", import.meta.url), "utf8"));
const rawEntry = (await readStdinPayload()).trim();
const entry = rawEntry ? JSON.parse(rawEntry) : {id: "", name: "no provided entry"};
function h(tag, attrs, ...kids) {
  return {tag, attrs, kids: kids.flat(Infinity).filter(k => k != null && k !== false), append(...nodes) {this.kids.push(...nodes);},
    get textContent() {return this.kids.map(k => typeof k === "string" ? k : k.textContent).join("");}};
}
function find(node, tag) {
  return [node, ...node.kids.flatMap(k => typeof k === "string" ? [] : find(k, tag))].filter(n => n.tag === tag);
}
const source = readFileSync(new URL("sheet.js", root), "utf8");
const context = vm.createContext({h, renderRules, cleanRules, ruleSummary, layoutText,
  state: {libOpen: new Set([entry.id]), byId: new Map()}, LIB_STATUS: {info: {cls: "", title: "", label: "Rules"}}});
vm.runInContext(source.slice(source.indexOf("function inlineMd("), source.indexOf("function renderLibrary()")), context);

test(`expanded library distinguishes both printed clocks: ${entry.name}`, {skip: !rawEntry}, () => {
  assert.ok(entry.id, "Supplied library entry must include an id");
  const casting = printed[entry.id].match(/^Time: (.+)$/m)[1];
  const duration = printed[entry.id].match(/^Duration: (.+)$/m)[1];
  // Check both complete text and structured-field fallback in the shared reader.
  for (const hover of [entry.hover, {...entry.hover, text: ""}]) {
    const lines = layoutText(hover).split("\n");
    assert.deepEqual(lines.filter(l => l.startsWith("Casting Time:")), [`Casting Time: ${casting}`]);
    assert.deepEqual(lines.filter(l => l.startsWith("Duration:")), [`Duration: ${duration}`]);
  }
  const node = context.libCard(entry, "");
  const ruleNode = find(node, "div").find(n => n.attrs?.class === "lib-text");
  assert.ok(ruleNode);
  const paragraphs = find(ruleNode, "p").map(n => n.textContent);
  assert.ok(paragraphs.includes(`Casting Time: ${casting}`));
  assert.deepEqual(paragraphs.filter(p => p.startsWith("Duration:")), [`Duration: ${duration}`]);
});
