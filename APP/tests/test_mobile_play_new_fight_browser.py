"""Opt-in 390x844 visual evidence. Lead runs outside the worker sandbox.

No server is needed: every HTTP request, including page assets and API writes,
is intercepted. Screenshots are synthetic UI evidence, never owner fight data.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


@pytest.mark.skipif(os.environ.get('PLAYNEW1_BROWSER') != '1',
                    reason='lead-only: PLAYNEW1_BROWSER=1 outside sandbox')
def test_mobile_play_new_fight_screenshots():
    playwright = pytest.importorskip('playwright.sync_api')
    app = Path(__file__).resolve().parents[1]
    output = app.parent / 'fix' / 'PLAYNEW1-evidence'
    output.mkdir(parents=True, exist_ok=True)
    captures = []
    errors = []
    waiting = []
    characters = [{'project_id': 'sample-a', 'actor_id': 'actor:factory.sample-a', 'display_name': 'River Guardian'},
                  {'project_id': 'sample-b', 'actor_id': 'actor:factory.sample-b', 'display_name': 'Mountain Archer'}]

    def route_request(route):
        path = urlparse(route.request.url).path
        if path == '/api/combat/matches':
            data = [{'match_id': 'sample', 'display_name': 'Courtyard practice'}]
        elif path.endswith('/state'):
            waiting.append(route)
            return
        elif path.endswith('/seat-status'):
            data = {'seats': {}}
        elif path == '/api/combat/factory-characters':
            data = characters
        elif path == '/api/combat/factory-arenas':
            data = [{'arena_id': 'sample-map', 'display_name': 'Training courtyard',
                     'description': 'An open courtyard with room for both sides.'}]
        elif path.startswith('/api/'):
            route.fulfill(status=409, content_type='application/json', body='{}')
            return
        else:
            asset = app / ('static/play/play.html' if path == '/play' else path.lstrip('/'))
            assert asset.resolve().is_relative_to(app / 'static')
            if asset.is_file():
                types = {'.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html'}
                route.fulfill(status=200, content_type=types.get(asset.suffix, 'application/octet-stream'), body=asset.read_bytes())
            else:
                route.fulfill(status=404, body='')
            return
        route.fulfill(status=200, content_type='application/json', body=json.dumps(data))

    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True,
                                          has_touch=True, device_scale_factor=1, reduced_motion='reduce')
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/*', route_request)
            page.goto('http://127.0.0.1:8799/play', wait_until='domcontentloaded')

            def capture(name):
                page.screenshot(path=str(output / name))
                captures.append(name)

            page.locator('#loadCard').wait_for(state='visible')
            assert 'up to a minute' in page.locator('#loadMessage').inner_text()
            capture('01-loading.png')
            page.wait_for_function("document.querySelector('#loadSpinner') && !document.querySelector('#loadSpinner').hidden")
            # Pump the routed state request without waiting for a real server.
            page.wait_for_timeout(100)
            assert waiting
            waiting.pop().fulfill(status=503, content_type='application/json', body=json.dumps({
                'error': {'message': 'Server restarted', 'code': 'NETWORK_ERROR'}}))
            page.locator('#retryLoad').wait_for(state='visible')
            capture('02-error-retry.png')
            page.locator('#cancelLoad').tap()
            page.locator('#newFight').tap()
            page.locator('.play-fighter').first.wait_for(state='visible')
            page.locator('.play-fighter input').nth(0).check()
            page.locator('.play-fighter input').nth(1).check()
            capture('03-new-fight.png')
            assert page.locator('#createFight').is_enabled()
            assert not errors, errors
            (output / 'index.json').write_text(json.dumps({
                'viewport': [390, 844], 'synthetic': True, 'screenshots': captures, 'errors': errors}, indent=2) + '\n')
        finally:
            browser.close()
