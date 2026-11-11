"""Opt-in actual Chromium DOM check; the lead runs this outside the sandbox."""
import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.skipif(os.environ.get("SOL36_BROWSER") != "1", reason="lead: set SOL36_BROWSER=1 outside the sandbox")
def test_sheet_vitals_and_defenses_refresh_together_in_real_dom():
    playwright = pytest.importorskip("playwright.sync_api")
    source = json.loads(subprocess.check_output(
        ["node", str(Path(__file__).with_name("sheet_live_render_source.cjs"))], text=True))
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"], headless=True)
        try:
            page = browser.new_page()
            ids = ("abilities", "vitals", "defenses", "link-pill", "link-text", "conn-banner", "turn-banner")
            page.set_content("".join(f'<div id="{name}"></div>' for name in ids))
            page.add_script_tag(content=source)
            page.evaluate("renderStats(); renderLive();")
            for ac, speed in ((12, 30), (14, 5), (17, 0)):
                page.evaluate("([ac, speed]) => { state.actor = {armor_class: ac, speed_ft: speed}; renderLive(); }", [ac, speed])
                assert page.locator("#vitals .ac .stat-big").inner_text() == str(ac)
                assert page.locator("#defenses summary").inner_text() == f"Armor Class {ac}"
                walking = page.locator("#vitals .stat").filter(has=page.locator(".stat-label", has_text="Walking"))
                assert walking.locator(".stat-big").inner_text() == f"{speed}ft"
        finally:
            browser.close()
