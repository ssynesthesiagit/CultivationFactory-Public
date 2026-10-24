"""Lead-only screenshot gate, against disposable real fights outside the sandbox.

Provide VARIANTS1_TABLE_URL, VARIANTS1_SHEET_URL, VARIANTS1_PLAY_URL and
VARIANTS1_SETUP_URL (the pre-fight setup screen), each
showing a manual caster who owns Darkvision and Persistent Meld, with >=4 Qi.
VARIANTS1_RUN_BROWSER=1 opts in. No browser runs in ordinary/public tests.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("VARIANTS1_RUN_BROWSER") != "1",
    reason="Lead must run the screenshot gate outside the sandbox",
)


@pytest.mark.parametrize("surface", ["SETUP", "TABLE", "SHEET", "PLAY"])
def test_darkvision_is_one_family_with_four_reachable_choices(surface, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    url = os.environ.get("VARIANTS1_" + surface + "_URL")
    assert url, "Set the disposable " + surface + " URL before opting in"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url)
            family = page.locator(".action-variant-group").filter(
                has=page.locator("summary", has_text="Meld: Darkvision"))
            expect(family).to_have_count(1)
            family.locator("summary").click()
            choices = family.locator("input[type=checkbox]") if surface == "SETUP" else family.locator("button").filter(has_text="Standard").or_(
                family.locator("button").filter(has_text="Persistent")).or_(
                family.locator("button").filter(has_text="Stronger"))
            expect(choices).to_have_count(4)
            expect(family).to_contain_text("2 Qi")
            expect(family).to_contain_text("4 Qi")
            expect(family).not_to_contain_text("(2 CP)")
            for button in choices.all():
                expect(button).to_be_visible()
                expect(button).to_be_enabled()
            page.screenshot(path=str(tmp_path / ("variants1-" + surface.lower() + ".png")), full_page=True)
        finally:
            browser.close()
