"""Lobby checks. Browser launch is strictly opt-in for the lead outside the sandbox."""
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_team_save_node_handlers():
    """Load the real row module added by tt/prefight-tooltips 907a1a08
    (approving PREFIGHTr2.review.md), retaining all saved-team assertions.
    """
    subprocess.run(["node", str(ROOT / "tests/team_saves.cjs")], check=True, timeout=30)


@pytest.mark.skipif(os.getenv("N4_BROWSER") != "1", reason="Lead must run outside sandbox with N4_BROWSER=1")
def test_team_save_browser_lobby():
    playwright = pytest.importorskip("playwright.sync_api")
    source = (ROOT / "static/tabletop/tabletop.js").read_text()
    names = ["prefightCost", "loadPrefight", "buildFightBuilder", "updatePresetSaveButtons", "savedTeamMembers", "fillSavedTeam", "singleTeamBar", "presetBar"]
    functions = []
    for name in names:
        start = source.index(f"function {name}(")
        if source[max(0, start - 6):start] == "async ":
            start -= 6
        functions.append(source[start:source.index("\n}", start) + 2])
    # Mount the production builder and its handlers in a real DOM, with test-only API data.
    bootstrap = """
      const $ = s => document.querySelector(s), FACTORY = 'actor:factory.', POOL_NAMES = {};
      const enc = encodeURIComponent, escapeHtml = s => String(s), toast = s => {window.notice = s;};
      let builderBuilt = false;
      // The fighter picker (OPUSUI2) is not loaded here; a slot's fighter is still its hidden dropdown's value.
      const fighterPicker = {open: options => { window.pickerOptions = options; }, fillSlotFace() {}};
      const applyPick = (entry, pick) => { entry.who.value = pick.pid; if (pick.mode) entry.control.value = pick.mode; entry.who.dispatchEvent(new Event('change')); };
      window.savedTeams = []; window.setups = [];
      window.prefightMode = 'ready'; window.prefightPending = [];
      const prefightData = {options:[{action_id:'cast',name:'Ward',costs:[],duration:'10 minutes'}],picks:['cast'],max:2};
      async function api(url, options = {}) {
        if (url.endsWith('factory-characters')) return [{project_id:'a',display_name:'Alice'},{project_id:'b',display_name:'Bob'}];
        if (url.endsWith('/maps')) return {maps:[], builtin:[{arena_id:'arena',display_name:'Field'}]};
        if (url.includes('factory-prefight')) {
          if (prefightMode === 'hold') return new Promise(resolve => prefightPending.push(resolve));
          if (prefightMode === 'fail') throw Error('offline');
          return prefightData;
        }
        const rows = url.includes('saved-teams') ? savedTeams : setups;
        if (options.method === 'DELETE') {rows.splice(rows.findIndex(r=>r.name===decodeURIComponent(url.split('/').pop())),1); return {};}
        if (options.body) {const row=options.body.preset; const i=rows.findIndex(r=>r.name===row.name); if(i>=0) rows.splice(i,1); rows.push(row); return row;}
        return url.includes('saved-teams') ? {teams:rows} : {presets:rows};
      }
    """
    html = '<div id="ttBuilder"></div><script>' + bootstrap + "\n".join(functions) + '\nbuildFightBuilder().then(()=>window.ready=true);</script>'
    def choose(select, value):
        # The fighter dropdown is hidden behind the picker's slot face now; set it the way a pick does.
        select.evaluate("(el, value) => { el.value = value; el.dispatchEvent(new Event('change')); }", value)

    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"], headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.fulfill(body=html, content_type="text/html"))
            page.goto("http://team-saves.test/")
            page.wait_for_function("window.ready === true")
            panels = page.locator(".tt-team")
            assert panels.count() == 2
            choose(panels.nth(0).locator(".tt-slot select").nth(0), "a")
            panels.nth(0).locator(".tt-prefight input").check()
            page.once("dialog", lambda dialog: dialog.accept("First"))
            panels.nth(0).locator("[data-team-save]").click()
            page.wait_for_function("savedTeams.length === 1")
            panels.nth(1).locator("[data-team]").select_option("First")
            panels.nth(1).locator("[data-team-load]").click()
            assert panels.nth(1).locator(".tt-slot select").nth(0).input_value() == "a"
            assert panels.nth(1).locator(".tt-slot select").nth(1).input_value() == "MANUAL"
            playwright.expect(panels.nth(1).locator(".tt-prefight input")).to_be_checked()
            choose(panels.nth(1).locator(".tt-slot select").nth(0), "b")
            panels.nth(1).locator(".tt-slot select").nth(1).select_option("LOCAL_AUTO")
            page.once("dialog", lambda dialog: dialog.accept("Second"))
            panels.nth(1).locator("[data-team-save]").click()
            page.wait_for_function("savedTeams.length === 2")
            panels.nth(0).locator("[data-team]").select_option("Second")
            panels.nth(0).locator("[data-team-load]").click()
            panels.nth(1).locator("[data-team]").select_option("First")
            panels.nth(1).locator("[data-team-load]").click()
            assert panels.nth(0).locator(".tt-slot select").nth(0).input_value() == "b"
            assert panels.nth(1).locator(".tt-slot select").nth(0).input_value() == "a"
            assert page.locator("[data-preset-save]").count() == 1
            page.once("dialog", lambda dialog: dialog.accept())
            panels.nth(1).locator("[data-team-delete]").click()
            page.wait_for_function("savedTeams.length === 1")
            assert page.locator('[data-team] option[value="First"]').count() == 0
            # Delayed and failed responses must not silently save AI defaults.
            for picks in (["cast"], []):
                page.evaluate("""picks => {
                  savedTeams.find(row => row.name === 'Second').members[0].prefight = picks;
                  prefightMode = 'hold'; window.notice = '';
                }""", picks)
                panels.nth(0).locator("[data-team]").select_option("Second")
                panels.nth(0).locator("[data-team-load]").click()
                page.wait_for_function("prefightPending.length === 1")
                playwright.expect(panels.nth(0).locator("[data-team-save]")).to_be_disabled()
                playwright.expect(page.locator("[data-preset-save]")).to_be_disabled()
                playwright.expect(panels.nth(1).locator("[data-team-save]")).to_be_enabled()
                before = page.evaluate("savedTeams.length")
                page.evaluate("document.querySelector('[data-team-save]').click()")
                assert page.evaluate("savedTeams.length") == before
                assert "Loaded" not in page.evaluate("window.notice")
                page.evaluate("prefightMode = 'ready'; prefightPending.splice(0).forEach(resolve => resolve(prefightData))")
                playwright.expect(panels.nth(0).locator("[data-team-save]")).to_be_enabled()
                label = "Delayed ward" if picks else "Delayed none"
                page.once("dialog", lambda dialog, label=label: dialog.accept(label))
                panels.nth(0).locator("[data-team-save]").click()
                page.wait_for_function("name => savedTeams.some(row => row.name === name)", arg=label)
                assert page.evaluate("name => savedTeams.find(row => row.name === name).members[0].prefight", label) == picks
                page.evaluate("prefightMode = 'fail'; window.notice = ''")
                panels.nth(0).locator("[data-team]").select_option("Second")
                panels.nth(0).locator("[data-team-load]").click()
                page.wait_for_function("window.notice.includes('could not restore')")
                playwright.expect(panels.nth(0).locator("[data-team-save]")).to_be_enabled()
                playwright.expect(panels.nth(0).locator(".tt-prefight")).to_contain_text("Saved choices have been kept")
                label = "Failed ward" if picks else "Failed none"
                page.once("dialog", lambda dialog, label=label: dialog.accept(label))
                panels.nth(0).locator("[data-team-save]").click()
                page.wait_for_function("name => savedTeams.some(row => row.name === name)", arg=label)
                assert page.evaluate("name => savedTeams.find(row => row.name === name).members[0].prefight", label) == picks
        finally:
            browser.close()
