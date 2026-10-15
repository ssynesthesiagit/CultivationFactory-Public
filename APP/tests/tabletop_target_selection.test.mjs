import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");

function declaration(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} is present`);
  const open = source.indexOf(") {", start) + 2;
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === "{") depth++;
    if (source[i] === "}" && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`Unclosed function ${name}`);
}

function harness() {
  const calls = [];
  // useGroup closes the table's open choice when an action needs no further choice, and announces an
  // open one on the BroadcastChannel. This file tests target selection, so the channel is a no-op --
  // but closeChoice and actOnce are the real ones, so the target logic under test is not faked.
  const app = {busy: false, state: {}, menu: {actor_id: "actor"}, selected: new Set(), lastTarget: "old-target",
               targeting: null, pendingChoice: null};
  const context = {
    app, calls,
    act: async candidate => { calls.push(candidate); return true; },
    // The player's view is available here, so the covered-view guard stands aside.
    currentViewer: () => ({ready: true}),
    toast() {}, hint(text) { context.hintText = text; }, renderHighlights() {}, renderTokens() {}, renderRoster() {}, renderInspector() {},
    broadcastActors() {},
    chooseFromList() { throw new Error("unexpected list"); },
  };
  for (const name of ["refuseCoveredView", "closeChoice", "cancelTargeting", "actOnce", "preferredTargets", "useGroup", "onTokenClick", "selectActor"]) {
    runInNewContext(declaration(name), context);
  }
  return {app, calls, context};
}

test("selecting a different token discards the cached target and uses the legal selection", async () => {
  const {app, calls, context} = harness();
  context.onTokenClick("new-target", {shiftKey: false});
  assert.equal(app.lastTarget, null);
  assert.deepEqual(Array.from(context.preferredTargets()), ["new-target"]);

  const group = {label: "Test action", options: [
    {candidate_id: "old-candidate", target_ids: ["old-target"]},
    {candidate_id: "new-candidate", target_ids: ["new-target"]},
  ]};
  await context.useGroup(group, {preferTargets: context.preferredTargets()});
  assert.deepEqual(calls, ["new-candidate"]);
  assert.equal(app.targeting, null);
});

for (const kind of ["target", "area", "destination"]) {
  for (const focused of [null, "select", "input", "dialog"]) {
    test(`Escape cancels ${kind} picking with ${focused || 'map'} focus and spends nothing`, async () => {
      const {app, calls, context} = harness();
      let keydown;
      context.document = {addEventListener: (_, handler) => { keydown = handler; }};
      const start = source.indexOf('document.addEventListener("keydown", event => {');
      runInNewContext(source.slice(start, source.indexOf('// Keep a watching table in step', start)), context);
      const options = [1, 2].map(i => ({candidate_id: `choice-${i}`, target_ids: kind === "target" ? [`foe-${i}`] : [],
        ...(kind === "area" ? {area: {center: {x: i, y: 1}}} : {}),
        ...(kind === "destination" ? {destination: {x: i, y: 1}} : {})}));
      const pending = context.useGroup({label: "Test ability", options});
      assert.ok(app.targeting);
      let prevented = false;
      keydown({key: "Escape", target: {closest: () => focused}, preventDefault() { prevented = true; }});
      assert.equal(await pending, false);
      assert.equal(app.targeting, null);
      assert.equal(app.pendingChoice, null);
      assert.equal(context.hintText, null);
      assert.deepEqual(calls, []);
      assert.equal(prevented, true);
    });
  }
}

test("reaction menu answers preserve every Pass and bind a later mode to its own source", () => {
  const context = {};
  runInNewContext(declaration("reactionMenuAnswers"), context);
  const alternatives = ["guard", "corrupt:mode:0", "corrupt:mode:3"].map(reaction_source_id => ({
    context: {checkpoint: "TYPED:HEALED@8", reactor_id: "player", reaction_source_id}}));
  const pass = context.reactionMenuAnswers({alternatives}, -1);
  assert.equal(pass.length, 3);
  assert.ok(pass.every(d => d.selection === "DECLINE"));
  const picked = context.reactionMenuAnswers({alternatives}, 1, "USE");
  assert.equal(picked.length, 2);
  assert.equal(picked[0].selection, "DECLINE");
  assert.equal(picked[1].reaction_source_id, "corrupt:mode:0");
  assert.equal(picked[1].selection, "USE");
});

test("the reaction menu renders the complete set and Pass without an automatic answer", async () => {
  let rendered;
  let resolveChoice;
  const context = {showChoiceDialog: prompt => { rendered = prompt; return new Promise(resolve => { resolveChoice = resolve; }); }};
  runInNewContext(declaration("reactionMenuAnswers") + declaration("askReactionMenu"), context);
  const alternatives = Array.from({length: 25}, (_, i) => ({reaction: `Reaction ${i}`, trigger: "Enemy heals",
    summary: "Affects Enemy until your next turn.", cost: "Reaction; 5 Qi",
    limits: "Cannot suppress artifact protections.", table_note: "The GM applies this effect manually.",
    rules: "The target makes a Charisma saving throw.",
    context: {checkpoint: "TYPED:HEALED@8", reactor_id: "player", reaction_source_id: `reaction:${i}`}}));
  let settled = false;
  const pending = context.askReactionMenu({alternatives}).then(answer => { settled = true; return answer; });
  await Promise.resolve();
  assert.equal(settled, false, "the player must explicitly answer");
  assert.equal(rendered.choice.options.length, 25, "no top-N or hidden cutoff");
  for (const option of rendered.choice.options) {
    assert.match(option.description, /Cannot suppress artifact protections/);
    assert.match(option.description, /GM applies this effect manually/);
    assert.match(option.description, /Charisma saving throw/);
  }
  assert.equal(rendered.choice.allow_decline, true, "Pass stays available");
  assert.equal(rendered.cost, "Shown beside each reaction", "the menu does not present the first entry as chosen");
  resolveChoice({selection: "USE", option_ids: ["24"]});
  const answers = await pending;
  assert.equal(answers.length, 25);
  assert.equal(answers.at(-1).reaction_source_id, "reaction:24");
  assert.equal(answers.at(-1).selection, "USE");
});

test("Escape on the hint-bar list uses the same cancellation as its Cancel button", async () => {
  const {app, calls, context} = harness();
  const element = () => ({firstChild: {textContent: ""}, children: [],
    addEventListener(name, handler) { this[name] = handler; },
    insertBefore(child) { this.children.push(child); }, appendChild(child) { this.children.push(child); }});
  const node = element();
  context.$ = () => node;
  let keydown;
  context.document = {createElement: () => element(), addEventListener: (_, handler) => { keydown = handler; }};
  runInNewContext(declaration("chooseFromList"), context);
  const start = source.indexOf('document.addEventListener("keydown", event => {');
  runInNewContext(source.slice(start, source.indexOf('// Keep a watching table in step', start)), context);
  const pending = context.chooseFromList({label: "Ability mode"}, [{candidate_id: "one", label: "One"}]);
  assert.ok(app.listPick);
  keydown({key: "Escape", target: {closest: () => "select"}, preventDefault() {}});
  assert.equal(await pending, false);
  assert.equal(app.listPick, null);
  assert.equal(app.pendingChoice, null);
  assert.deepEqual(calls, []);
  node.children.at(-1).click();
  assert.deepEqual(calls, [], "a stale Cancel handler cannot spend anything");
});

test("Ask me hides the preset mode; automatic plans keep it", () => {
  const sheet = readFileSync(new URL("../static/tabletop/sheet.js", import.meta.url), "utf8");
  const start = sheet.indexOf("function renderReactions()");
  let rendered;
  const context = {
    state: {sheet: {reaction_plan: {mode: "ask", order: ["menu"], choices: [
      {id: "menu", name: "Menu reaction", options: ["First", "Second"], option: 1}]}}},
    $: id => id === "reactions-panel" ? {replaceChildren: tree => { rendered = tree; }} : null,
    h: (tag, attrs, ...children) => ({tag, attrs, children})};
  runInNewContext(sheet.slice(start, sheet.indexOf("// Companions", start)), context);
  const countPreset = tree => tree && typeof tree === "object"
    ? (tree.attrs?.class?.includes("reaction-option") ? 1 : 0) + (tree.children || []).reduce((n, c) => n + countPreset(c), 0) : 0;
  context.renderReactions();
  assert.equal(countPreset(rendered), 0);
  context.state.sheet.reaction_plan.mode = "auto";
  context.renderReactions();
  assert.equal(countPreset(rendered), 1);
});

test("an illegal current selection opens the picker instead of using the old target", async () => {
  const {app, calls, context} = harness();
  context.onTokenClick("unrelated-token", {shiftKey: false});
  const group = {label: "Test action", options: [
    {candidate_id: "old-candidate", target_ids: ["old-target"]},
    {candidate_id: "legal-candidate", target_ids: ["legal-target"]},
  ]};
  context.useGroup(group, {preferTargets: context.preferredTargets()});
  assert.deepEqual(calls, []);
  assert.ok(app.targeting);
  assert.deepEqual(Array.from(app.targeting.byTarget.keys()), ["old-target", "legal-target"]);
});

test("roster selection invalidates a cached target while an untouched combo can retain it", () => {
  const {app, context} = harness();
  assert.deepEqual(Array.from(context.preferredTargets()), ["old-target"]);
  context.selectActor("actor");
  assert.equal(app.lastTarget, null);
  assert.deepEqual(Array.from(context.preferredTargets()), ["actor"]);
  app.selected.clear();
  app.lastTarget = "combo-target";
  assert.deepEqual(Array.from(context.preferredTargets()), ["combo-target"]);
});
