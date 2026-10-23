"""Opt-in rendered native image projection; lead runs outside the sandbox.

CF_AFTERIMAGE_BROWSER=1 python -m pytest tests/test_mgr_t14_afterimage_map_browser.py
Uses system Chromium, never Playwright's bundled browser or live combat data.
"""
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get("CF_AFTERIMAGE_BROWSER") != "1", reason="lead-only browser check outside sandbox")
def test_native_image_projection_renders_hides_and_removes(tmp_path):
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from playwright.sync_api import sync_playwright
    from combat import senses
    from tests.test_mgr_t14_afterimage_map import game, move, image
    from tests.auto8f1_table_support import OWNER, FOE, candidate_id

    g = game(tmp_path)
    move(g)
    engine = g["stored_engine"]()
    _, obj = image(engine)
    rows = g["table"].state(g["match_id"])["objects"]
    rows = [r for r in rows if r["id"] == obj.object_id]
    perceived = senses.perception(engine, engine.state.actors[FOE])["objects"]
    g["commit"](candidate_id(g["menu"](), "End image condition"))
    ended_rows = [r for r in g["table"].state(g["match_id"])["objects"] if r["id"] == obj.object_id]
    assert not ended_rows
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler,
        directory=str(Path(__file__).resolve().parents[1])))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
            try:
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{server.server_port}/static/tabletop/")
                page.set_content('<div id="board" style="width:800px;height:600px"></div>')
                page.evaluate("""async ({rows, perceived}) => {
                    const {createBoard} = await import('/static/tabletop/board.js');
                    const {tableObjectTokens} = await import('/static/tabletop/object-presentation.js');
                    window.imageBoard = createBoard(document.querySelector('#board'));
                    window.imageBoard.setMap({width_squares:20,height_squares:14,
                        background:{style:'plain'},walls:[],terrain:[],trees:[],materials:[]});
                    window.renderImages = (objects, seenIds) => imageBoard.setTokens(
                        tableObjectTokens(objects,new Set(),[],new Uint8Array(280).fill(1),20,
                            'afterimage-browser',new Set(seenIds)));
                    renderImages(rows,perceived);
                }""", {"rows": rows, "perceived": perceived})
                token = page.locator('.tt-token[aria-label^="Afterimage."]')
                assert token.count() == 1 and "is-hidden" not in token.get_attribute("class")
                assert OWNER not in token.get_attribute("aria-label")
                page.evaluate("rows => renderImages(rows,[])", rows)
                assert "is-hidden" in token.get_attribute("class")
                page.evaluate("rows => renderImages(rows,[])", ended_rows)
                assert token.count() == 0
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
