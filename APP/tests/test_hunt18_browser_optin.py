"""Lead-only rendered check of a scratch table paused at Shadow Ward.

Run outside the sandbox with HUNT18_RUN_BROWSER=1 and HUNT18_TABLE_URL.
"""
import os
import re

import pytest

pytestmark = pytest.mark.skipif(os.getenv("HUNT18_RUN_BROWSER") != "1",
                              reason="Lead must run browser checks outside the sandbox")


def test_shadow_ward_rendered_summary():
    from playwright.sync_api import sync_playwright
    url = os.environ["HUNT18_TABLE_URL"]
    assert url.startswith(("http://127.0.0.1:", "http://localhost:"))
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            decision = page.locator("#ttReaction[open] #ttReactionText")
            decision.get_by_text("Shadow Ward", exact=True).wait_for()
            text = decision.inner_text()
            assert re.search(r"Reduce the triggering damage to you or an ally within 30 feet by [123]d8 [+-] \d+", text)
            assert "This protects against this damage only." in text
            cost = decision.locator("p").filter(has_text="Cost now:").inner_text()
            assert "Reaction" in cost and re.search(r"\b1\b", cost)
            assert "| CL |" not in text and "| --- |" not in text
            assert not errors
        finally:
            browser.close()
