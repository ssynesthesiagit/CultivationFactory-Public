"""Lead-only browser check; run outside the sandbox against a disposable scratch fight."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("BLOSSOMTARGET_RUN_BROWSER") != "1" or not os.environ.get("BLOSSOMTARGET_TABLE_URL"),
    reason="Lead runs this Chromium check outside the sandbox against a disposable scratch fight",
)


def test_clicking_an_enemy_token_aims_cultivate_blossom_at_its_square():
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.goto(os.environ["BLOSSOMTARGET_TABLE_URL"])
            page.get_by_role("button", name="Cultivate Blossom", exact=True).click()
            page.locator(".tt-token").filter(has_text="Sun Taitian").click()
            expect(page.get_by_text("cultivated a Blossom", exact=False)).to_be_visible()
            expect(page.get_by_text("That token is not a legal target for this action.")).to_have_count(0)
        finally:
            browser.close()
