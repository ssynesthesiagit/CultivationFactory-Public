"""Lead-only screenshot gate: the production board under light/fog/cloud bands.

Run outside the agent sandbox with AIMSLOW_BROWSER=1, through the test queue.
Screenshots are a pair of the same synthetic scene with and without aiming UI.
"""
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get("AIMSLOW_BROWSER") != "1",
                    reason="Lead runs Chromium and the screenshot gate outside the sandbox")
def test_aim_marks_above_atmosphere(tmp_path):
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from PIL import Image, ImageChops
    from playwright.sync_api import sync_playwright

    root = Path(__file__).resolve().parents[1] / "static"
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(root)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
            try:
                page = browser.new_page(viewport={"width": 1000, "height": 760})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(origin)
                page.set_content(f'<link rel="stylesheet" href="{origin}/tabletop/tabletop.css">'
                                 '<div id="board" class="tt-viewport" style="position:relative;width:900px;height:650px"></div>')
                page.evaluate("""async origin => {
                  const {createBoard} = await import(origin + '/tabletop/board.js');
                  const board = window.aimBoard = createBoard(document.querySelector('#board'));
                  board.setMap({width:8,height:6,background:{style:'plain'},walls:[],trees:[],
                    cells:{blocked:[],sight:[]}});
                  // Darkness may legally be aimed at an unseen square. Its UI
                  // must stay legible without revealing the ground under fog.
                  board.setFog(new Uint8Array(48));
                  board.setLight({cells:btoa(String.fromCharCode(...new Uint8Array(12)))},
                    new Uint8Array(48).fill(1));
                  board.fit();
                }""", origin)
                before = tmp_path / "aim-marks-without.png"
                after = tmp_path / "aim-marks-with.png"
                page.screenshot(path=str(before))
                page.evaluate("""() => aimBoard.setHighlights({
                  areas:[{x:2,y:3},{x:4,y:3}],areaCells:[{x:2,y:3},{x:3,y:3}]
                })""")
                assert page.locator(".tt-mark-center").count() == 2
                assert page.locator(".tt-mark-area").count() == 2
                page.screenshot(path=str(after))
                assert ImageChops.difference(Image.open(before).convert("RGB"),
                                            Image.open(after).convert("RGB")).getbbox()
                assert page.locator(".tt-mark-center").first.evaluate("""mark => {
                  const board = mark.closest('.tt-board'), fog = board.querySelector('.tt-fog');
                  return Boolean(fog.compareDocumentPosition(mark) & Node.DOCUMENT_POSITION_FOLLOWING)
                    && mark.getBoundingClientRect().width > 0;
                }""")
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
