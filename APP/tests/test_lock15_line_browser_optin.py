"""Lead-only check: prepare the Judgment Ray pillar fixture on a scratch Table."""
import os
import pytest

@pytest.mark.skipif(os.environ.get('LOCK15_RUN_BROWSER') != '1', reason='Lead runs opt-in Chromium outside the sandbox')
def test_pillar_blocks_rendered_judgment_ray_overlay():
    url=os.environ['LOCK15_LINE_TABLE_URL']
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        try:
            page=browser.new_page();page.goto(url);page.wait_for_selector('#ttViewport')
            page.get_by_role('button',name='Judgment Ray',exact=False).first.click()
            # The aim marker at (11,4) is a diamond centered at (11.5,4.5).
            page.locator('path.tt-mark-center[d^="M11.5 4.18"]').hover(force=True)
            page.wait_for_selector('.tt-mark-area')
            assert page.locator('.tt-mark-area[x="11"][y="4"]').count()==0
            assert page.locator('.tt-mark-area[x="6"][y="5"]').count()==1
        finally:browser.close()
