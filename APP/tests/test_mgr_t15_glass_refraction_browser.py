"""Opt-in visual entry check. Lead runs outside the sandbox on a test table."""
import os

import pytest


@pytest.mark.skipif(not os.environ.get('CF_REFRACTION_BROWSER_URL'),
                    reason='Lead must supply a disposable table URL and run outside the sandbox')
def test_owner_scene_declaration_is_reachable():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page()
            page.goto(os.environ['CF_REFRACTION_BROWSER_URL'])
            page.get_by_role('button', name='Private scene declarations', exact=True).click()
            dialog = page.get_by_role('dialog')
            assert dialog.get_by_role('heading', name='Private scene and character declarations').is_visible()
            assert dialog.get_by_role('button', name='Record this private declaration').is_visible()
            assert dialog.get_by_label('Scene being entered').input_value() == ''
        finally:
            browser.close()
