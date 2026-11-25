"""Lead runs PERF1_BROWSER=1 outside the sandbox; no server or live data needed."""
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


@pytest.mark.skipif(os.environ.get("PERF1_BROWSER") != "1",
                    reason="lead must run PERF1_BROWSER=1 outside the sandbox")
@pytest.mark.parametrize("width", [1600, 1280])
def test_crowded_header_has_full_width_turn_order_and_visible_current_chip(width, tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    root = Path(__file__).resolve().parents[1] / "static"
    source = (root / "tabletop" / "tabletop.html").read_text()
    header = source[source.index('<header class="tt-top">'):source.index('</header>') + len('</header>')]
    html = ('<link rel="stylesheet" href="/themes.css">'
            '<link rel="stylesheet" href="/tabletop/tabletop.css">'
            '<body class="tt-app">' + header + '</body>')
    def serve(route):
        path = urlparse(route.request.url).path
        if path == "/":
            route.fulfill(body=html, content_type="text/html")
        elif path in ("/themes.css", "/tabletop/tabletop.css"):
            route.fulfill(path=str(root / path.lstrip("/")), content_type="text/css")
        else:
            route.abort()
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"], headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": 500})
            page.route("**/*", serve)
            page.goto("http://perf1.test/")
            page.evaluate("""() => {
              document.querySelector('#ttMatchName').textContent = 'Demon horde';
              const ol = document.querySelector('#ttInitiative');
              ['Tabik Damu','Lingfeng Xi','Wen Xue','Jiang Xi','Gu Xiangze','He Zhenbo','Mei Jiang','Ouyang Lanjiang'].forEach((name,i) => {
                const li = document.createElement('li');
                if (i === 0) li.className = 'is-current';
                const button = document.createElement('button'); button.textContent = name;
                li.appendChild(button); ol.appendChild(li);
              });
            }""")
            strip = page.locator('#ttInitiative')
            assert strip.is_visible()
            box = strip.bounding_box()
            assert box and box['width'] >= width * .9, box
            chip = page.locator('#ttInitiative .is-current button')
            assert chip.is_visible() and chip.inner_text() == 'Tabik Damu'
            current = chip.bounding_box()
            assert current and current['width'] > 0 and current['height'] > 0
            assert current['x'] >= box['x'] and current['x'] + current['width'] <= box['x'] + box['width']
            assert 0 <= current['y'] and current['y'] + current['height'] <= 500
            tools = page.locator('.tt-top-tools').bounding_box()
            assert tools and box['y'] >= tools['y'] + tools['height'] - 1
            for selector in ('#ttFog', '#ttLobbyOpen', '#ttNames'):
                control = page.locator(selector)
                assert control.is_visible() and control.is_enabled()
                rect = control.bounding_box()
                assert rect and 0 <= rect['x'] and rect['x'] + rect['width'] <= width
            page.screenshot(path=str(tmp_path / f'perf1-header-{width}.png'))
        finally:
            browser.close()
