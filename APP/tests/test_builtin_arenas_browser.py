"""Opt-in map rendering checks. The lead runs these outside the sandbox."""
import json
import os
from io import BytesIO
from urllib.parse import urlparse

import pytest

from combat import zones
from tests.test_builtin_arenas import IDS, RETIRED_IDS, ROOT, _fight
from tests.test_retired_maps import _pre_retirement_fight


@pytest.mark.skipif(os.getenv("ARENA1_BROWSER") != "1", reason="Lead must run outside sandbox with ARENA1_BROWSER=1")
@pytest.mark.parametrize("map_id", IDS)
def test_shipped_arena_board_and_screenshot(tmp_path, map_id):
    playwright = pytest.importorskip("playwright.sync_api")
    service, mid = (_pre_retirement_fight(tmp_path, map_id) if map_id in RETIRED_IDS
                    else _fight(tmp_path, "battlefield:map." + map_id))
    doc = service.tabletop_maps.get(map_id)
    engine = service._load_session(mid).engine
    ground = [z.model_dump(mode="json") for z in zones.map_zones(engine)]
    board_map = {
        "width": doc["width_squares"], "height": doc["height_squares"],
        "background": {"url": None, "style": doc["background"]["style"], "seed": doc["background"]["seed"]},
        "display": {"gridOpacity": doc["display"]["grid_opacity"], "detail": 1, "blend": doc["display"]["blend"]},
        "walls": doc["walls"], "trees": doc["trees"], "cells": {
            **doc["cells"],
            "cover": [[cell["x"], cell["y"]] for region in engine.battlefield_document["terrain_regions"]
                      if region["terrain_type"] == "SIMPLE_COVER" for cell in region["cells"]],
        },
        "floors": [{"style": r["material"][6:], "cells": r["cells"]} for r in doc["materials"] if r["material"].startswith("floor:")],
    }
    # Use the real board, procedural texture renderer and zone painter, with
    # scenery converted from the service's sealed arena rather than a mock map.
    html = f'''<!doctype html><html><head><link rel="stylesheet" href="/tabletop.css"></head>
      <body><div class="tt-viewport" id="view" style="width:1280px;height:900px"></div>
      <script type="module">
      import {{createBoard}} from '/board.js';
      const board = createBoard(document.getElementById('view'), {{}});
      board.setMap({json.dumps(board_map)});
      board.setZones({json.dumps(ground)});
      board.fit(); window.ready = true;
      </script></body></html>'''
    static = ROOT / "static/tabletop"

    def serve(route):
        name = urlparse(route.request.url).path.lstrip("/")
        if not name:
            route.fulfill(body=html, content_type="text/html")
        elif name in {p.name for p in static.glob("*.js")} | {"tabletop.css"}:
            route.fulfill(path=str(static / name), content_type="text/css" if name.endswith(".css") else "text/javascript")
        else:
            route.abort()

    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"], headless=True)
        try:
            page = browser.new_page(viewport={"width": 1320, "height": 940})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", serve)
            page.goto("http://arena1.test/")
            page.wait_for_function("window.ready === true")
            assert not errors
            assert page.locator(".tt-walls .tt-wall").count() == len(doc["walls"])
            assert page.locator(".tt-bg-floor").evaluate("node => node.width > 0 && node.height > 0")
            assert page.locator(".tt-zone").count() > 0
            # This deliberately renders outside .tt-app, as a board preview does.
            # Missing theme variables previously made the stone pattern black.
            assert page.locator(".tt-stone-base").evaluate(
                "node => getComputedStyle(node).fill") != "rgb(0, 0, 0)"
            if map_id == "builtin-pillar-arena":
                from PIL import Image

                pillars = page.locator(".tt-walls circle.tt-wall-filled")
                assert pillars.count() == 5
                for pillar in pillars.all():
                    pixels = Image.open(BytesIO(pillar.screenshot())).convert("RGB")
                    w, h = pixels.size
                    # The inner square is fully inside the pillar, away from its
                    # edge/shadow, and includes both stone blocks and joints.
                    sample = pixels.crop((w//3, h//3, 2*w//3, 2*h//3))
                    colors = list(sample.getdata())
                    assert sum(max(rgb) > 24 for rgb in colors) > len(colors) * 0.95
                    assert len(set(colors)) > 1, "Stone should retain visible texture"
            if doc.get("natural_haze") is True:
                mist = page.locator(".tt-zone-air.is-light")
                assert mist.count() > 0
                assert mist.locator(".tt-zone-fill").first.evaluate(
                    "node => getComputedStyle(node).backgroundColor").endswith(", 0.36)")
                assert mist.locator(".tt-anim-drift").count() == 2 * mist.count()
            page.screenshot(path=str(tmp_path / f"{map_id}.png"), full_page=True)
        finally:
            browser.close()
