"""Grow campaign UI checks. Chromium is opt-in and must run outside the sandbox."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "static/tabletop/grow.js"


def menu():
    return {"cl": 15, "realm": "Nascent Soul", "paths": [], "spheres": [], "talents": [], "forge": {},
            "ability_panel": {"scores": dict.fromkeys(["STR", "DEX", "CON", "INT", "WIS", "CHA"], 12)},
            "added": {"spheres": [], "talents": [], "forged": [], "abilities": [], "insights": [], "immortal_arts": []},
            "insights": [{"id": "insight.example", "name": "Example Lesson", "text": "Your lesson helps you.",
                          "legal": True, "reasons": []}],
            "immortal_art": {"known": 0, "limit": 3, "sources": [{"id": "source.example", "name": "Guard"}],
                            "aspects": [{"id": "aspect.example", "name": "Fortification",
                                         "factors": [{"id": "guard", "name": "Shield", "text": "Protects you."}], "burdens": []}]}}


def test_grow_campaign_handlers_add_remove_and_keep_source_note():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the DOM-free UI check")
    source = SOURCE.read_text().replace("export function", "function").replace("export async function", "async function")
    script = """
const assert = require("node:assert/strict");
const ids = {};
const calls = [];
let scheduled;
const setTimeout = callback => { scheduled = callback; return 1; };
const clearTimeout = () => {};
const current = MENU;
const root = {addEventListener() {}, replaceChildren(...children) { this.children = children; }};
ids["grow-root"] = root;
function h(tag, attrs, ...children) {
  const value = {tag, ...(attrs || {}), children, addEventListener() {}, replaceChildren() {},
    focus() { this.focused = true; }, setSelectionRange(start, end) { this.selection = [start, end]; }};
  if (attrs?.id) ids[attrs.id] = value;
  return value;
}
const pause = () => new Promise(resolve => setImmediate(resolve));
""" .replace("MENU", json.dumps(menu())) + source + """
(async () => {
  initGrow({h, $: id => ids[id], projectId: () => "campaign",
    toast() {}, reloadSheet: async () => {},
    fetchJson: async (url, options) => {
      if (url === "/api/session") return {token: "synthetic"};
      if (!options) return current;
      const body = JSON.parse(options.body); calls.push({url, body});
      if (url.endsWith("/insight")) current.added.insights.push({index: 0, name: "Example Lesson", note: body.note});
      if (url.endsWith("/remove")) current.added.insights = [];
      return current;
    }});
  await loadGrow();
  assert(ids["grow-insights"] && ids["grow-immortal-art"]);
  const oldSearch = ids["grow-insight-q"];
  onInput({target: {...oldSearch, value: "Example", selectionStart: 3, dataset: {}}});
  scheduled();
  const newSearch = ids["grow-insight-q"];
  assert.notEqual(newSearch, oldSearch);
  assert.equal(newSearch.value, "Example");
  assert.equal(newSearch.focused, true);
  assert.deepEqual(newSearch.selection, [3, 3]);
  onInput({target: {id: "grow-insight-note", value: "Mentor under the bridge", dataset: {}}});
  onClick({target: {closest: selector => selector === "[data-grow-insight]" ? {dataset: {growInsight: "insight.example"}} : null}});
  await pause(); await pause();
  assert.equal(calls[0].body.note, "Mentor under the bridge");
  assert.equal(calls[0].body.record_id, "insight.example");
  onClick({target: {closest: selector => selector === "[data-grow-remove]" ? {dataset: {growRemove: "insight", id: "0"}} : null}});
  await pause(); await pause();
  assert.equal(calls[1].body.kind, "insight");
  assert.equal(calls[1].body.record_id, "0");
  assert.equal(current.added.insights.length, 0);
  onChange({target: {id: "grow-art-source", value: "source.example", dataset: {}}});
  onChange({target: {id: "grow-art-aspect", value: "aspect.example", dataset: {}}});
  onChange({target: {id: "", checked: true, dataset: {growArtPick: "factor_ids", id: "guard"}}});
  assert.deepEqual(artDraft.factor_ids, ["guard"]);
  onInput({target: {id: "grow-art-die", value: "19", type: "number", dataset: {},
    setSelectionRange() {throw Error("Number input selection is forbidden");}}});
  assert.equal(artProof.die, 19);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


@pytest.mark.skipif(os.environ.get("GROW2_BROWSER") != "1", reason="Lead must run Chromium outside the sandbox")
def test_campaign_panels_render_and_accept_source_note_in_chromium():
    from playwright.sync_api import sync_playwright

    source = SOURCE.read_text().replace("export function", "function").replace("export async function", "async function")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            page.set_content('<div id="grow-root"></div>')
            page.evaluate("""({source, menu}) => {
              const h = (tag, attrs, ...children) => {
                const node = document.createElement(tag);
                for (const [key, value] of Object.entries(attrs || {})) {
                  if (value === null || value === undefined) continue;
                  if (key === "dataset") Object.assign(node.dataset, value);
                  else if (key === "style") node.setAttribute("style", value);
                  else node[key] = value;
                }
                for (const child of children.flat()) if (child !== null && child !== undefined) node.append(child);
                return node;
              };
              (0, eval)(source);
              initGrow({h, $: id => document.getElementById(id), projectId: () => "campaign",
                fetchJson: async () => menu, toast() {}, reloadSheet: async () => {}});
              return loadGrow();
            }""", {"source": source, "menu": menu()})
            page.locator("#grow-insight-q").fill("Example")
            page.wait_for_timeout(300)  # allow the real 150 ms replacement to run
            assert page.locator("#grow-insight-q").input_value() == "Example"
            assert page.locator("#grow-insight-q").evaluate("(node) => document.activeElement === node")
            assert page.locator("#grow-insight-q").evaluate("(node) => node.selectionStart") == 7
            page.locator("#grow-insight-note").fill("A quest reward")
            assert page.locator("#grow-insight-note").input_value() == "A quest reward"
            page.locator("#grow-art-name").fill("Azure Shelter")
            assert page.locator("#grow-art-name").input_value() == "Azure Shelter"
            assert page.locator("#grow-insights").inner_text().find("not its level-selection") >= 0
        finally:
            browser.close()
