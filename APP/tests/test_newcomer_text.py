"""N4 text regressions. Owner copies are read directly, never extracted or edited."""
import json
import os
from pathlib import Path
import subprocess
import zipfile

import pytest

APP = Path(__file__).resolve().parents[1]
ROSTER = Path(os.environ.get("N4_OWNER_ROSTER", "/var/tmp/auto-audit/astra/lock3-inputs/portable_characters"))


def test_newcomer_builders():
    subprocess.run(["node", str(Path(__file__).with_name("newcomer_text.test.mjs"))], check=True)


def test_resource_references_are_current_owner_text():
    from tools.newcomer_text_data import build_data, build_mark_durations, build_condition_readings
    result = subprocess.run(["node", "--input-type=module", "-e",
        "import {RESOURCE_RULES} from './static/tabletop/newcomer-data.js'; import {MARK_DURATIONS, CONDITION_READINGS} from './static/tabletop/zone-text-data.js'; console.log(JSON.stringify({resources:RESOURCE_RULES,marks:MARK_DURATIONS,conditions:CONDITION_READINGS}));"],
        cwd=APP, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"resources": build_data(), "marks": build_mark_durations(),
                                         "conditions": build_condition_readings()}


@pytest.mark.skipif(not ROSTER.is_dir(), reason="N4 read-only owner roster is not supplied")
def test_owner_roster_text_coverage(tmp_path):
    from combat.factory_compiler import compile_character
    from combat.presentation import _humanize
    terms = json.loads(subprocess.run(["node", "--input-type=module", "-e",
        "import {GLOSSARY} from './static/tabletop/newcomer.js'; console.log(JSON.stringify(GLOSSARY.flatMap(row=>row.terms)));"],
        cwd=APP, capture_output=True, text=True, check=True).stdout)
    roster = []
    for path in sorted(ROSTER.glob("*/current.zip")):
        with zipfile.ZipFile(path) as archive:
            ledger = json.loads(archive.read("Character_Master_Ledger.json"))
            sheet = json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json"))
        bundle = compile_character(sheet, actor_id=f"actor:n4.{path.parent.name}")
        resources = [{"name": _humanize(row["resource_id"]), "current": row.get("initial"), "maximum": row.get("maximum")}
                     for row in bundle["actor_template"]["resources"] if not row["resource_id"].startswith("resource:uses.")]
        zones = []
        for action in bundle["action_catalog"]:
            typed = action.get("parameters", {}).get("typed", {})
            spec = typed.get("zone_spec")
            if spec:
                zones.append({"trigger_profile": {"kind": "TYPED", **spec, "numbers": typed.get("numbers", {})},
                              "zone_id": "test", "duration_rounds": 10, "created_round": 0})
        assert resources, path.parent.name
        printed = json.dumps(sheet, ensure_ascii=False)
        roster.append({"name": sheet.get("identity", {}).get("name", path.parent.name),
                       "resources": resources, "zones": zones, "text": "\n".join(term for term in terms if term in printed)})
    fixture = tmp_path / "roster-text.json"
    fixture.write_text(json.dumps(roster))
    subprocess.run(["node", str(Path(__file__).with_name("newcomer_text.test.mjs")), str(fixture)], check=True)


@pytest.mark.skipif(os.environ.get("N4_BROWSER") != "1", reason="N4_BROWSER=1 requires a Chromium-capable environment")
def test_glossary_uses_only_the_native_tooltip(tmp_path):
    """Real table/sheet modules: hovering adds definitions to the title, and no second popup exists."""
    from urllib.parse import urlparse
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(tmp_path / "chromium-profile"),
            executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def serve(route):
            path = urlparse(route.request.url).path
            if path.startswith("/static/"):
                route.fulfill(path=str(APP / path.removeprefix("/")))
            elif path in ("/tabletop", "/tabletop/sheet"):
                name = "sheet" if path.endswith("sheet") else "tabletop"
                route.fulfill(path=str(APP / "static/tabletop" / f"{name}.html"))
            elif path.startswith("/api/"):
                body = {"/api/session": {"token": "n4-test"},
                        "/api/combat/factory-characters": [], "/api/combat/matches": [],
                        "/api/tabletop/maps": {"maps": [], "builtin": []},
                        "/api/tabletop/characters/n4/sheet": {"actor_id": "n4", "summary": {"name": "Test fighter"}, "buttons": [], "library": {"groups": []}},
                        "/api/tabletop/conditions": {"conditions": {}}}.get(path, {})
                route.fulfill(json=body)
            else:
                route.abort()

        page.route("**/*", serve)
        page.goto("http://n4.test/tabletop")
        page.wait_for_function("window.tabletop")
        page.evaluate("""() => {
            document.querySelector('#ttLobby').close();
            const log = document.querySelector('#ttNames');
            log.title = 'Spend 2 CP';
            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.innerHTML = '<g id="n4g"><title>Holds Martial Focus</title><rect width="40" height="40"/></g>';
            svg.setAttribute('style', 'position:fixed;left:0;top:0;width:40px;height:40px;z-index:99999');
            document.body.append(svg);
        }""")
        page.locator("#ttNames").hover()
        assert page.locator("#ttNames").get_attribute("title").startswith("Spend 2 CP\n\nCP means cultivation points")
        page.mouse.move(20, 20)
        assert "hold more than one" in page.locator("#n4g > title").text_content()
        assert page.locator("#newcomer-glossary").count() == 0
        assert page.locator("[popover]").count() == 0
        page.goto("http://n4.test/tabletop/sheet?project=n4")
        page.wait_for_function("document.querySelector('#sheet').getAttribute('aria-busy') === 'false'")
        page.locator("#theme-select").evaluate("el => el.title = 'Qi'")
        page.locator("#theme-select").hover()
        assert "Short rest" in page.locator("#theme-select").get_attribute("title")
        assert page.locator("#newcomer-glossary").count() == 0
        assert not errors
        context.close()
