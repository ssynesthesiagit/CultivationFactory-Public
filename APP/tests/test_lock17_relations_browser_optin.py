"""Lead-only smoke after the rider UI exposes a prepared Neutral fight."""
import os

import pytest


@pytest.mark.skipif(os.environ.get('LOCK17_RUN_BROWSER') != '1', reason='Lead opt-in; no browser in Astra lane')
def test_neutral_fighter_is_visible_on_table():
    from playwright.sync_api import sync_playwright
    url = os.environ['LOCK17_RELATIONS_TABLE_URL']
    name = os.environ['LOCK17_NEUTRAL_DISPLAY_NAME']
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        page = browser.new_page()
        page.goto(url)
        page.get_by_text(name, exact=True).first.wait_for(state='visible')
        page.get_by_text('Neutral', exact=True).first.wait_for(state='visible')
        browser.close()
