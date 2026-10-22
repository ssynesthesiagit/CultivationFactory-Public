"""One document popup on real sheet rows; browser verification is lead-only and opt-in."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading

import pytest

APP = Path(__file__).resolve().parents[1]


def test_sheet_double_tooltip_dom():
    result = subprocess.run(["node", "tests/sheet_hover_dom.test.mjs"], cwd=APP,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.getenv("SOL211_BROWSER") != "1",
                    reason="Lead must run Chromium outside the sandbox")
def test_sheet_double_tooltip_browser(tmp_path):
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
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
            try:
                page = browser.new_page(viewport={"width": 1200, "height": 850})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}/static/themes.css")
                page.set_content('''<link rel="stylesheet" href="/static/tabletop/hovercard.css">
                  <link rel="stylesheet" href="/static/tabletop/sheet.css">
                  <main class="sheet" style="width:720px;margin:0">
                    <h1>Chain Adept</h1><section title="Resonance"><div id="rows"></div></section>
                    <button id="map-trigger">Map creature</button></main>''')
                page.evaluate('''async source => {
                  const {actionHoverText, actionTipCard, cleanRules, uniqueRuleBlocks} = await import('/static/tabletop/rules.js');
                  const {layoutText} = await import('/static/tabletop/presentation.js');
                  const {installGlossary, glossaryDefinitions} = await import('/static/tabletop/newcomer.js');
                  const {createHoverCard, bindTipTargets} = await import('/static/tabletop/hovercard.js');
                  const paint = new Function('actionHoverText', 'actionTipCard', 'cleanRules', 'layoutText', 'uniqueRuleBlocks',
                    source + '\n document.querySelector("#rows").replaceChildren(actionRow(row));');
                  const sheetCard = createHoverCard();
                  window.renderSheet = () => {
                    paint(actionHoverText, actionTipCard, cleanRules, layoutText, uniqueRuleBlocks);
                    installGlossary();
                    bindTipTargets(sheetCard, document, {glossary: text => glossaryDefinitions(text, false)});
                  };
                  const mapCard = createHoverCard();
                  document.querySelector('#map-trigger').addEventListener('pointerenter', () => mapCard.open({
                    trigger: document.querySelector('#map-trigger'), build: node => { node.textContent = 'Map creature'; }}));
                  window.renderSheet();
                }''', fixture["source"])
                row = page.locator('[data-button-id="act:chain-armor"]')
                for iteration in range(3):
                    if iteration:
                        page.evaluate("window.renderSheet()")
                    page.locator("#map-trigger").hover()
                    row.locator(".arow-sub").hover()
                    card = page.locator(".tt-hovercard:visible")
                    expect(card).to_have_count(1)
                    expect(card).to_contain_text("Chain Armor")
                    page.wait_for_timeout(1800)
                    assert page.locator(".tt-hovercard").count() == 1
                    assert row.get_attribute("title") == ""  # block inherited native popup
                    assert page.locator('[data-tip] [title]:not([title=""])').count() == 0
                row.focus()
                expect(page.locator(".tt-hovercard:visible")).to_have_count(1)
                out = Path(os.getenv("SOL211_SCREENSHOT_DIR", str(tmp_path)))
                out.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out / "SOL211-sheet-double-tooltip.png"))
                assert not errors, errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
