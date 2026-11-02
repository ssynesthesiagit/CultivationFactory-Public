import test from "node:test";
import assert from "node:assert/strict";
import {paintAmbientCell, withTimeOfDay, indoorSelectValue} from "../static/tabletop/ambient_edit.js";
import {combineLightPayloads} from "../static/tabletop/light_layer.js";
import {editorLightPreview} from "../static/tabletop/mapeditor-light.js";

const ids = () => { let n = 0; return () => "r" + (++n); };
const levelOf = (regions, [x, y]) => {
  const hits = regions.filter(row => row.cells.some(([cx, cy]) => cx === x && cy === y));
  return {count: hits.length, levels: hits.map(row => row.level)};
};

test("repainting a square replaces its level instead of leaving the first region in charge", () => {
  let regions = [];
  regions = paintAmbientCell(regions, [1, 1], 2, ids());
  regions = paintAmbientCell(regions, [1, 1], 0, ids());
  assert.deepEqual(levelOf(regions, [1, 1]), {count: 1, levels: [0]});
  regions = paintAmbientCell(regions, [1, 1], 2, ids());
  assert.deepEqual(levelOf(regions, [1, 1]), {count: 1, levels: [2]});
});

test("painting over an imported region moves the square out of it", () => {
  const imported = [{id: "a", name: "Hall", level: 1, cells: [[3, 3], [4, 3]]}];
  const regions = paintAmbientCell(imported, [3, 3], 2, ids());
  assert.deepEqual(levelOf(regions, [3, 3]), {count: 1, levels: [2]});
  assert.deepEqual(levelOf(regions, [4, 3]), {count: 1, levels: [1]});
});

test("changing the time of day drops the stored level so the new time sets it", () => {
  const next = withTimeOfDay({time_of_day: "night", level: 0, indoor_level: 1}, "day");
  assert.deepEqual(next, {time_of_day: "day", indoor_level: 1});
  assert.equal("level" in withTimeOfDay({level: 0}, "dawn"), false);
});

test("the indoor select shows the stored level by name, and blank means use time of day", () => {
  assert.equal(indoorSelectValue(null), "");
  assert.equal(indoorSelectValue(undefined), "");
  assert.equal(indoorSelectValue(1), "dim");
  assert.equal(indoorSelectValue("bright"), "bright");
  assert.equal(indoorSelectValue(9), "");
});

test("shared view is the same whichever order the selected viewers are listed in", () => {
  const a = {cells: btoaCells([0, 2, 0, 1]), by: "a"};
  const b = {cells: btoaCells([1, 0, 2, 0]), by: "b"};
  const ab = decodeCells(combineLightPayloads([a, b]).cells);
  const ba = decodeCells(combineLightPayloads([b, a]).cells);
  assert.deepEqual(ab, [1, 2, 2, 1]);
  assert.deepEqual(ba, ab);
});

test("one viewer or none passes straight through", () => {
  assert.equal(combineLightPayloads([]), null);
  const only = {cells: btoaCells([2, 2, 2, 2]), by: "a"};
  assert.equal(combineLightPayloads([only]), only);
});

test("the editor hands its placed sources to the board, not only inside the payload", () => {
  const doc = {width_squares: 2, height_squares: 2, display: {run_ambient: true}, ambient: {time_of_day: "night"},
    lights: [{x: 1, y: 1, bright_ft: 10, dim_ft: 20, color: "orange"}, {x: 0, y: 0, lit: false, bright_ft: 5, dim_ft: 5}]};
  const preview = editorLightPreview(doc);
  assert.equal(preview.sources.length, 1);
  assert.equal(preview.sources[0].x, 1);
});

function btoaCells(values) {
  const packed = new Uint8Array(Math.ceil(values.length / 4));
  values.forEach((v, i) => { packed[Math.floor(i / 4)] |= (v & 3) << ((i % 4) * 2); });
  return Buffer.from(packed).toString("base64");
}
function decodeCells(encoded) {
  const bytes = Buffer.from(encoded, "base64");
  return Array.from({length: 4}, (_, i) => (bytes[Math.floor(i / 4)] >> (2 * (i % 4))) & 3);
}
