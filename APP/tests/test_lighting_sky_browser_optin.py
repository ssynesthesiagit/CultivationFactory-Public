"""Lead-only visual evidence: real preview map, four times, no sandbox browser."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.skipif(os.getenv("LIGHTS5_BROWSER") != "1", reason="Lead must run outside sandbox")
def test_lighting_preview_screenshots(tmp_path):
    from playwright.sync_api import sync_playwright
    doc = json.loads((ROOT / "combat/maps/builtin-lighting-preview-camp.json").read_text())
    board_map = {"width": doc["width_squares"], "height": doc["height_squares"],
        "background": {"url": None, "style": doc["background"]["style"], "seed": doc["background"]["seed"]},
        "display": {"gridOpacity": doc["display"]["grid_opacity"], "detail": 1, "blend": doc["display"]["blend"]},
        "walls": doc["walls"], "trees": doc["trees"], "objects": doc.get("objects", []),
        "roofs": doc.get("roofs"), "cells": doc.get("cells", {}),
        "floors": [{"style": r["material"][6:], "cells": r["cells"]} for r in doc.get("materials", []) if r["material"].startswith("floor:")]}
    html = f"""<html><head><link rel='stylesheet' href='/tabletop.css'></head><body>
    <div class='tt-viewport' id='view' style='width:1280px;height:900px'></div>
    <script type='module'>import {{createBoard}} from '/board.js';
    window.board = createBoard(document.getElementById('view'), {{}}); window.map = {json.dumps(board_map)};
    window.showTime = time => {{board.setMap({{...map, ambient: {{time_of_day: time}}}}); board.setLight(null); board.fit();}};
    showTime('day'); window.ready = true;</script></body></html>"""
    static = ROOT / "static/tabletop"
    def serve(route):
        name = urlparse(route.request.url).path.lstrip("/")
        if not name:
            route.fulfill(body=html, content_type="text/html")
        elif (static / name).is_file() and name.endswith((".js", ".css")):
            route.fulfill(path=str(static / name), content_type="text/css" if name.endswith(".css") else "text/javascript")
        else:
            route.abort()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 1320, "height": 940})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.route("**/*", serve)
            page.goto("http://lighting-preview.test/")
            page.wait_for_function("window.ready === true")
            for time in ("dawn", "day", "dusk", "night"):
                page.evaluate("time => window.showTime(time)", time)
                page.wait_for_timeout(1000)
                page.screenshot(path=str(tmp_path / f"lighting-{time}.png"))
            assert not errors
        finally:
            browser.close()
