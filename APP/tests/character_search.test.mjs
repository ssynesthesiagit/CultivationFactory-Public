import test from "node:test";
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import path from "node:path";
import {fileURLToPath} from "node:url";

const require = createRequire(import.meta.url);
const search = require(path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "static", "character_search.js"));

const rows = [{name: "Shen Lihuo"}, {name: "Mira"}];
test("character search matches names without regard to case", () => {
  assert.deepEqual(search.filter(rows, "shen", row => row.name), [rows[0]]);
  assert.deepEqual(search.filter(rows, "LIHUO", row => row.name), [rows[0]]);
});
test("clearing search shows every character and an empty query is not an empty state", () => {
  assert.deepEqual(search.filter(rows, "", row => row.name), rows);
  assert.equal(search.filter([], "", row => row.name).length, 0);
});
test("a non-matching query returns the empty state", () => {
  assert.deepEqual(search.filter(rows, "missing", row => row.name), []);
});
