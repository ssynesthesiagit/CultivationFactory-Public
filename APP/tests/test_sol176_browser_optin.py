"""Lead-only visual smoke check against a scratch table paused for displacement.

Outside the sandbox, run SOL176_BROWSER=1 SOL176_TABLE_URL=<scratch table URL>
SOL176_SUBJECT_NAME=<target display name> pytest tests/test_sol176_browser_optin.py.
Prepare Spatial Displacement's destination prompt before running this check.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("SOL176_BROWSER") != "1",
                              reason="Lead must run browser checks outside the sandbox")


def test_subject_destination_is_shown_on_the_main_map():
    from playwright.sync_api import sync_playwright

    url = os.environ["SOL176_TABLE_URL"]
    subject = os.environ["SOL176_SUBJECT_NAME"]
    assert url.startswith(("http://127.0.0.1:", "http://localhost:"))
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.goto(url)
            page.locator("body.is-map-pick").wait_for(state="visible")
            hint = page.locator("#ttHint")
            hint.wait_for(state="visible")
            assert "Spatial Displacement" in hint.inner_text()
            assert subject in hint.inner_text()
            assert "Leave them here" in hint.inner_text()
        finally:
            browser.close()
