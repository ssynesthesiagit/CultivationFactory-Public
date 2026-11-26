// Headless in-process read of the REAL table card renderer, never a browser.
// Keep no alternate rules formatter: drift in sheet.js/rules.js fails loudly.
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {layoutText} from "../static/tabletop/presentation.js";
import {actionCardModel, cleanRules, renderRules, renderTipCard, ruleSummary} from "../static/tabletop/rules.js";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../static/tabletop");
const sheet = fs.readFileSync(path.join(root, "sheet.js"), "utf8");
function section(text, start, end) {
  const at = text.indexOf(start), to = text.indexOf(end, at);
  if (at < 0 || to < 0) throw Error(`Sheet renderer contract missing: ${start}`);
  return text.slice(at, to);
}
class Node {
  constructor(tag, attrs, children) { this.tag = tag; this.attrs = attrs || {}; this.children = children.flat(Infinity).filter(v => v !== null && v !== undefined); }
  append(...nodes) { this.children.push(...nodes); }
  prepend(node) { this.children.unshift(node); }
  setAttribute(key, value) { this.attrs[key] = value; }
  set textContent(text) { this.children = [String(text)]; }
  get textContent() { return this.children.map(v => v instanceof Node ? v.textContent : String(v)).join(" "); }
}
const h = (tag, attrs, ...children) => new Node(tag, attrs, children);
const document = {createElement: tag => h(tag), createTextNode: String};
const context = vm.createContext({h, document, layoutText, actionCardModel, cleanRules, renderRules, renderTipCard,
  ruleSummary, state: {libOpen: new Set(), libPick: new Map(), byId: new Map()},
  norm: text => String(text || "").toLowerCase(), Node});
vm.runInContext(section(sheet, "function plainRules(text)", "function describe(b)") + "\n" +
  section(sheet, "const LIB_STATUS =", "function renderLibrary()"), context);
const library = JSON.parse(fs.readFileSync(0, "utf8"));
function render(row) {
  context.item = row;
  context.state.libOpen.add(row.id);
  const card = vm.runInContext('libCard(item, "")', context);
  // Read the player-visible summary from the shipped card itself.
  row.summary = card.children.find(node => node.attrs.class === "lib-summary").textContent;
  row.text = vm.runInContext('rulesText(layoutText(item.hover) || item.text || item.summary, "").textContent', context);
  row.tooltip = card.attrs.title || "";
}
for (const group of library.groups || []) {
  for (const row of group.entries || []) render(row);
  for (const sphere of group.spheres || []) {
    context.item = sphere;
    sphere.text = vm.runInContext('rulesText(item.text, "").textContent', context);
    for (const row of sphere.entries || []) render(row);
  }
}
process.stdout.write(JSON.stringify(library));
