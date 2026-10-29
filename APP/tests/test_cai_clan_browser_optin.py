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
    from playwright.sync_api import expect, sync_playwright

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
            expect(page.locator("body")).to_contain_text("1 Qi", timeout=1500)
            expect(page.locator("body")).to_contain_text("Radiant", timeout=1500)
            layer = page.get_by_role("button", name=re.compile("^Empyreal Layer")).first
            layer.hover()
            expect(page.locator("body")).to_contain_text("2 Qi", timeout=1500)
            expect(page.locator("body")).to_contain_text("Concentration", timeout=1500)
            expect(page.locator("body")).not_to_contain_text("Rule description unavailable")
            assert not errors
        finally:
            browser.close()
