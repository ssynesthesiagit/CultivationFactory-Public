"""Opt-in rendered fog check: the lead must run outside the sandbox."""
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


def _rendered_fog_script(static):
    """Build the same production view/render path with an explicit player fixture."""
    source = (static / "tabletop.js").read_text(encoding="utf-8")

    def function(name):
        start = source.index(f"function {name}(")
        return source[start:source.index("\n}", start) + 2]

    def constant(name):
        return next(line for line in source.splitlines() if line.startswith(f"const {name} ="))

    script = """
      import {createBoard, initials, treeCells} from '/board.js';
      import {tokenHiddenByFog, perceivedCells, perceivedObjects, wallCells} from '/vision.js';
      import {wallSightCells} from '/zones.js';
      import {blockerSegments, visibilityPolygons} from '/fog_polygon.js';
      import {altitudeVisibilityPolygons, altitudeFogKey, viewerEye} from '/fog-altitude.js';
      import {tableObjectTokens} from '/object-presentation.js';
      import {createHoverCard} from '/hovercard.js';
      import {DEFAULT_FOG_VIEW, NO_FOG_VIEW, fogOn, fogView, fogViewers} from '/fog_view.js';
      import {createViewerStore, resolveViewerIdentity} from '/viewer-identity.js';
      const rows = ['viewer', 'fallen', 'unseen'].map((id, i) => ({entity_id: id,
        display_name: id, active: i === 0, life_state: i === 1 ? 'DYING' : null,
        primary_combatant: true, controller: 'MANUAL', owner_id: null,
        summon_status: null, team_index: 0,
        position: {x: i + 1, y: 1}, hit_points: {current: i ? 0 : 10, maximum: 10}, conditions: []}));
      const app = {matchId: 'sol35-fog', fog: 'own', selected: new Set(), targeting: null,
        explored: new Uint8Array(25), viewerKey: '', viewerPromptKey: '',
        fogGeometryKey: '', fogPolygons: [], seatStatus: {seats: {}},
        state: {last_sequence: 0, tokens: {}, items: [], objects: [],
          presentation: {match_id: 'sol35-fog', actors: rows, current_actor_id: 'viewer',
            round_number: 1, zones: [], battlefield: {width_squares: 5, height_squares: 5, blocked_cells: []}},
          fog_perception: {viewer: {cells: [[1,1],[2,1]], creatures: ['viewer','fallen']}}}};
      const viewerStore = createViewerStore({viewId: 'sol35-player'});
      viewerStore.bindPlayer(app.matchId, ['viewer']);
      const $ = selector => document.querySelector(selector);
      const hoverCard = createHoverCard({doc: document, win: window});
      const openViewerPicker = () => { throw new Error('The explicit fixture binding must stay valid.'); };
      const TEAM_HEX = ['white'];
      const shownCondition = () => true, conditionText = () => '', conditionTone = () => '';
      const board = createBoard(document.querySelector('#ttViewport'), {});
      board.setRoofView({gm: false, viewers: [], seen: new Uint8Array(25)});
      board.setMap({width: 5, height: 5, background: {style: 'plain'}, walls: [], trees: [],
        centerlineCells: [], cells: {blocked: [], sight: []}});
    """
    script += "\n".join(constant(name) for name in (
        "presentation", "offMap", "actors", "teamIndex", "isOwnedActor"))
    script += "\n" + "\n".join(function(name) for name in (
        "currentViewer", "isGMView", "suspendViewerDialogs", "resumeViewerDialogs",
        "resetViewerPresentation", "renderViewerIdentity", "reconcileViewerIdentity", "setFogPicker",
        "fogAudience", "roofAudience", "visibility", "squareFogDebug", "fogGeometry", "viewerIds",
        "unseenByViewers", "tokenLabels", "tokenGeometry", "tokenImage", "renderTokens"))
    return script + "\nrenderTokens(); window.ready = true;"


@pytest.mark.skipif(os.environ.get("SOL35_BROWSER") != "1",
                    reason="lead runs SOL35_BROWSER=1 outside the sandbox")
def test_rendered_fog_keeps_downed_tokens_and_hides_unperceived_tokens(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    static = Path(__file__).resolve().parents[1] / "static" / "tabletop"
    script = _rendered_fog_script(static)
    html = '<html><head><link rel="stylesheet" href="/tabletop.css"></head>'
    html += '<body class="tt-app is-viewer-pending"><div id="ttViewport"></div>'
    html += '<script type="module">' + script + '</script></body></html>'
    def serve(route):
        name = urlparse(route.request.url).path.lstrip("/")
        if not name:
            route.fulfill(body=html, content_type="text/html")
        elif name in {p.name for p in static.glob("*.js")} | {"tabletop.css", "map-heights.json"}:
            kind = 'application/json' if name.endswith('.json') else 'text/css' if name.endswith('.css') else 'text/javascript'
            route.fulfill(path=str(static / name), content_type=kind)
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
