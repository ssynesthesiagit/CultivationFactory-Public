import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const staticRoot = new URL("../static/tabletop/", import.meta.url);
const rules = await import(new URL("rules.js", staticRoot));
const { cleanRules, ruleSummary, renderRules, actionSummary, actionHoverText, reactionHelp, rulesTextFor, uniqueRuleBlocks } = rules;

function h(tag, attrs, ...kids) {
  return {tag, attrs, kids: kids.flat(Infinity), append(...nodes) { this.kids.push(...nodes); },
    appendChild(node) { this.kids.push(node); return node; },
    setAttribute(key, value) { this.attrs[key] = value; },
    set textContent(value) { this.kids = [value]; },
    get textContent() { return this.kids.map(kid => typeof kid === "string" ? kid : kid.textContent).join(""); }};
}
function find(node, tag) {
  return [node, ...node.kids.flatMap(kid => typeof kid === "string" ? [] : find(kid, tag))].filter(child => child.tag === tag);
}

test("library strips routing/review metadata, preserves rule headings and renders printed tables", () => {
  const text = "# Domain Pressure\nFactory Routing: combat_action_row\n**Factory Coverage:** CORE_WITH_RIDERS\nRecommended Factory Realization: internals\nSplit Review Decision: internals\nCost: 2 CP\nRelease a wave of spiritual authority.\n| CL | Cone Length |\n|---:|---:|\n| 5–10 | 15 feet |\n| 11–16 | 30 feet |";
  assert.equal(ruleSummary(text), "Release a wave of spiritual authority.");
  assert.doesNotMatch(cleanRules(text), /Factory|internals|CORE_WITH_RIDERS/);
  assert.match(cleanRules(text), /# Domain Pressure/);
  const node = renderRules(text, h, line => [line]);
  assert.equal(find(node, "table").length, 1);
  assert.equal(find(node, "th").length, 2);
  assert.equal(find(node, "td").length, 4);
  assert.match(node.textContent, /CP means cultivation points/);
  assert.match(node.textContent, /30 feet/);
  const hostile = renderRules('<img src=x onerror="bad()">A safe rule.', h, line => [line]);
  assert.equal(hostile.textContent, "A safe rule.");
  assert.equal(find(hostile, "img").length, 0);
});

test("the shipped action lookup keeps the end of long rules and shows contextual help first", () => {
  const source = readFileSync(new URL("tabletop.js", staticRoot), "utf8");
  const text = "Action Type: Action\n" + "A printed effect sentence. ".repeat(70) + "The final rule still matters.";
  const sheet = {library: {groups: [{entries: [{button_id: "x", name: "Attack", text}]}]}};
  assert.match(rulesTextFor(sheet, {id: "x", label: "Attack"}), /The final rule still matters\.$/);
  // Contextual help is shown first, but it must not hide the printed library rules.
  const contextual = rulesTextFor(sheet, {id: "x", label: "Attack", description: "Choose this particular option."});
  assert.match(contextual, /^Choose this particular option\./);
  assert.match(contextual, /The final rule still matters\.$/);
  assert.equal(rulesTextFor(null, {description: text}), text);
  const structured = rulesTextFor(sheet, {id: "x", label: "Attack",
    hover: {title: "Chosen option", text: "Chosen option\nChoose this particular option.", fields: [], body: []}});
  assert.match(structured, /^Chosen option\nChoose this particular option\./);
  assert.match(structured, /The final rule still matters\.$/, "structured context must keep the complete printed fallback");
  assert.match(source, /card\.appendChild\(actionRules\(/);
});

test("action summary and reaction help explain costs, saves and player control", () => {
  const summary = actionSummary({economy: "ACTION", description: "# Grapple\nOn failure, the creature is Grappled.",
    detail: {cost: "2 Stamina", save: "Strength or Dexterity save, DC 14", range: "5 ft"}});
  assert.match(summary, /^Action · Cost: 2 Stamina/);
  assert.match(summary, /Strength or Dexterity save, DC 14/);
  assert.match(summary, /On failure/);
  assert.match(reactionHelp(), /Ask me.*Use or Pass.*automatic reactions.*AI-controlled/);
});

test("reaction help remains in action summaries even when the cost warning takes priority", () => {
  const source = readFileSync(new URL("tabletop.js", staticRoot), "utf8");
  const context = vm.createContext({reactionHelp});
  vm.runInContext(source.slice(source.indexOf("function reasonFor("), source.indexOf("function actionRules(", source.indexOf("function reasonFor("))), context);
  const reaction = {label: "Guard", economy: "REACTION", description: "Reduce the triggering damage.", detail: {cost: "2 Stamina"}};
  const actor = {resources: [{display_name: "Stamina", current: 1}]};
  assert.equal(context.reasonFor(actor, reaction), "Needs 2 Stamina (you have 1)");
  const summary = actionSummary(reaction);
  assert.match(summary, /Cost: 2 Stamina/);
  assert.match(summary, /Reduce the triggering damage/);
  assert.match(summary, /Ask me.*Use or Pass.*automatic reactions.*AI-controlled/);
  assert.doesNotMatch(actionSummary({...reaction, economy: "ACTION"}), /Ask me/);
  actor.resources[0].current = 2;
  assert.equal(context.reasonFor(actor, reaction), "");
  assert.equal([summary, context.reasonFor(actor, reaction)].join("\n").split("Ask me").length - 1, 1);

  // Exercise the shipped sheet button renderer, not a copy of its hover expression.
  const sheet = readFileSync(new URL("sheet.js", staticRoot), "utf8");
  const sheetContext = vm.createContext({h, actionSummary, actionHoverText, actionTipCard: rules.actionTipCard, reactionHelp, uniqueRuleBlocks, economyLabel: value => value,
    GROUP_NAMES: {}, describe: b => b.description, hitCell: () => ""});
  vm.runInContext(sheet.slice(sheet.indexOf("function actionRow("), sheet.indexOf("// Hover text", sheet.indexOf("function actionRow("))), sheetContext);
  const button = sheetContext.actionRow(reaction);
  assert.equal(button.attrs.title.split("Ask me").length - 1, 1);
  assert.match(button.attrs.title, /automatic reactions/);
});

test("shipped action disclosure contains the complete rules and library snippets hide metadata", () => {
  const source = readFileSync(new URL("tabletop.js", staticRoot), "utf8");
  const document = {createElement: tag => h(tag, {})};
  const context = vm.createContext({document, renderRules});
  vm.runInContext(source.slice(source.indexOf("function actionRules("), source.indexOf("function buttonDetail(")), context);
  const text = "A printed rule. ".repeat(100) + "Final duration and cost.";
  const node = context.actionRules(text, "Action: affect one creature.");
  assert.equal(node.tag, "details");
  assert.equal(find(node, "summary")[0].textContent, "Full rules");
  assert.match(node.textContent, /Final duration and cost\.$/);
  const sheet = readFileSync(new URL("sheet.js", staticRoot), "utf8");
  const snippets = vm.createContext({cleanRules, h, norm: text => String(text || "").toLowerCase(), highlight: text => [text]});
  vm.runInContext(sheet.slice(sheet.indexOf("function snippet("), sheet.indexOf("function libCard(")), snippets);
  assert.equal(snippets.snippet({name: "Talent", text: "Factory Routing: secret_id\nA printed rule."}, "secret_id"), null);
});

// The service roster test pipes owner library rows here without retaining private fixtures.
if (process.argv.includes("--roster")) {
  const entries = JSON.parse(readFileSync(0, "utf8"));
  let tables = 0;
  for (const entry of entries) {
    const clean = cleanRules(entry.text);
    assert.doesNotMatch(clean, /^\s*(?:\*\*)?Factory [\w -]+:/im, entry.name);
    const node = renderRules(entry.text, h, line => [line]);
    assert.doesNotMatch(node.textContent, /Factory Routing:/, entry.name);
    if (/^\s*\|.*\n\s*\|\s*:?-{3,}/m.test(clean)) {
      assert.ok(find(node, "table").length, entry.name);
      tables++;
    }
  }
  console.log(`Owner library: ${entries.length} entries checked; ${tables} entries render tables.`);
}
