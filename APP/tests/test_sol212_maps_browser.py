"""Lead-only real /tabletop screenshots on disposable fights.

From APP, outside the sandbox:
SOL212_BROWSER=1 <project-python> -m pytest tests/test_sol212_maps_browser.py
    --basetemp=/var/tmp/sol212f-browser
"""
from contextlib import contextmanager
import json
import os
import shutil
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

import pytest

from combat.tabletop_service import TabletopService
from tests.run_controller_browser import reserve_socket
from tests.test_builtin_arenas import _fight, ROOT
from tests.test_sol212_new_maps import IDS


@contextmanager
def _table_server(data, log_path):
    """Reuse the controller checks' real app and inherited loopback socket.

    Stop only our child PID; all writable settings and the empty model-provider
    registry point into this test's disposable data.
    """
    providers = data / 'providers.json'
    providers.write_text(json.dumps({'providers': []}))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT),
               TIANXIA_FOUNDRY_DATA=str(data),
               TIANXIA_FOUNDRY_SECURITY_DIR=str(data / 'security'),
               FACTORY_SEAT_PROVIDERS=str(providers))
    for key in ('TIANXIA_FACTORY_ZIP', 'TIANXIA_FACTORY_FIXTURE'):
        env.pop(key, None)
    with reserve_socket() as sock, log_path.open('w') as log:
        base = f'http://127.0.0.1:{sock.getsockname()[1]}'
        process = subprocess.Popen(
            [sys.executable, str(ROOT / 'tests/run_controller_browser.py'),
             '--serve', str(data), '--socket-fd', str(sock.fileno())],
            cwd=ROOT, env=env, pass_fds=(sock.fileno(),),
            stdout=log, stderr=subprocess.STDOUT)
        print(f'SOL212 isolated server PID: {process.pid}; data: {data}', flush=True)
        sock.close()
        try:
            deadline = time.monotonic() + 120
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f'Server exited {process.returncode}; see {log_path}')
                try:
                    with urlopen(base + '/tabletop', timeout=2) as response:
                        assert response.status == 200
                    break
                except (URLError, TimeoutError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f'Server not ready; see {log_path}')
                    time.sleep(0.1)
            yield base
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


@pytest.mark.skipif(os.getenv('SOL212_BROWSER') != '1',
                   reason='Lead must run outside sandbox with SOL212_BROWSER=1')
@pytest.mark.parametrize('map_id', IDS)
def test_new_map_real_board_screenshot(tmp_path, map_id):
    playwright = pytest.importorskip('playwright.sync_api')
    data = tmp_path / 'data'
    try:
        combat, mid = _fight(data, 'battlefield:map.' + map_id, size=6, rounds=1)
        state = TabletopService(combat, data).state(mid)
        with _table_server(data, tmp_path / 'server.log') as base:
            with playwright.sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path='/usr/bin/chromium',
                                            args=['--no-sandbox'], headless=True)
                try:
                    page = browser.new_page(viewport={'width': 1480, 'height': 1120})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    try:
                        # Actual HTML, assets and APIs run the private mapFromState().
                        response = page.goto(base + '/tabletop?match=' + quote(mid, safe=''))
                        assert response.ok
                        page.wait_for_function(
                            'mid => window.tabletop?.app.matchId === mid '
                            '&& !!window.tabletop.app.state && !window.tabletop.app.busy',
                            arg=mid, timeout=120000)
                        rendered = page.evaluate('window.tabletop.app.state')
                        assert rendered['presentation']['battlefield'] == state['presentation']['battlefield']
                        assert rendered['presentation']['zones'] == state['presentation']['zones']
                        field = rendered['presentation']['battlefield']
                        assert page.locator('.tt-grid').get_attribute('viewBox') == (
                            f"0 0 {field['width_squares']} {field['height_squares']}")
                        assert page.locator('.tt-bg-floor').evaluate(
                            'node => node.width > 0 && node.height > 0')
                        # One ground layer per zone; .tt-zone also counts optional
                        # air/shadow layers. Scenery-only maps legitimately have none.
                        assert page.locator('.tt-zone-ground').count() == len(rendered['presentation']['zones'])
                        assert page.locator('.tt-token:not(.is-object)').count() == 12
                        assert page.locator('.tt-token.is-object').count() == len(rendered.get('objects', []))
                        trees = rendered['map'].get('trees', [])
                        assert trees == state['map'].get('trees', [])
                        # The real board replaces one SVG <use> per map tree with
                        # a painted raster layer after asynchronous sprite decode.
                        page.wait_for_function("!document.querySelector('.tt-tree-raster')?.dataset.pending")
                        tree_layer = page.evaluate('''trees => {
                            const svg = document.querySelector('.tt-trees');
                            const canvas = document.querySelector('.tt-tree-raster');
                            if (!canvas || canvas.hidden) {
                                return {uses: [...svg.querySelectorAll('use')].map(node =>
                                    [Number(node.getAttribute('x')), Number(node.getAttribute('y'))])};
                            }
                            const width = window.tabletop.app.state.presentation.battlefield.width_squares;
                            const height = window.tabletop.app.state.presentation.battlefield.height_squares;
                            const px = canvas.width / (width + 6);
                            const context = canvas.getContext('2d');
                            return {width: canvas.width, height: canvas.height, px,
                                ready: !!canvas.dataset.ready,
                                painted: trees.map(tree => {
                                    const size = tree.size === 2 ? 2 : 1;
                                    const data = context.getImageData(Math.round((tree.x + 3) * px),
                                        Math.round((tree.y + 3) * px), size * px, size * px).data;
                                    return data.some((value, index) => index % 4 === 3 && value > 0);
                                })};
                        }''', trees)
                        if 'uses' in tree_layer:
                            assert tree_layer['uses'] == [[t['x'], t['y']] for t in trees]
                        else:
                            assert trees and tree_layer['ready']
                            assert tree_layer['px'] > 0
                            assert tree_layer['height'] == (field['height_squares'] + 6) * tree_layer['px']
                            assert tree_layer['painted'] == [True] * len(trees)
                        if rendered['map'].get('walls'):
                            assert page.locator('.tt-walls').evaluate('node => node.childElementCount > 0')
                        assert not errors, errors
                    finally:
                        page.screenshot(path=str(tmp_path / (map_id + '.png')), full_page=True)
                finally:
                    browser.close()
    finally:
        # Keep screenshots and server logs, remove disposable databases.
        shutil.rmtree(data, ignore_errors=True)
