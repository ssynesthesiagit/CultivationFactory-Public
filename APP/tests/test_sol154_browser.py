"""Opt-in visual evidence; lead must run outside the restricted sandbox."""
import os
import pytest


@pytest.mark.skipif(not os.environ.get('SOL154_BROWSER_URL'),reason='Lead runs Chromium outside sandbox with SOL154_BROWSER_URL')
def test_bamboo_table_visual_evidence(tmp_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        try:
            page=browser.new_page(viewport={'width':1440,'height':1000})
            page.goto(os.environ['SOL154_BROWSER_URL'],wait_until='networkidle')
            page.locator('.tt-board').wait_for(state='visible')
            assert page.locator('.tt-zone-ground').count()>0
            page.screenshot(path=os.environ.get('SOL154_BROWSER_SCREENSHOT',str(tmp_path/'sol154-bamboo.png')),full_page=True)
        finally:
            browser.close()
