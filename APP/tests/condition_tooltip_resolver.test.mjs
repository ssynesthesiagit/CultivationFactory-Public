// The SHIPPED condition resolver, run against the real server catalog and real table rows.
//
// MMX85f1 review finding 2: the first attempt at this regression copied conditionText() into Python and called
// all_conditions() directly, so it never touched /api/tabletop/conditions, never built a Golden Core table row,
// and silently dropped the resolver's own row.detail precedence. This harness instead lifts the real function out
// of static/tabletop/tabletop.js and runs it, so a regression in the endpoint wiring, the catalog, the table row,
// or the resolver itself all fail here.
//
// The catalog and the rows arrive from Python as the bytes the server actually returned.
// Runs under plain `node` as well as `node --test` (host Node 26 reports only the file wrapper under --test).
import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {runInNewContext} from "node:vm";
import {readStdinPayload} from "./node_stdin.mjs";

const table = readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");

function section(source, start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `Missing tabletop.js source boundary: ${start}`);
  return source.slice(from, to);
}

const rawPayload = (await readStdinPayload()).trim();
const payload = rawPayload ? JSON.parse(rawPayload) : {};
const catalog = payload.conditions || {};
const rows = payload.rows || [];

// The real resolver, verbatim, with the catalog the endpoint served. conditionText is the one function every
// surface (map hover, actor message, sheet pill) sends a condition row through, so this is the shipped path.
const context = {conditionInfo: {rows: catalog}};
runInNewContext(section(table, "const TONE_MEANING", "// The combat log"), context);
const conditionText = row => runInNewContext("conditionText(row)", Object.assign(context, {row}));

const results = rows.map(row => ({condition_id: row.condition_id, display_name: row.display_name,
                                  title: conditionText(row)}));
process.stdout.write(`MMX85_RESOLVED ${JSON.stringify(results)}\n`);

test("the shipped resolver gives every real table row a non-empty hover title", {
  // The negative control deliberately removes a catalog entry and expects a blank title, so the
  // caller states whether non-empty titles are the expectation for this run.
  skip: process.env.MMX85_EXPECT_NONEMPTY !== "1",
}, () => {
  assert.ok(rows.length, "no table rows were supplied");
  for (const row of results) {
    assert.ok(row.title, `empty hover title for ${row.display_name} (${row.condition_id})`);
  }
});

test("a row's own detail still wins over the catalog (Numbing Darkness)", () => {
  assert.equal(runInNewContext("conditionTextBody(row)", Object.assign(context, {
    row: {condition_id: "condition:typed.some_area_effect", detail: "The area's own words."}})),
    "The area's own words.");
  assert.match(conditionText({condition_id: "condition:typed.some_area_effect", detail: "The area's own words."}),
    /The area's own words.*Pill colour: red/);
});
