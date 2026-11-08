"""Mounted tabletop presentation regressions; all assets and fights are test-owned."""
from types import SimpleNamespace
import copy
import json
import os
import subprocess
import shutil
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import pytest

from combat.tabletop_service import TabletopService
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests.test_factory_combat_compiler import SHEET


@pytest.mark.parametrize("group,kind", [("mount.warhorse", "warhorse"), ("beast0.wolf", "wolf"),
                                       ("beast.pack.wolf", "wolf"), ("wolf", "wolf")])
def test_summon_tokens_resolve_creature_kind(tmp_path, group, kind):
    actor = SimpleNamespace(entity_id="summon:test", summon={"group": group})
    engine = SimpleNamespace(state=SimpleNamespace(actors={actor.entity_id: actor}))
    combat = SimpleNamespace(_load_session=lambda _: SimpleNamespace(engine=engine))
    table = TabletopService(combat, tmp_path)
    pool = table.summon_token_root() / kind
    pool.mkdir(parents=True)
    (pool / "face.png").write_bytes(b"test fixture")
    expected = {actor.entity_id: f"/api/tabletop/summon-tokens/{kind}/face.png"}
    assert table._summon_tokens("fight") == expected
    assert table._summon_tokens("fight", engine) == expected
    assert table.summon_token_path(kind, "face.png") == pool / "face.png"


@pytest.fixture
def mounted_table_rows(tmp_path):
    root = Path(__file__).resolve().parents[1]
    sheet = copy.deepcopy(SHEET)
    sheet["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.beastmastery"],
        "learned_talent_record_ids": [], "automatic_sphere_component_record_ids": ["BEASTMASTERY_BASE_RIDER_PACKAGE"]}
    folder = tmp_path / "portable_characters" / "rider"
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    combat = CombatService(root, tmp_path)
    rider_id = FACTORY_ACTOR_PREFIX + "rider"
    view = combat.create_factory_match(project_ids=["rider"], control_modes={rider_id: "MANUAL"}, match_seed="P3-MOUNTED")
    table = TabletopService(combat, tmp_path)
    pool = table.summon_token_root() / "warhorse"
    pool.mkdir(parents=True)
    (pool / "test.png").write_bytes(b"fixture")
    match_id = view["match_id"]
    state = table.state(match_id)
    # Commit a real table action, then rebuild the service from the saved fight.
    for _ in range(20):
        if state["menu"].get("manual"):
            break
        state = table.auto_step(match_id, state["last_sequence"])["state"]
    menu = state["menu"]
    table.act(match_id, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    state = TabletopService(CombatService(root, tmp_path), tmp_path).state(match_id)
    rows = state["presentation"]["actors"]
    mount = next(a for a in rows if ".summon.mount.warhorse." in a["entity_id"])
    assert state["tokens"][mount["entity_id"]].endswith("/warhorse/test.png")
    return rows


def test_mounted_table_state_after_commit_and_reload(tmp_path, mounted_table_rows):
    fixture = tmp_path / "mounted-presentation.json"
    fixture.write_text(json.dumps(mounted_table_rows))
    subprocess.run(["node", str(Path(__file__).with_name("tabletop_mounted.cjs")), str(fixture)], check=True)


@pytest.mark.skipif(os.environ.get("P3_BROWSER") != "1", reason="set P3_BROWSER=1 to run Chromium rendering checks")
def test_mounted_browser_hit_testing_and_cards(tmp_path, mounted_table_rows, monkeypatch):
    """Real board/CSS and pointer events; requests never reach a live service."""
    playwright = pytest.importorskip("playwright.sync_api")
    executable = "/usr/bin/chromium"
    if not Path(executable).is_file():
        pytest.skip("Chromium is required for the mounted rendering regression")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    static = Path(__file__).resolve().parents[1] / "static" / "tabletop"
    source = (static / "tabletop.js").read_text()

    def function(name):
        start = source.index(f"function {name}(")
        return source[start:source.index("\n}", start) + 2]

    # Keep the saved presentation intact; pan the board to leave room for cards.
    script = """
      const rider = rows.find(a => a.conditions.some(c => c.condition_id === 'condition:typed.mounted'));
      const mount = rows.find(a => a.entity_id === rider.conditions.find(c => c.condition_id === 'condition:typed.mounted').source_actor_id);
      const actors = () => rows, actorById = id => rows.find(a => a.entity_id === id);
      const presentation = () => ({current_actor_id: null});
      const tokenLabels = () => new Map(), visibility = () => null;
      const TEAM_HEX = ['#b78b4a'], teamIndex = () => 0;
      const unseenByViewers = () => false, isManualActor = () => true;
      const shownCondition = () => true, conditionText = () => 'Mounted condition', conditionTone = () => 'neutral';
      // This sizing/card fixture explicitly chooses GM presentation. Player
      // disclosure is checked by the separate production identity regressions.
      const viewerStore = createViewerStore({viewId: 'mounted-browser'});
      viewerStore.bindGM('mounted-fixture');
      const app = {matchId: 'mounted-fixture', seatStatus: {seats: {}}, selected: new Set(),
        state: {tokens: {}, presentation: {battlefield: {blocked_cells: []}}}, targeting: null};
      const currentViewer = () => resolveViewerIdentity(viewerStore.read(app.matchId), rows, app.seatStatus);
      const isGMView = () => currentViewer().status === 'gm';
      const isOwnedActor = actor => currentViewer().isOwned(actor);
      const reconcileViewerIdentity = () => false, resumeViewerDialogs = () => {}, roofAudience = () => [];
      const $ = selector => document.querySelector(selector);
      window.clicks = [];
      const board = createBoard(document.querySelector('#ttViewport'), {onTokenClick: id => clicks.push(id)});
      board.setMap({width: 20, height: 14, background: {style: 'plain'}});
    """ + function("tokenGeometry") + "\n" + function("tokenImage") + "\n" + function("fogGeometry") + "\n" + function("renderTokens") + """
      renderTokens();
      board.centerOn(mount.position.x + 1, mount.position.y + 1);
      Object.assign(window, {board, rider, mount, tokenGeometry, renderTokens});
      window.ready = true;
    """
    html = '<link rel="stylesheet" href="/tabletop.css"><div id="ttViewport"></div>'
    html += '<script type="module">import {createBoard, OBJECT_FACE} from "/board.js";'
    html += 'import {tableObjectTokens} from "/object-presentation.js";'
    html += 'import {createViewerStore, resolveViewerIdentity} from "/viewer-identity.js";'
    html += "const rows = " + json.dumps(mounted_table_rows) + ";" + script + "</script>"

    def serve(route):
        name = urlparse(route.request.url).path.lstrip("/")
        if not name:
            route.fulfill(body=html, content_type="text/html")
        elif name in {p.name for p in static.glob("*.js")} | {"tabletop.css"}:
            route.fulfill(path=str(static / name), content_type="text/css" if name.endswith(".css") else "text/javascript")
        else:
            route.abort()

    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=executable, headless=True,
                                    args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = browser.new_page(viewport={"width": 1000, "height": 800})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", serve)
            page.goto("http://p3.test/")
            page.wait_for_function("window.ready === true")
            page.wait_for_function("!document.getAnimations().some(a => a.playState === 'running')")
            geometry = page.evaluate("""() => {
              const bounds = id => {const r = board.tokenNode(id).getBoundingClientRect();
                return {x:r.x, y:r.y, width:r.width, height:r.height};};
              return {rider:bounds(rider.entity_id), mount:bounds(mount.entity_id),
                riderId:rider.entity_id, mountId:mount.entity_id};
            }""")
            r, m = geometry["rider"], geometry["mount"]
            assert r["width"] == pytest.approx(51.2, abs=0.5)  # browsers lay out in 1/16 px
            assert m["width"] == pytest.approx(128, abs=0.5)
            assert r["x"] + r["width"] / 2 == pytest.approx(m["x"] + m["width"] / 2, abs=0.5)
            assert r["y"] + r["height"] / 2 == pytest.approx(m["y"] + m["height"] / 2, abs=0.5)
            card = page.locator(".tt-token-card")
            for creature, point, relation in [
                ("rider", (r["x"] + r["width"] / 2, r["y"] + r["height"] / 2), "Riding"),
                ("mount", (m["x"] + 18, m["y"] + m["height"] / 2), "Ridden by"),
            ]:
                page.mouse.move(*point)
                assert card.is_visible()
                text = card.inner_text()
                assert relation in text
                for row in mounted_table_rows:
                    if row["entity_id"] in {geometry["riderId"], geometry["mountId"]}:
                        assert row["display_name"] in text
                        assert f'{row["hit_points"]["current"]} / {row["hit_points"]["maximum"]} HP' in text
                page.mouse.click(*point)
                assert page.evaluate("clicks.at(-1)") == geometry[creature + "Id"]
                page.evaluate(f"board.setHighlights({{targets:[{{...{creature}.position,...tokenGeometry({creature})}}]}})")
                ring = page.locator(".tt-mark-target")
                assert float(ring.get_attribute("rx")) == pytest.approx(0.62 if creature == "rider" else 1.12)
                assert ring.bounding_box()["width"] == pytest.approx(79.36 if creature == "rider" else 143.36, abs=1)
            assert not errors
            page.screenshot(path=str(tmp_path / "mounted-browser.png"))
        finally:
            browser.close()
