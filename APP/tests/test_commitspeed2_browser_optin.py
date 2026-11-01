"""Lead-only visual check against a disposable, all-manual copied fight.

Serve this checkout outside the worker sandbox, open/prepare its human table,
with CF_EMBEDMENU=0 and no MODEL seats, then set CF_COMMITSPEED2_BROWSER=1 and
CF_COMMITSPEED2_TABLE_URL to that scratch table with at least two active manual fighters.
No production match or model server is part of this check.
"""
import os

import pytest


@pytest.mark.skipif(os.environ.get('CF_COMMITSPEED2_BROWSER') != '1',
                   reason='Lead must run Chromium outside the worker sandbox')
def test_committed_table_renders_before_next_choices_are_available():
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page()
            page.goto(os.environ['CF_COMMITSPEED2_TABLE_URL'])
            expect(page.locator('#ttViewerChange')).to_be_enabled(timeout=60000)
            if not page.locator('#ttViewerPicker').is_visible():
                page.locator('#ttViewerChange').click()
            page.locator('#ttViewerGM').click()
            button = page.get_by_role('button', name='End turn', exact=True)
            expect(button).to_be_visible(timeout=60000)
            page.locator('.tt-token.is-current').click()
            previous_name = page.locator('#ttInspector h2').inner_text()
            # Make the next menu temporarily unavailable. The acknowledgement
            # and new round/actor must still render, and stale buttons vanish.
            page.route('**/state?*', lambda route: route.fulfill(status=503,
                content_type='application/json', body='{"error":{"message":"Test menu delayed"}}'))
            with page.expect_response(lambda response: response.url.endswith('/act')) as acknowledgement:
                button.click()
            result = acknowledgement.value.json()
            assert result['status'] == 'COMMITTED' and result['state']['menu'] is None
            assert result['state']['menu_pending']['state_version'] > acknowledgement.value.request.post_data_json['state_version']
            presentation = result['state']['presentation']
            next_actor = next(actor for actor in presentation['actors']
                              if actor['entity_id'] == presentation['current_actor_id'])
            assert next_actor['display_name'] != previous_name, 'Prepare two distinct human fighters for this check'
            expect(page.locator('body.is-working')).to_have_count(0, timeout=5000)
            expect(page.locator('#ttActionBar')).to_contain_text('Loading your choices')
            expect(button).to_have_count(0)
            page.unroute('**/state?*')
            expect(button).to_be_visible(timeout=60000)
            expect(page.locator('#ttInspector h2')).to_have_text(next_actor['display_name'])
            expect(page.locator('.tt-token.is-selected .tt-token-name')).to_have_text(next_actor['display_name'])
        finally:
            browser.close()
