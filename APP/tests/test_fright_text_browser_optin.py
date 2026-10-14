"""Lead-only check of a scratch table containing a Frightened fighter.

Run outside the sandbox: N4_BROWSER=1 N4_TABLE_URL=<scratch table URL>.
This checks condition text only; movement notices await the engine reason seam.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("N4_BROWSER") != "1",
                              reason="Lead must run browser checks outside the sandbox")


def test_frightened_condition_pill_rendering():
    from playwright.sync_api import sync_playwright

    url = os.environ["N4_TABLE_URL"]
    assert url.startswith(("http://127.0.0.1:", "http://localhost:"))
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.goto(url)
            pill = page.locator(".tt-pill.is-condition").filter(has_text="Frightened").first
            pill.wait_for(state="visible")
            text = pill.get_attribute("title")
            assert "can't willingly move closer" in text
            assert "(GM)" not in text
        finally:
            browser.close()
