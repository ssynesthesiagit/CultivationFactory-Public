"""Lead-only visual text check; prepare the scratch table at the repayment prompt.

Run outside the sandbox with CF_HUNT32_BROWSER_URL set to that scratch table URL.
Without the explicit opt-in this test neither imports Playwright nor launches a GUI.
It checks the displayed explanation and leaves the pending decision untouched.
"""
import os

import pytest


@pytest.mark.skipif(not os.environ.get("CF_HUNT32_BROWSER_URL"), reason="lead must run browser checks outside the sandbox")
def test_repayment_prompt_explains_cost_and_restrictions():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runner:
        browser = runner.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.goto(os.environ["CF_HUNT32_BROWSER_URL"])
            page.get_by_text("Pay the Second Back", exact=False).first.wait_for()
            text = page.locator("body").inner_text()
            for phrase in ("Borrowed Second", "2 Time Debt", "Speed", "Reactions", "next turn", "Forced movement"):
                assert phrase in text
        finally:
            browser.close()
