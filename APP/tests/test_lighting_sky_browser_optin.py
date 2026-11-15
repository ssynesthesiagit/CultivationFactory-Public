"""Lead-only visual evidence: synthetic preview map, four times, no sandbox browser."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse
import pytest

ROOT = Path(__file__).resolve().parents[1]

# Synthetic camp map: a stone-and-timber wall, a dead tree, a crate, two floor styles and rubble.
# Built in the test (no data file) so the public export can run it; it exercises the same board paths.
PREVIEW_MAP = {
    "width_squares": 24, "height_squares": 16, "square_size_ft": 5,
    "background": {"style": "mountain", "seed": 40211},
    "display": {"grid_opacity": 0.2, "blend": 0.35},
    "walls": [
        {"id": "wall-a", "shape": "rect", "points": [[8.0, 3.0], [9.0, 12.0]], "filled": True,
         "blocks": "sight_and_movement", "look": "timber_lattice", "height_ft": 10},
        {"id": "wall-b", "shape": "rect", "points": [[12.0, 13.0], [16.0, 14.0]], "filled": True,
         "blocks": "sight_and_movement", "look": "timber_lattice", "height_ft": 10},
    ],
    "trees": [{"x": 3, "y": 2, "size": 1, "seed": 973, "look": "dead", "occluder": "centerline", "height_ft": 20}],
    "objects": [{"id": 1, "kind": "crate", "x": 13, "y": 6, "height_ft": 3}],
    "cells": {"blocked": [[5, 8], [6, 8]], "sight": []},
    "materials": [
        {"material": "floor:scree_ground", "cells": [[x, y] for x in range(1, 7) for y in range(9, 13)]},
        {"material": "floor:wood", "cells": [[x, y] for x in range(14, 20) for y in range(9, 12)]},
        {"material": "terrain:loose rubble", "cells": [[10, 4], [10, 5], [11, 4], [18, 14], [19, 14]]},
    ],
}

@pytest.mark.skipif(os.getenv("LIGHTS5_BROWSER") != "1", reason="Lead must run outside sandbox")
def test_lighting_preview_screenshots(tmp_path):
    from playwright.sync_api import sync_playwright
    doc = PREVIEW_MAP
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
