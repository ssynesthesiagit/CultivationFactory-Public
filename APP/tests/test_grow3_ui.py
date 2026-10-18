"""Grow wizard UI: no browser is launched unless the lead opts in."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def source():
    return (ROOT / "static/tabletop/grow.js").read_text().replace("export ", "")


def test_wizard_preserves_all_talent_options_and_draft_choices():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for this DOM-free UI check")
    script = source() + r"""
const assert = require("node:assert/strict");
deps = {h: (tag, props, ...children) => ({tag, props, children}), $: () => null};
data = {cl: 1, level_up: {cl: 2, available: true, history: [], talent_count: 1, subpaths: [],
  statistics: {pb: 2, hp: {maximum: 17}},
  talents: Array.from({length: 210}, (_, i) => ({id: "talent."+i, name: "Talent "+i, legal: true}))}};
levelDraft = {open: true, step: 1, talent_ids: ["talent.209"], subpaths: {}, changes: {}};
const tree = JSON.stringify(levelBlock());
for (let i = 0; i < 210; i++) assert.ok(tree.includes('"value":"talent.'+i+'"'), "missing "+i);
assert.ok(tree.includes('"checked":true'));
levelDraft.step = 0;
const review = JSON.stringify(levelBlock());
assert.ok(review.includes("cultivation level") || review.includes("Cultivation level"));
assert.ok(review.includes("17"));
assert.deepEqual(levelDraft.talent_ids, ["talent.209"]);
levelDraft.open = false;
assert.ok(JSON.stringify(levelBlock()).includes("Level up"));
assert.deepEqual(levelDraft.talent_ids, ["talent.209"]);
"""
    subprocess.run([node, "-e", script], check=True, text=True, capture_output=True)


@pytest.mark.skipif(os.environ.get("GROW3_BROWSER") != "1", reason="Lead must run Chromium outside the sandbox")
def test_chromium_level_wizard_and_jade_source():
    from playwright.sync_api import sync_playwright
    view = {"cl": 1, "realm": "Mortal", "paths": [], "added": {"spheres": [], "talents": [], "forged": []},
            "sources": ["campaign", "manual", "jade tablet"], "ability_panel": {}, "forge": {},
            "level_up": {"cl": 2, "available": True, "history": [], "talent_count": 1,
                "subpaths": [], "features": [{"name": "Meridian Regulation", "text": "Recover Qi during a short rest."}],
                "statistics": {"pb": 2, "hp": {"maximum": 17}},
                "talents": [{"id": "practice", "name": "Water practice", "legal": True}]}}
    harness = r"""
window.posts = [];
function h(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === false) continue;
    if (key === "dataset") Object.assign(node.dataset, value);
    else if (key === "class") node.className = value;
    else if (key === "style") node.style.cssText = value;
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
initGrow({h, $: id => document.getElementById(id), projectId: () => "synthetic",
  toast() {}, reloadSheet: async () => {},
  fetchJson: async (url, options) => {
    if (url === "/api/session") return {token: "fake"};
    if (options) window.posts.push(JSON.parse(options.body));
    return window.view;
  }});
await loadGrow();
"""
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.set_content('<div id="grow-root"></div>')
            page.evaluate("window.view = " + json.dumps(view))
            page.evaluate("(async () => {" + source() + harness + "})()")
            page.locator("#grow-source").select_option("jade tablet")
            page.get_by_role("button", name="Level up", exact=True).click()
            assert page.get_by_text("Meridian Regulation", exact=True).is_visible()
            page.get_by_role("button", name="Next", exact=True).click()
            page.get_by_label("Water practice", exact=False).check()
            page.get_by_role("button", name="Next", exact=True).click()
            page.get_by_role("button", name="Record level", exact=True).click()
            page.wait_for_function("window.posts.length === 1")
            assert page.evaluate("window.posts[0].talent_ids") == ["practice"]
            assert page.evaluate("window.posts[0].cl") == 2
            assert not errors
        finally:
            browser.close()
