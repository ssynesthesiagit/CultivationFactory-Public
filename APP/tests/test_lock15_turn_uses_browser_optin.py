"""Lead-only rendered usage wording check against a prepared scratch Table."""
import os
import pytest

@pytest.mark.skipif(os.environ.get('LOCK15_RUN_BROWSER') != '1', reason='Lead runs opt-in Chromium outside the sandbox')
def test_usage_refresh_is_rendered_for_prepared_clock_fixture():
    url=os.environ['LOCK15_USAGE_TABLE_URL']
    from playwright.sync_api import expect, sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        try:
            page=browser.new_page();page.goto(url);page.wait_for_selector('#ttViewport')
            button=page.get_by_role('button',name='Practice blade',exact=False).first
            button.hover()
            expect(page.locator('body')).to_contain_text("next creature's turn", timeout=1500)
            expect(page.locator('body')).to_contain_text('your turn only', timeout=1500)
        finally:browser.close()
