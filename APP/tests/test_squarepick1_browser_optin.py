"""Lead-only screenshots against an already paused disposable Blossom fight.

Never starts a browser unless explicitly enabled. Point the URL at the scratch
server's /tabletop?match=... or /play?match=... with the initial square choice
already pending (the owner copy must not be served from its original location).
"""
import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('SQUAREPICK1_BROWSER') != '1' or not os.environ.get('SQUAREPICK1_URL'),
    reason='Lead must run outside the sandbox against a disposable scratch fight',
)


@pytest.mark.parametrize('mobile', [False, True], ids=['desktop', 'phone'])
def test_pending_blossom_map_screenshot_and_phone_tap(mobile):
    from playwright.sync_api import expect, sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page(viewport={'width': 412, 'height': 915} if mobile
                                    else {'width': 1440, 'height': 1000}, has_touch=mobile)
            url = os.environ['SQUAREPICK1_URL']
            if mobile:
                url = url.replace('/tabletop?', '/play?')
            page.goto(url)
            expect(page.locator('body')).to_have_class(re.compile(r'is-map-pick'))
            expect(page.locator('#ttReaction')).not_to_be_visible()
            expect(page.locator('#ttHint')).to_contain_text('Cultivate Blossom')
            expect(page.locator('.tt-mark-move').first).to_be_visible()
            assert not page.locator('#ttReaction .tt-choice-list').is_visible()
            point = page.evaluate('''() => {
              const v = document.querySelector('#ttViewport').getBoundingClientRect();
              for (const mark of document.querySelectorAll('.tt-mark-move')) {
                const b = mark.getBoundingClientRect(), x = b.x + b.width / 2, y = b.y + b.height / 2;
                if (x > v.left + 5 && x < v.right - 5 && y > v.top + 5 && y < v.bottom - 5)
                  return {x, y};
              }
            }''')
            assert point, 'Pan to show at least one legal square before running the check'
            if not mobile:
                page.mouse.move(point['x'], point['y'])
            folder = Path(os.environ.get('SQUAREPICK1_SCREENSHOTS', '/var/tmp/auto-audit/fix/SQUAREPICK1-evidence'))
            folder.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(folder / ('phone.png' if mobile else 'desktop.png')), full_page=True)
            # Desktop captures first; the phone test then answers the scratch
            # fight once. Recreate its pending choice before another run.
            if mobile:
                with page.expect_request(lambda request: request.url.endswith('/act')) as sent:
                    page.touchscreen.tap(point['x'], point['y'])
                assert any(answer.get('option_ids') for answer in sent.value.post_data_json['reactions'])
        finally:
            browser.close()
