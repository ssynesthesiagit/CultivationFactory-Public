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
  throw new Error(`Unclosed ${name}`);
}

test("disabled action tooltip uses the server's plain reason", () => {
  const context = {app: {state: {unavailable_reasons: {"act:smoke": "Used: once per short rest; returns after a short rest."}}}};
  runInNewContext(declaration("reasonFor"), context);
  assert.equal(context.reasonFor({}, {id: "act:smoke"}), "Used: once per short rest; returns after a short rest.");
});

test("hidden housekeeping conditions do not appear in token or condition lists", () => {
  const declaration = source.match(/const shownCondition = row => [^;]+;/)?.[0];
  assert.ok(declaration, "condition visibility filter is present");
  const context = {};
  runInNewContext(declaration.replace("const shownCondition", "globalThis.shownCondition"), context);
  assert.equal(context.shownCondition({condition_id: "condition:typed.concentration_deadline", hidden: true}), false);
  assert.equal(context.shownCondition({condition_id: "condition:core.blinded", hidden: false}), true);
});

test("unknown restrictions do not suggest movement or guess a displayed cost", () => {
  const context = {app: {state: {}}};
  runInNewContext(declaration("reasonFor"), context);
  assert.equal(context.reasonFor({resources: [{display_name: "CP", current: 0}]},
    {id: "act:unknown", detail: {cost: "3 CP"}}),
    "Unavailable now: this action has no legal option under the current combat rules.");
});
