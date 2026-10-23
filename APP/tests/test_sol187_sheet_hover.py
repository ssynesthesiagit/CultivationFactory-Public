"""SOL187: deterministic DOM checks, plus lead-only visual verification."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading

import pytest

APP = Path(__file__).resolve().parents[1]


def test_sheet_hover_dom():
    result = subprocess.run(["node", "tests/sheet_hover_dom.test.mjs"], cwd=APP,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.getenv("SHEETHOVER_BROWSER") != "1",
                    reason="Lead must run Chromium outside the sandbox")
def test_sheet_hover_real_row_screenshot(tmp_path):
    from playwright.sync_api import sync_playwright, expect

    fixture = json.loads(subprocess.check_output(
        ["node", str(APP / "tests/sheet_hover_render_source.cjs")], text=True))

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(APP)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
            try:
                # Screenshot's sheet occupies about 720 px; the rest leaves room for its card.
                width = int(os.getenv("SHEETHOVER_SHEET_WIDTH", "720"))
                page = browser.new_page(viewport={"width": width + 400, "height": 850})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/static/themes.css")
                page.set_content(f'''<link rel="stylesheet" href="/static/themes.css">
                  <link rel="stylesheet" href="/static/tabletop/hovercard.css">
                  <link rel="stylesheet" href="/static/tabletop/sheet.css">
                  <main class="sheet" style="width:{width}px;max-width:{width}px;margin:0">
                    <h1>Chain Adept</h1><section class="agroup"><h3>Bonus Actions</h3>
                    <div id="rows"></div></section></main>''')
                page.evaluate('''async source => {
                  document.documentElement.dataset.theme = 'lacquer';
                  const {actionHoverText, actionTipCard, cleanRules, uniqueRuleBlocks} = await import('/static/tabletop/rules.js');
                  const {layoutText} = await import('/static/tabletop/presentation.js');
                  const {installGlossary} = await import('/static/tabletop/newcomer.js');
                  const {createHoverCard, bindTipTargets} = await import('/static/tabletop/hovercard.js');
                  // Execute the actual sheet actionRow/h/describe functions, not an imitation.
                  const paint = new Function('actionHoverText', 'actionTipCard', 'cleanRules', 'layoutText', 'uniqueRuleBlocks', source +
                    '\\n document.querySelector("#rows").append(actionRow(row));');
                  paint(actionHoverText, actionTipCard, cleanRules, layoutText, uniqueRuleBlocks);
                  installGlossary(); bindTipTargets(createHoverCard(), document);
                }''', fixture["source"])
                row = page.locator('[data-button-id="act:chain-armor"]')
                row.locator('.arow-sub').hover()
                card = page.locator('.tt-hovercard')
                expect(card).to_be_visible()
                # Wait beyond the native tooltip delay and hover a nested cost label.
                page.wait_for_timeout(1800)
                assert page.locator('[data-tip][title], [data-hover-card][title], [data-tip] [title]').count() == 0
                text = card.inner_text()
                for part in ('Chains coil around your body', '3 Resonance',
                             'Concentration, up to 1 minute', 'Partly automated:'):
                    assert text.count(part) == 1
                assert 'Resonance is the Spirit Awakening' not in text
                out = Path(os.getenv('SHEETHOVER_SCREENSHOT_DIR', str(tmp_path)))
                out.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out / 'SOL187-sheet-hover.png'))
                row.focus()
                expect(card).to_be_visible()
                assert not errors, errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
