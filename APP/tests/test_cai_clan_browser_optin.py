"""Lead-only hover check against a prepared, disposable CL15 Cai table.

Run outside the sandbox with SOL118_RUN_BROWSER=1 and SOL118_TABLE_URL pointing
to the scratch table paused on the Administrator's turn, before using an action.
This check only reads and hovers; it never clicks an action or changes a fight.
"""
import os
import re

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SOL118_RUN_BROWSER") != "1",
    reason="Lead must run SOL118 browser checks outside the sandbox",
)


def test_cai_table_action_hovers_are_readable():
    from playwright.sync_api import sync_playwright

    url = os.environ["SOL118_TABLE_URL"]
    assert url.startswith(("http://127.0.0.1:", "http://localhost:"))
    with sync_playwright() as runner:
        browser = runner.chromium.launch(
            executable_path="/usr/bin/chromium", args=["--no-sandbox"],
        )
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            saber = page.get_by_role("button", name=re.compile("^Judgment Saber")).first
            saber.wait_for()
            saber.hover()
            text = page.locator("body").inner_text()
            assert "1 Qi" in text and "Radiant" in text
            layer = page.get_by_role("button", name=re.compile("^Empyreal Layer")).first
            layer.hover()
            text = page.locator("body").inner_text()
            assert "2 Qi" in text and "Concentration" in text
            assert "Rule description unavailable" not in text
            assert not errors
        finally:
            browser.close()
