"""Lead-only rendered check against a disposable table outside the sandbox.

Set FIX15_BROWSER_TABLE_URL to a copied fight with Flowing Response's step-away
setting active. The test reads and hovers only; it does not mutate a live fight.
"""
import os
import pytest


@pytest.mark.skipif(not os.environ.get("FIX15_BROWSER_TABLE_URL"), reason="lead must run Chromium outside sandbox")
def test_rendered_setting_pill_hover():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.goto(os.environ["FIX15_BROWSER_TABLE_URL"])
            pill = page.locator(".tt-pill.is-condition").filter(has_text="Flowing Response: step away").first
            pill.wait_for()
            pill.hover()
            title = pill.get_attribute("title") or ""
            assert "5 feet" in title and "Opportunity Attacks" in title
            assert "Rule description unavailable" not in title
        finally:
            browser.close()
