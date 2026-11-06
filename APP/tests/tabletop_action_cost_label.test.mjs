// node APP/tests/tabletop_action_cost_label.test.mjs
//
// MMX90 review finding 1 (P0): the action-bar and pip captions were given a template interpolation with an object
// literal but no opening brace, `${ACTION: "Action", ...}[row.kind]`. That is a syntax error, so the whole tabletop
// module failed to parse and every table lost its controls -- including characters unrelated to this lane. These tests
// pin the two things that went wrong: the module must parse, and the caption must come out in words either way.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");
// LIVE shares this formatter between both surfaces; evaluate the real helper
// alongside the extracted caption rather than duplicating its implementation.
const costSource = source.match(/function costTag\(row\) \{[\s\S]*?\n\}/)?.[0];
assert.ok(costSource, "the shared LIVE cost formatter exists");
const costTag = new Function(`${costSource}; return costTag;`)();

// The template literal that starts right after `marker`, tracking ${ } nesting so a nested template inside the
// interpolation does not end the scan early. `after` narrows the search to one function when the line appears twice.
function templateAfter(marker, after = "") {
  const region = source.indexOf(after);
  assert.notEqual(region, -1, `tabletop.js still has ${after}`);
  const start = source.indexOf(marker, region);
  assert.notEqual(start, -1, `tabletop.js still has ${marker}`);
  let depth = 0;
  for (let i = start + marker.length + 1; i < source.length; i++) {  // just past the opening backtick
    const ch = source[i];
    if (ch === "\\") { i++; continue; }
    if (ch === "`" && depth === 0) return source.slice(start + marker.length, i + 1);
    if (ch === "$" && source[i + 1] === "{") { depth++; i++; continue; }
    if (ch === "}" && depth > 0) depth--;
  }
  throw new Error(`unterminated template after ${marker}`);
}

const ACTION_BAR = "makeButton(row.label, ";
const PIP = 'button.querySelector("small").textContent = ';

test("the action bar and pip caption the cost the server sent, else the action's own economy", () => {
  const bar = templateAfter(ACTION_BAR);
  const render = row => new Function("row", "costTag", `return ${bar};`)(row, costTag);

  // What the server says wins: a free standing choice is not dressed up as a Bonus Action.
  assert.equal(render({kind: "BONUS_ACTION", cost_label: "Free", options: []}), "Free");
  assert.equal(render({kind: "ACTION", cost_label: "Action, 1 Qi", options: []}), "Action, 1 Qi");

  // With nothing said, the caption falls back to the economy the engine already reported.
  assert.equal(render({kind: "ACTION", options: []}), "Action");
  assert.equal(render({kind: "BONUS_ACTION", options: []}), "Bonus");
  assert.equal(render({kind: "HOLD_POSITION", options: []}), "Hold");
  assert.equal(render({kind: "REACTION", options: []}), "REACTION", "an unknown kind is shown, not guessed");
  assert.equal(render({kind: "ACTION", cost_label: "", options: []}), "Action", "an empty label is no label");
  assert.equal(render({kind: "BONUS_ACTION", economy: "NONE", options: []}), "Free");
  assert.equal(render({kind: "REACTION", economy: "REACTION", options: []}), "Reaction");

  // The "N choices" hint still rides the end of the same caption, and only when there really is a choice.
  assert.equal(render({kind: "ACTION", options: [1, 2, 3]}), "Action · 3 choices");
  assert.equal(render({kind: "BONUS_ACTION", cost_label: "Free", options: [1, 2]}), "Free · 2 choices");
  assert.equal(render({kind: "ACTION", options: [1]}), "Action", "one option is not a choice");
});

test("the pop-out pip prints the same words as the action bar", () => {
  const pip = templateAfter(PIP, "function renderPip(");
  const render = group => new Function("group", "costTag", `return ${pip};`)(group, costTag);
  assert.equal(render({kind: "ACTION", cost_label: "Action, 1 Qi", options: []}), "Action, 1 Qi");
  assert.equal(render({kind: "BONUS_ACTION", cost_label: "Free", options: []}), "Free");
  assert.equal(render({kind: "ACTION", options: []}), "Action");
  assert.equal(render({kind: "HOLD_POSITION", options: [1]}), "Hold");
});
