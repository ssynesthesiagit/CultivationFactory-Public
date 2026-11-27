"""Lead-only browser check against a disposable manual Iron Fist table.

Set SOL117_BROWSER_URL to its table URL. Never enable this inside the sandbox.
"""
import os
import pytest


@pytest.mark.skipif(not os.environ.get('SOL117_BROWSER_URL'), reason='lead must run Chromium outside sandbox')
def test_browser_modifier_toggle_never_attacks():
    from playwright.sync_api import sync_playwright
    url = os.environ['SOL117_BROWSER_URL']
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page()
            with page.expect_response(lambda r: '/state?' in r.url) as initial:
                page.goto(url)
            before = initial.value.json()
            options = page.locator('.tt-ab-group').filter(has=page.get_by_role('heading', name='Options', exact=True))
            options.get_by_role('button', name='Iron Fist attack', exact=False).click()
            panel = page.locator('#ttShape')
            assert panel.get_by_text('Nullifying Strike', exact=False).count() == 1
            with page.expect_response(lambda r: '/state?' in r.url) as changed:
                panel.get_by_role('button', name='Turn on', exact=True).click()
            after = changed.value.json()
            for actor in before['presentation']['actors']:
                other = next(a for a in after['presentation']['actors'] if a['entity_id'] == actor['entity_id'])
                for field in ('hit_points', 'resources', 'turn_state'):
                    assert other.get(field) == actor.get(field)
            assert any(' + Nullifying Strike:' in group['label'] for group in after['menu']['actions'])
        finally:
            browser.close()
