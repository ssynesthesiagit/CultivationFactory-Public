import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {editorLightPreview} from "../static/tabletop/mapeditor-light.js";

const editor = readFileSync(new URL("../static/tabletop/mapeditor.js", import.meta.url), "utf8");
const page = readFileSync(new URL("../static/tabletop/mapeditor.html", import.meta.url), "utf8");

test("editor lighting preview reflects authored time, painted cells and lit sources", () => {
  const result = editorLightPreview({width_squares: 2, height_squares: 2,
    ambient: {time_of_day: "night"}, ambient_regions: [{level: "bright", cells: [[1, 0]]}],
    lights: [{x: 0, y: 1, bright_ft: 10, dim_ft: 20, color: "#ffaa00", lit: true},
      {x: 1, y: 1, bright_ft: 10, dim_ft: 20, lit: false}]});
  assert.deepEqual([...Uint8Array.from(atob(result.cells), c => c.charCodeAt(0))], [0b00001000]);
  assert.deepEqual(result.sources, [{x: 0, y: 1, bright_ft: 10, dim_ft: 20, color: "#ffaa00"}]);
  assert.match(editor, /board\.setLight\(doc\.display\?\.run_ambient \? editorLightPreview\(doc\) : null, null, \{preview: true\}\)/);
});

test("preview toggle and ambient/source authoring controls are present", () => {
  for (const id of ["meTimeOfDay", "meIndoorLight", "meRunAmbient", "meAmbientLevel", "meLightName", "meLightBright", "meLightDim"])
    assert.ok(page.includes(`id="${id}"`));
  assert.match(editor, /doc\.ambient/);
  assert.match(editor, /doc\.lights/);
});
