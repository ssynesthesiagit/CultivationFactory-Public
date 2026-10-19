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
    toast() {}, hint() {}, renderHighlights() {}, renderTokens() {}, renderRoster() {}, renderInspector() {},
    broadcastActors() {},
    chooseFromList() { throw new Error("unexpected list"); },
  };
  for (const name of ["refuseCoveredView", "closeChoice", "actOnce", "preferredTargets", "useGroup", "onTokenClick", "selectActor"]) {
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
