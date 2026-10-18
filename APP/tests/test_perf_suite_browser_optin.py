"""Lead-only rendered timing smoke against an already isolated scratch server.

Run outside the sandbox with PERF_SUITE_BROWSER=1 and
PERF_SUITE_TABLE_URL=http://127.0.0.1:<scratch-port>/tabletop?... .
The lead prepares a human table with at least one multi-option action.
These timings supplement the counter gate; they have no wall-clock assertions.
"""
import json
import os
from urllib.parse import urlparse

import pytest


@pytest.mark.skipif(os.environ.get('PERF_SUITE_BROWSER') != '1',
                   reason='Lead must run Chromium outside the sandbox on a scratch server')
def test_rendered_menu_and_option_open(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    url = os.environ['PERF_SUITE_TABLE_URL']
    parsed = urlparse(url)
    assert parsed.hostname in {'localhost', '127.0.0.1'} and parsed.port not in {None, 8765}
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page()
            page.goto(url)
            expect(page.locator('#ttViewerChange')).to_be_enabled(timeout=120000)
            if not page.locator('#ttViewerPicker').is_visible():
                page.locator('#ttViewerChange').click()
            page.locator('#ttViewerGM').click()
            expect(page.get_by_role('button', name='End turn', exact=True)).to_be_visible(timeout=120000)
            timing = page.evaluate('performance.getEntriesByType("navigation")[0].toJSON()')
            # Opening a picker is reversible. The lead chooses the multi-option
            # ability by visible text, avoiding accidental immediate commits.
            label = os.environ['PERF_SUITE_PICKER_LABEL']
            requests = []
            page.on('request', lambda request: requests.append(request.url))
            page.get_by_role('button', name=label, exact=True).click()
            expect(page.locator('#ttHint')).to_be_visible()
            assert not any(urlparse(u).path.endswith('/act') for u in requests)
            (tmp_path / 'rendered-perf.json').write_text(json.dumps({'navigation': timing,
                'picker_requests': len(requests)}, indent=2))
        finally:
            browser.close()
