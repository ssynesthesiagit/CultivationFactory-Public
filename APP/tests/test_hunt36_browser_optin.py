"""Lead-only rendered Hidden Strike dialog; enable HUNT36_BROWSER=1 outside the sandbox.

Uses synthetic scratch data and the production dialog JavaScript; no server.
"""
import os
from pathlib import Path
import re
import pytest


@pytest.mark.skipif(os.environ.get("HUNT36_BROWSER") != "1", reason="Lead must run browser checks outside the sandbox")
def test_hidden_strike_all_riders_in_production_dialog(tmp_path):
    from playwright.sync_api import sync_playwright
    from tests.hunt36_support import setup_hidden, weapon

    combat, table, mid = setup_hidden(tmp_path, smoke=True)
    state = table.state(mid)
    candidate = weapon(combat, mid)
    menu = state["menu"]
    result = table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], [])
    assert result["status"] == "REACTION_REQUIRED"
    static = Path(__file__).resolve().parents[1] / "static/tabletop"
    dialog = re.search(r'<dialog id="ttReaction".*?</dialog>', (static / "tabletop.html").read_text(), re.S).group()
    javascript = (static / "tabletop.js").read_text()
    functions = javascript[javascript.index("function decisionText(prompt)"):javascript.index("// The Items panel")]
    with sync_playwright() as api:
        browser = api.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(dialog)
            page.add_script_tag(content="""
                const $ = selector => document.querySelector(selector);
                const escapeHtml = text => {const el = document.createElement('span'); el.textContent = text || ''; return el.innerHTML;};
                const toast = text => {throw new Error(text);};
            """ + functions)
            page.evaluate("prompt => {window.answer = askReaction(prompt);}", result["reaction"])
            text = page.locator("#ttReactionText").inner_text()
            assert "Hidden Strike" in text and "Visiting Fighter" in text and "no resource cost" in text
            assert page.locator("[data-option]").count() == 5
            for label in ("Silent Withdrawal", "Sever Awareness", "Vanishing Posture", "Misleading Impact", "Smoke Mark"):
                assert label in page.locator("#ttReaction").inner_text()
            page.locator('[data-option="smoke"]').click()
            assert page.evaluate("window.answer") == {"selection": "USE", "option_ids": ["smoke"]}
        finally:
            browser.close()
