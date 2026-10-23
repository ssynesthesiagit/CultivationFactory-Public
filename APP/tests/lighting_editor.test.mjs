import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";

const editor = readFileSync(new URL("../static/tabletop/mapeditor.js", import.meta.url), "utf8");
const page = readFileSync(new URL("../static/tabletop/mapeditor.html", import.meta.url), "utf8");

test("editor exposes light placement, drag, erase, and ambient painting through history edits", () => {
  for (const text of ['data-tool="light"', 'data-tool="ambient"', 'editor.dragLight', 'doc.lights.splice', 'doc.ambient_regions'])
    assert.ok(editor.includes(text), `missing editor behavior: ${text}`);
  assert.ok(editor.includes('change(doc => { doc.lights ='));
  assert.ok(editor.includes('Bright radius must be no greater than the dim radius.'));
});

test("ambient controls expose time, indoor level and preview", () => {
  for (const id of ['meTimeOfDay', 'meIndoorLight', 'meRunAmbient', 'meAmbientLevel'])
    assert.ok(page.includes(`id="${id}"`));
  assert.ok(editor.includes('doc.ambient'));
});
