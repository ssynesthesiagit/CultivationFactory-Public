import assert from "node:assert/strict";
import test from "node:test";
import {createPrefightRow} from "../static/tabletop/prefight_row.js";

function element(tag) {
  return {tag, children: [], append(...children) { this.children.push(...children); }};
}
const documentRef = {createElement: element};

test("rendered pre-fight option row titles its printed effect, cost, and duration", () => {
  const {row, tick} = createPrefightRow({name: "Night-Sight Meridian", duration: "1 hour",
    description: "Dim Light does not impose Disadvantage on sight-based Perception checks."}, "1 CP", documentRef);
  assert.equal(row.tag, "label");
  assert.equal(row.className, "tt-prefight-row");
  assert.match(row.title, /Night-Sight Meridian \(1 CP; 1 hour\)/);
  assert.match(row.title, /Dim Light does not impose Disadvantage/);
  assert.equal(tick.tag, "input");
  assert.match(row.children[1].textContent, /1 CP · 1 hour/);
});
