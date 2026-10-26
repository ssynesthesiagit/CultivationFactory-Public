"""Opt-in production choice-dialog check; the lead runs outside the sandbox.

HUNT12_BROWSER=1 enables Chromium. No app server, live data or network is used.
"""
import os
from pathlib import Path
import re
import pytest
from tests.hunt12_support import FOE, candidate, fight, hit_dice, send
from tests.test_hunt12_palm import PALM, IRON


@pytest.mark.skipif(os.environ.get("HUNT12_BROWSER") != "1",
                    reason="Lead must run HUNT12_BROWSER=1 outside the sandbox")
def test_actual_palm_choice_dialog(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    combat, table, mid = fight(tmp_path, [PALM, IRON])
    hit_dice(monkeypatch)
    strike = candidate(combat, mid, lambda c: ".natural.iron_fist" in c.source_definition_id and "#" not in c.source_definition_id and tuple(c.target_ids) == (FOE,))
    result = send(combat, table, mid, strike)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    static = Path(__file__).resolve().parents[1] / "static/tabletop"
    html = (static / "tabletop.html").read_text()
    dialog = re.search(r'<dialog id="ttReaction".*?</dialog>', html, re.S).group()
    javascript = (static / "tabletop.js").read_text()
    functions = javascript[javascript.index("function decisionText(prompt)"):javascript.index("// The Items panel")]
    with playwright.sync_playwright() as browser_api:
        browser = browser_api.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(dialog)
            page.add_script_tag(content="""
                const $ = selector => document.querySelector(selector);
                const escapeHtml = text => {const el = document.createElement('span'); el.textContent = text || ''; return el.innerHTML;};
                const toast = text => {throw new Error(text);};
            """ + functions)
            page.evaluate("prompt => {window.answer = askReaction(prompt);}", prompt)
            text = page.locator("#ttReactionText").inner_text()
            assert "Severing Palm" in text and "4 Stamina" in text and "Unarmed Strike" in text
            assert page.locator("[data-option]").count() == 5
            page.locator('[data-option="breath"]').click()
            assert page.evaluate("window.answer") == {"selection": "USE", "option_ids": ["breath"]}
            page.evaluate("prompt => {window.answer = askReaction(prompt);}", prompt)
            page.locator('[data-answer="DECLINE"]').click()
            assert page.evaluate("window.answer") == "DECLINE"
        finally:
            browser.close()
