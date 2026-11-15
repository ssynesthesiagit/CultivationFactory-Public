"""Lead-only screenshot gate, run outside the sandbox.

VARIANTS1_RUN_BROWSER=1 opts in. No browser runs in ordinary/public tests.
"""
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("VARIANTS1_RUN_BROWSER") != "1",
    reason="Lead must run the screenshot gate outside the sandbox",
)


def test_folded_table_families_keep_card_width_and_sheet_fills_column(tmp_path):
    from playwright.sync_api import sync_playwright

    static = Path(__file__).resolve().parents[1] / "static" / "tabletop"
    shared = (static / "action-variants.css").read_text()
    table = (static / "tabletop.css").read_text()
    family = ('<details class="attack-group action-variant-group"><summary>'
              'Thunderwood Dao LongUnbreakableWeaponName</summary>'
              '<div class="attack-chips"><button data-variant-choice="action.one">Use</button></div></details>')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 800, "height": 600})
            page.set_content('<style>' + shared + table + '</style>'
                '<div class="tt-actionbar"><div class="tt-ab-groups"><div class="tt-ab-group">'
                '<h3>No action</h3><div class="tt-ab-buttons">'
                '<div class="tt-action-card tt-attack-group">Attack</div>' + family * 6 +
                '</div></div></div></div>'
                '<div id="sheet" style="width: 320px">' + family + '</div>')
            cards = page.locator(".tt-ab-buttons > .action-variant-group")
            assert cards.count() == 6
            widths = cards.evaluate_all("(nodes) => nodes.map(n => n.getBoundingClientRect().width)")
            attack_width = page.locator(".tt-attack-group").bounding_box()["width"]
            assert all(width >= attack_width for width in widths)
            assert cards.first.locator("summary").evaluate(
                "(n) => getComputedStyle(n).overflowWrap") == "normal"
            assert cards.first.evaluate("(n) => getComputedStyle(n).flexShrink") == "0"
            assert page.locator(".tt-ab-groups").evaluate("(n) => n.scrollWidth > n.clientWidth")
            assert page.locator(".tt-actionbar").bounding_box()["height"] < 160
            sheet = page.locator("#sheet .action-variant-group")
            assert abs(sheet.bounding_box()["width"] - 320) < 1
            assert sheet.locator("summary").evaluate("(n) => getComputedStyle(n).overflowWrap") == "anywhere"
            cards.first.locator("summary").click()
            assert cards.first.locator("[data-variant-choice]").is_visible()
            page.screenshot(path=str(tmp_path / "bar-family-width.png"), full_page=True)
        finally:
            browser.close()
