"""Lead-only smoke check against an authorized scratch server outside the sandbox."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("SOL56_BROWSER") != "1", reason="lead runs outside sandbox")


def test_saved_table_renders_without_browser_errors():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(os.environ["SOL56_SCRATCH_TABLE_URL"])
        page.wait_for_load_state("networkidle")
        assert page.locator("body").inner_text().strip()
        assert not errors
        browser.close()
