"""Opt-in UI guard. Lead runs outside the sandbox against a disposable table.

CF_NUDGE_BROWSER_URL must open a prepared CL10+ Spirit character's sheet that
has not acquired Nudge. This test checks the form and submits no acquisition.
"""
import os
import pytest


@pytest.mark.skipif(not os.environ.get('CF_NUDGE_BROWSER_URL'), reason='Lead-only browser check; set CF_NUDGE_BROWSER_URL outside the sandbox')
def test_feature_access_form_requires_a_source():
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page()
            page.goto(os.environ['CF_NUDGE_BROWSER_URL'])
            page.get_by_role('button', name='Grow', exact=True).click()
            source = page.get_by_label('Nudge Consequence: source granting access')
            source.wait_for()
            learn = source.locator('..').get_by_role('button', name='Learn', exact=True)
            assert learn.is_disabled()
            source.fill('Inherited Secret scripture: regression source')
            assert learn.is_enabled()
        finally:
            browser.close()
