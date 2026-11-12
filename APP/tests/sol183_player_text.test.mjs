import assert from "node:assert/strict";
import {test} from "node:test";
import {riderNotice} from "../static/tabletop/rules.js";

test("manual reminder toast uses the entire server projection, never raw author evidence", () => {
  const summary = "Stitch the Falling Body: " + "Catch the falling ally safely. ".repeat(20);
  const row = {event_type: "GM_RIDER", summary,
    payload: {rider: "#### Author block Action Type: Reaction TAL_INTERNAL"},
    raw: {payload: {rider: "condition:typed.internal"}}};
  assert.equal(riderNotice([row], new Set(["GM_RIDER"])), summary);
  assert.equal(riderNotice([{...row, summary: ""}], new Set(["GM_RIDER"])), "");
  assert.equal(riderNotice([row, {event_type: "DAMAGE_COMMITTED"}], new Set(["GM_RIDER"])), "");
});
