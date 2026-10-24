"""Phone-only browser check for a pending Blossom square choice on /play.

Opt-in: never starts a browser unless SQUAREPICK1_BROWSER=1 is set and SQUAREPICK1_URL points
at a disposable scratch /play?match=... page whose square choice is already pending.
"""
import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('SQUAREPICK1_BROWSER') != '1' or not os.environ.get('SQUAREPICK1_URL'),
    reason='Lead must run outside the sandbox against a disposable scratch fight',
)


def test_phone_map_answers_pending_blossom_square():
    from playwright.sync_api import expect, sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page(viewport={'width': 412, 'height': 915}, has_touch=True)
            url = os.environ['SQUAREPICK1_URL'].replace('/tabletop?', '/play?')
            page.goto(url)
            expect(page.locator('#reactionCard')).to_be_visible()
            expect(page.locator('#reactionBody')).to_contain_text(re.compile('Cultivate Blossom', re.I))
            screenshot_dir = Path(os.environ['SQUAREPICK1_SCREENSHOTS'])
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_dir / 'phone.png'), full_page=True)
            box = page.locator('#map').bounding_box()
            with page.expect_request(lambda request: request.url.endswith('/act') or request.url.endswith('/auto-step')) as sent:
                page.touchscreen.tap(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            body = sent.value.post_data_json
            assert any(answer.get('option_ids') for answer in body['reactions'])
        finally:
            browser.close()
