import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {setGlassSceneVisibility} from "../static/tabletop/glass-scene.js";

test("Glass scene toolbar control stays hidden for player and observer views, including first render", () => {
  const html = readFileSync(new URL("../static/tabletop/tabletop.html", import.meta.url), "utf8");
  const css = readFileSync(new URL("../static/tabletop/tabletop.css", import.meta.url), "utf8");
  const table = readFileSync(new URL("../static/tabletop/tabletop.js", import.meta.url), "utf8");
  assert.match(html, /<button id="ttGlassScene"[^>]*\shidden(?:\s|>)/);
  assert.match(css, /\.tt-tool\[hidden\]\s*\{\s*display:\s*none\s*!important;/);
  assert.match(table, /setGlassSceneVisibility\(glassScene, view\.status, Boolean\(app\.matchId\)\)/);
  assert.match(table, /function renderViewerIdentity\(view = currentViewer\(\)\)/);

  const button = {hidden: false, disabled: false};
  for (const status of ["player", "observer", "unbound", "stale"]) {
    setGlassSceneVisibility(button, status, true);
    assert.equal(button.hidden, true, status);
    assert.equal(button.disabled, true, status);
  }
  setGlassSceneVisibility(button, "gm", false);
  assert.equal(button.hidden, false);
  assert.equal(button.disabled, true);
  setGlassSceneVisibility(button, "gm", true);
  assert.equal(button.hidden, false);
  assert.equal(button.disabled, false);
});
