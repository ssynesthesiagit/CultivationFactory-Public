"""Opt-in rendered loading checks for disposable, manually controlled fights.

Set MENUSPEED6_DESKTOP_URL and/or MENUSPEED6_PLAY_URL to a prepared test fight.
Requires Playwright and /usr/bin/chromium in an environment that permits
browser execution; desktop and phone layouts are checked separately.
"""
import os

import pytest


@pytest.mark.parametrize('variable,width,height', [
    ('MENUSPEED6_DESKTOP_URL', 1440, 900), ('MENUSPEED6_PLAY_URL', 390, 844)])
def test_choices_loading_is_visible_until_menu_arrives(variable, width, height):
    url = os.environ.get(variable)
    if not url:
        pytest.skip('Set ' + variable + ' to a disposable fight URL to enable this browser check')
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page(viewport={'width': width, 'height': height})
            page.goto(url)
            # Prepare the scratch URL/viewer before this check. The next state
            # request is held pending while the commit acknowledgement renders.
            end = page.get_by_role('button', name='End turn', exact=True)
            expect(end).to_be_visible(timeout=60000)
            held = []
            page.route('**/state?*', lambda route: held.append(route))
            end.click()
            loading = page.get_by_role('status').filter(has_text='Loading your choices')
            expect(loading).to_be_visible(timeout=5000)
            expect(loading.locator('.tt-choices-spinner')).to_be_visible()
            expect(end).to_have_count(0)
            page.unroute('**/state?*')
            for route in held:
                route.continue_()
            expect(loading).to_have_count(0, timeout=60000)
            expect(end).to_be_visible()
        finally:
            browser.close()
