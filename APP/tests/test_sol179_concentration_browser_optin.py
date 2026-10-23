"""Lead only, outside sandbox: SOL179_BROWSER=1 pytest this file.

Static sheet fixture: no live service or saved fight is accessed. Set
SOL179_SCREENSHOT_DIR to retain the focused sheet and tooltip screenshots.
"""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import threading

import pytest

pytestmark = pytest.mark.skipif(os.getenv("SOL179_BROWSER") != "1",
                              reason="Lead must run browser checks outside the sandbox")


def test_concentration_sheet_hover_focus_visibility_and_end():
    from playwright.sync_api import sync_playwright, expect

    root = Path(__file__).resolve().parents[1]

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
            try:
                page = browser.new_page(viewport={"width": 1000, "height": 700})
                page.goto(f"http://127.0.0.1:{server.server_port}/static/themes.css")
                page.set_content('''<link rel="stylesheet" href="/static/themes.css">
                  <link rel="stylesheet" href="/static/tabletop/hovercard.css">
                  <link rel="stylesheet" href="/static/tabletop/tabletop.css">
                  <body class="tt-app"><aside id="sheet" style="width:300px;padding:20px">
                    <h2>Moon Adept</h2><div class="tt-sub">HP 500 / 500</div>
                    <div id="focus"></div></aside></body>''')
                page.evaluate('''async () => {
                  document.documentElement.dataset.theme = 'lacquer';
                  const {concentrationCard} = await import('/static/tabletop/concentration.js');
                  const {bindTipTargets, createHoverCard} = await import('/static/tabletop/hovercard.js');
                  window.paintConcentration = (effects, visible = true) => {
                    document.querySelector('#focus').innerHTML = concentrationCard({concentration_effects: effects}, visible);
                  };
                  bindTipTargets(createHoverCard(), document);
                  paintConcentration(["Moon's Pull"]);
                }''')
                line = page.locator(".tt-concentration-line")
                expect(line).to_have_text("Concentrating on Moon's Pull")
                line.hover()
                tooltip = page.get_by_text("Concentration keeps an effect going", exact=False)
                expect(tooltip).to_be_visible()
                expect(tooltip).to_contain_text("DC 10 or half the damage")
                screenshots = os.getenv("SOL179_SCREENSHOT_DIR")
                if screenshots:
                    folder = Path(screenshots)
                    folder.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(folder / "SOL179-sheet-hover.png"))
                page.mouse.move(950, 650)
                line.focus()
                expect(tooltip).to_be_visible()
                if screenshots:
                    page.screenshot(path=str(folder / "SOL179-sheet-focus.png"))
                page.evaluate("paintConcentration(['Darkness'], false)")
                expect(line).to_have_count(0)
                page.evaluate('paintConcentration([])')
                expect(line).to_have_count(0)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
