"""GROWENTRY1: the owner character sheet opens the table sheet's Grow tab directly.

(a) static/tabletop/sheet.js honours ?tab=grow (and ignores unknown names) by calling selectTab.
(b) the owner Leveling section renders the "Change or level up this character" button with the Grow URL.
"""
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest

APP = Path(__file__).resolve().parents[1]
PROJECT = "00000000-0000-4000-8000-000000000a01"


def test_sheet_js_reads_tab_parameter_and_selects_it_after_render():
    source = (APP / "static/tabletop/sheet.js").read_text(encoding="utf-8")
    start = source.index("const requestedTab = params.get(\"tab\");")
    block = source[start:start + 400]
    assert source.rindex("renderAll();", 0, start) > source.index("async function main()")
    assert "selectTab(requestedTab)" in block
    assert "tab.dataset.tab === requestedTab" in block


@pytest.mark.skipif(os.environ.get("GROWENTRY_BROWSER") != "1",
                    reason="GROWENTRY_BROWSER=1 requires a Chromium-capable environment with playwright")
@pytest.mark.parametrize("query, expected_selected", [
    ("tab=grow", "grow"),
    ("tab=bogus", "actions"),
    ("", "actions"),
])
def test_sheet_page_selects_grow_only_for_known_tab(tmp_path, query, expected_selected):
    """Real sheet.js in Chromium: ?tab=grow selects Grow; unknown or absent names keep the default tab."""
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = browser.new_page()

        def serve(route):
            path = urlparse(route.request.url).path
            if path.startswith("/static/"):
                route.fulfill(path=str(APP / path.removeprefix("/")))
            elif path == "/tabletop/sheet":
                route.fulfill(path=str(APP / "static/tabletop/sheet.html"))
            elif path == f"/api/tabletop/characters/{PROJECT}/sheet":
                route.fulfill(json={"actor_id": PROJECT, "summary": {"name": "Grow test"}, "buttons": [], "library": {"groups": []}})
            elif path.startswith("/api/"):
                route.fulfill(json={})
            else:
                route.abort()

        page.route("**/*", serve)
        # The sheet's module graph can hold the load event open; wait for the sheet's own render signal instead.
        page.goto(f"http://grow.test/tabletop/sheet?project={PROJECT}" + (f"&{query}" if query else ""), wait_until="commit")
        page.wait_for_function("document.querySelector('#sheet').getAttribute('aria-busy') === 'false'")
        selected = page.evaluate(
            "() => [...document.querySelectorAll('#tablist [role=tab]')].filter(t => t.getAttribute('aria-selected') === 'true').map(t => t.dataset.tab)")
        browser.close()
    assert selected == [expected_selected]


def _run_leveling_harness(script: str) -> dict:
    result = subprocess.run(["node", "-e", script], cwd=APP, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


HARNESS = r"""
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const {documentStub} = require('./tests/gm_sheet_dom_stub/domstub.js');
const readStatic = name => fs.readFileSync(path.join('static', name), 'utf8');
const opened = [];
const sandbox = {
  console,
  setTimeout, clearTimeout, setInterval, clearInterval,
  AbortController,
  Image: class { constructor() { this.src = ''; } },
  fetch: async () => { throw new Error('network disabled'); },
  Option: class { constructor(text = '', value = '') { this.textContent = text; this.value = value; } },
  location: {assign() {}, reload() {}},
  navigator: {userAgent: 'grow-entry'},
  document: documentStub,
  localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
  open: (...args) => { opened.push(args); return globalThis.__popupResult; },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.addEventListener = () => {};
sandbox.removeEventListener = () => {};
vm.createContext(sandbox);
for (const file of ['sphere_talent_logic.js', 'sheet_view_model.js', 'complete_request_save.js', 'character_search.js']) {
  vm.runInContext(readStatic(file), sandbox, {filename: file});
}
documentStub.getElementById('guidedManualLineageTrainingTypes').options = [{selected: false}];
vm.runInContext(readStatic('app.js'), sandbox, {filename: 'app.js'});

function find(node, pred, out = []) {
  if (!node) return out;
  if (pred(node)) out.push(node);
  for (const child of node.children || []) find(child, pred, out);
  return out;
}
const hasClass = (node, name) => String(node.className || '').split(/\s+/).includes(name);
const PID = '__PID__';
function sheet(buildStatus) {
  return {
    project_id: PID, name: 'Wayfinder', build_status: buildStatus,
    owner_character_sheet: {identity: {display_name: 'Wayfinder'}},
    complete_character: {available: true, surfaces: {leveling: {available: true, data: {levels: [
      {cl: 1, realm: 'Mortal', pb: 2, ability_scores_after: {STR: 15}},
    ]}}}},
  };
}
function render(buildStatus) {
  const content = sandbox.ownerLevelingContent(sandbox.ownerSheetContext(sheet(buildStatus)));
  return content;
}
const out = {};
const finalized = render('CHARACTER_SHEET_READY');
const buttons = find(finalized, n => hasClass(n, 'owner-grow-entry-button'));
out.buttonCount = buttons.length;
out.buttonText = buttons[0] ? buttons[0].textContent : null;
const notes = find(finalized, n => hasClass(n, 'owner-grow-entry-note')).map(n => n.textContent);
out.noteText = notes[0] || null;
out.firstChildIsEntry = finalized.children[0] ? hasClass(finalized.children[0], 'owner-grow-entry') : false;
out.levelRows = find(finalized, n => hasClass(n, 'owner-level-row')).length;
globalThis.__popupResult = {};
buttons[0].click();
out.opened = opened.map(args => args[0]);
globalThis.__popupResult = null;
buttons[0].click();
out.blockedNote = find(finalized, n => hasClass(n, 'owner-grow-entry-note')).map(n => n.textContent).slice(1);
out.notFinalizedButtons = find(render('ADVANCEMENT_READY'), n => hasClass(n, 'owner-grow-entry-button')).length;
console.log(JSON.stringify(out));
process.exit(0);
""".replace("__PID__", PROJECT)


def test_leveling_section_renders_grow_button_with_correct_url():
    out = _run_leveling_harness(HARNESS)
    assert out["buttonCount"] == 1
    assert out["buttonText"] == "Change or level up this character"
    assert out["noteText"] == ("Opens the Grow page: change ability scores, learn talents and Spheres, forge techniques. "
                               "No fight needed.")
    assert out["firstChildIsEntry"] is True
    assert out["levelRows"] == 1
    assert out["opened"] == [f"/tabletop/sheet?project={PROJECT}&tab=grow"]
    assert out["blockedNote"] == ["Your browser blocked the pop-up; allow pop-ups for this page."]
    assert out["notFinalizedButtons"] == 0
