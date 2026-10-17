"""Opt-in rendered fog check: the lead must run outside the sandbox."""
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


@pytest.mark.skipif(os.environ.get("SOL35_BROWSER") != "1",
                    reason="lead runs SOL35_BROWSER=1 outside the sandbox")
def test_rendered_fog_keeps_downed_tokens_and_hides_unperceived_tokens(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    static = Path(__file__).resolve().parents[1] / "static" / "tabletop"
    source = (static / "tabletop.js").read_text()
    def function(name):
        start = source.index(f"function {name}(")
        return source[start:source.index("\n}", start) + 2]

    script = """
      import {createBoard, OBJECT_FACE} from '/board.js';
      import {tokenHiddenByFog, perceivedCells} from '/vision.js';
      const rows = ['viewer', 'fallen', 'unseen'].map((id, i) => ({entity_id: id,
        display_name: id, active: i === 0, life_state: i === 1 ? 'DYING' : null,
        position: {x: i + 1, y: 1}, hit_points: {current: i ? 0 : 10, maximum: 10}, conditions: []}));
      const actors = () => rows, presentation = () => ({}), tokenLabels = () => new Map();
      const viewerIds = () => new Set(['viewer']);
      const app = {fog: 'team', selected: new Set(), targeting: null, explored: new Uint8Array(25),
        state: {tokens: {}, fog_perception: {viewer: {cells: [[1,1],[2,1]], creatures: ['viewer','fallen']}}}};
      const visibility = () => perceivedCells(5, 5, [rows[0]], app.state.fog_perception);
      const tokenGeometry = () => ({width: 1, height: 1});
      const TEAM_HEX = ['white'], teamIndex = () => 0, isManualActor = () => true;
      const shownCondition = () => true, conditionText = () => '', conditionTone = () => '';
      const board = createBoard(document.querySelector('#ttViewport'), {});
      board.setMap({width: 5, height: 5, background: {style: 'plain'}});
    """ + function("unseenByViewers") + function("tokenImage") + function("renderTokens") + "renderTokens(); window.ready = true;"
    html = '<link rel="stylesheet" href="/tabletop.css"><div id="ttViewport"></div>'
    html += '<script type="module">' + script + '</script>'
    def serve(route):
        name = urlparse(route.request.url).path.lstrip("/")
        if not name:
            route.fulfill(body=html, content_type="text/html")
        elif name in {p.name for p in static.glob("*.js")} | {"tabletop.css"}:
            route.fulfill(path=str(static / name), content_type="text/css" if name.endswith(".css") else "text/javascript")
        else:
            route.abort()
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", serve)
            page.goto("http://sol35.test/")
            page.wait_for_function("window.ready === true")
            assert page.locator('.tt-token.is-down:not(.is-hidden)').count() == 1
            assert page.locator('.tt-token.is-hidden').count() == 1
            assert page.locator('.tt-token:not(.is-hidden) .tt-token-badge', has_text="Dying").count() == 1
            assert not errors
        finally:
            browser.close()
