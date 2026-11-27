"""The fighter picker in Fights > New fight (OPUSUI2, owner 2026-10-04: "I want the character selection with add fighter
to be better organized, listed by recency would be good, but also better ways to choose; organize the UI to be larger
and more visual, with searches, maybe the tokens to select").

- the character list carries the read-only card fields (subpath, spheres, edited_at; token_url when a token exists) and
  the saved-fight list carries each fight's dates, which give "played" recency; creating a fight is unchanged;
- the picker's search, filters, sorting and the add-to-team result (identical to the old dropdown) run under node
  (tests/fighter_picker.test.mjs), with the builder's own node tests;
- a rendered check of the panel is opt-in (CF_UI_BROWSER=1, /usr/bin/chromium) for the lead.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop import ButtonStore

from tests.test_factory_combat_compiler import SHEET

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
PID = "5f1c2d3e-0000-4000-8000-00000000c0de"
SUBPATH_SHEET = {**SHEET, "path_and_subpath": {**(SHEET.get("path_and_subpath") or {}),
                                               "subpath": {"name": "Iron Body Disciple", "subpath_id": "tianxia.subpath.test"}}}


def _install(userdata: Path, project_id: str, sheet: dict) -> Path:
    folder = userdata / "portable_characters" / project_id
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    return folder / "current.zip"


def test_character_rows_carry_the_card_fields_and_fights_their_dates(tmp_path):
    package = _install(tmp_path, PID, SUBPATH_SHEET)
    old = time.time() - 3600
    os.utime(package, (old, old))
    service = CombatService(ROOT, tmp_path)
    [row] = service.factory_characters()
    assert row["subpath"] == "Iron Body Disciple"
    assert row["spheres"] == ["Brute", "Sabers"]  # the rules' names, not record ids
    assert row["edited_at"] and row["edited_at"].endswith("Z")
    first = row["edited_at"]
    # A change made at the table (here a rename) counts as an edit, and the cached row follows it.
    ButtonStore(tmp_path / "tabletop_buttons").save_display_name(PID, "Renamed Hero")
    [row] = service.factory_characters()
    assert row["display_name"] == "Renamed Hero" and row["edited_at"] > first
    # A character without a Subpath or Spheres still lists, with empty card fields.
    _install(tmp_path, "plain-project", {"identity": {"display_name": "Plain"}})
    plain = next(row for row in service.factory_characters() if row["project_id"] == "plain-project")
    assert plain["subpath"] is None and plain["spheres"] == []
    # Fights keep being created exactly as before, and the saved-fight list now says when each was made.
    view = service.create_factory_match(project_ids=[PID], match_seed="PICKER-RECENCY")
    [listed] = [entry for entry in service.list_matches() if entry["match_id"] == view["match_id"]]
    assert listed["created_at"].endswith("Z") and listed["updated_at"].endswith("Z")
    assert FACTORY_ACTOR_PREFIX + PID in listed["participant_control_modes"]
    # Strings only: what the picker reads survives JSON as it is.
    assert json.loads(json.dumps(row)) == row


def test_the_list_route_adds_the_table_token_only_for_characters_that_have_one(tmp_path):
    from app.api import create_app
    from app.core import Settings
    from combat.portraits import TokenStore

    data = tmp_path / "app-data"
    app = create_app(settings=Settings.from_env(ROOT, data))
    _install(data, PID, SUBPATH_SHEET)
    _install(data, "abcdef01-2222-4333-8444-555566667777", {"identity": {"display_name": "No Token"}})
    tokens = data / "tabletop_tokens"
    tokens.mkdir(parents=True)
    (tokens / f"{PID}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    route = next(route for route in app.routes if route.path == "/api/combat/factory-characters" and "GET" in route.methods)
    rows = {row["project_id"]: row for row in route.endpoint()}
    # The same picture the table's token shows (the token store the board reads).
    assert rows[PID]["token_url"] == TokenStore(tokens).url(PID)
    assert rows[PID]["token_url"].startswith(f"/api/tabletop/characters/{PID}/token.png?v=")
    assert "token_url" not in rows["abcdef01-2222-4333-8444-555566667777"]
    assert rows[PID]["subpath"] == "Iron Body Disciple"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_picker_and_fight_builder_node_checks():
    for script in ("tests/fighter_picker.test.mjs", "tests/fight_setup.test.mjs"):
        result = subprocess.run(["node", "--test", str(ROOT / script)], capture_output=True, text=True, cwd=ROOT, timeout=60)
        assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    subprocess.run(["node", str(ROOT / "tests/team_saves.cjs")], check=True, timeout=30)


def test_the_picker_uses_only_theme_colours_and_the_lobby_points_to_it():
    css = (STATIC / "tabletop/tabletop.css").read_text(encoding="utf-8")
    block = css[css.index("/* ---------- fighter picker"):]
    assert "#" not in block.replace("#ttPicker", "") and "rgb" not in block
    assert "var(--cf-" in block
    html = (STATIC / "tabletop/tabletop.html").read_text(encoding="utf-8")
    assert "+ Add fighter</strong> to choose from cards" in html


@pytest.mark.skipif(os.getenv("CF_UI_BROWSER") != "1", reason="opt-in browser check for the lead (CF_UI_BROWSER=1)")
def test_picker_panel_in_a_real_browser():
    playwright = pytest.importorskip("playwright.sync_api")
    rows = [{"project_id": f"p{index:03d}", "display_name": f"Hero {index}", "cultivation_level": index % 20 + 1,
             "path": "Qi Cultivation" if index % 2 else "Body Cultivation", "subpath": "Storm Caller" if index == 7 else None,
             "spheres": ["Fire", "Water"] if index % 3 else ["Lightning"], "edited_at": f"2026-09-{index % 28 + 1:02d}T00:00:00Z"}
            for index in range(120)]
    fights = [{"match_id": "m", "created_at": "2026-10-03T00:00:00Z",
               "participant_control_modes": {"actor:factory.p042": "MANUAL"}}]
    page_html = f"""<!doctype html><html data-theme="lacquer"><head>
      <link rel="stylesheet" href="/static/themes.css"><link rel="stylesheet" href="/static/tabletop/tabletop.css"></head>
      <body class="tt-app"><script type="module">
        import {{fighterPicker}} from "/static/tabletop/fighter-picker.js";
        window.picks = [];
        fighterPicker.rememberFights({json.dumps(fights)});
        window.openPicker = () => fighterPicker.open({{characters: {json.dumps(rows)}, teamName: "Team 1", mode: "MANUAL",
          taken: new Set(["p001"]), onPick: pick => (window.picks.push(pick), true), onCancel: () => window.cancelled = true}});
        window.ready = true;
      </script></body></html>"""

    def serve(route):
        path = route.request.url.split("://", 1)[1].split("/", 1)[1].split("?", 1)[0]
        if path.startswith("static/"):
            file = ROOT / path
            if file.suffix not in (".css", ".js"):
                return route.fulfill(path=str(file))  # fonts and images are binary
            kind = "text/css" if file.suffix == ".css" else "text/javascript"
            return route.fulfill(body=file.read_text(encoding="utf-8"), content_type=kind)
        return route.fulfill(body=page_html, content_type="text/html")

    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"], headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.route("**/*", serve)
            page.goto("http://picker.test/")
            page.wait_for_function("window.ready === true")
            page.evaluate("openPicker()")
            dialog = page.locator("dialog.tt-picker")
            playwright.expect(dialog).to_be_visible()
            assert page.evaluate("document.activeElement.type") == "search"
            # Recently used row first, with the character that played last.
            assert dialog.locator(".tt-picker-row .tt-pick-card").first.get_attribute("data-pid") == "p042"
            assert dialog.locator(".tt-picker-grid .tt-pick-card").count() == 120
            assert dialog.locator('.tt-pick-card[data-pid="p001"]').first.is_disabled()
            # Type to search, then Enter adds the first match.
            page.keyboard.type("storm")
            playwright.expect(dialog.locator(".tt-picker-grid .tt-pick-card")).to_have_count(1)
            page.keyboard.press("Enter")
            assert page.evaluate("window.picks") == [{"pid": "p007", "mode": "MANUAL"}]
            playwright.expect(dialog).to_have_count(0)
            # Arrow keys from the search box into the grid, AI chosen, Enter on a card.
            page.evaluate("openPicker()")
            page.locator(".tt-picker-search").fill("")
            page.locator(".tt-picker-mode input[value=LOCAL_AUTO]").check()
            page.locator("select").last.select_option("name")
            page.locator(".tt-picker-search").focus()
            page.keyboard.press("ArrowDown")
            page.keyboard.press("ArrowRight")
            focused = page.evaluate("document.activeElement.dataset.pid")
            page.keyboard.press("Enter")
            assert page.evaluate("window.picks")[-1] == {"pid": focused, "mode": "LOCAL_AUTO"}
            # Narrow screens: the panel fills the width and the grid still scrolls.
            page.set_viewport_size({"width": 390, "height": 760})
            page.evaluate("openPicker()")
            box = page.locator("dialog.tt-picker").bounding_box()
            assert box["width"] <= 390
            assert page.evaluate("(() => { const s = document.querySelector('.tt-picker-scroll'); return s.scrollHeight > s.clientHeight; })()")
            page.keyboard.press("Escape")
            page.wait_for_function("window.cancelled === true")  # the dialog's close event is asynchronous
        finally:
            browser.close()
