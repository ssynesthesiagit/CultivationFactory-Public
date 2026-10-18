"""Lead must run outside the sandbox; ACBREAK_BROWSER=1 enables Chromium.

Loads the shipped pop-out sheet with a real Scratch character compiled by the
production TabletopService into a disposable test directory. No live data.
"""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading

import pytest

pytestmark = pytest.mark.skipif(os.getenv("ACBREAK_BROWSER") != "1",
                              reason="Lead must run Chromium outside the sandbox")


def test_real_sheet_ac_hover_click_and_live_update(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    from tests.test_ac_breakdown import ROOT, scratch_sheet_payload

    payload = scratch_sheet_payload(tmp_path)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.startswith("/api/tabletop/characters/abcdef19/sheet"):
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)
            elif self.path.startswith("/api/"):
                self.send_error(404)
            else:
                super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
            try:
                # The owner's pop-out is opened by tabletop.js at 1280 x 860.
                page = browser.new_page(viewport={"width": 1280, "height": 860})
                page.goto(f"http://127.0.0.1:{server.server_port}/static/tabletop/sheet.html?project=abcdef19")
                ac = page.locator("#vitals .ac")
                expect(ac).to_be_visible()
                assert not ac.get_attribute("title")
                ac.hover()
                card = page.locator(".tt-hovercard:visible")
                expect(card).to_have_count(1)
                expect(card).to_contain_text("10 base + 2 Dexterity modifier = 12")
                expect(card).to_contain_text("Qi Armor")
                output = Path(os.getenv("ACBREAK_SCREENSHOT_DIR", "/var/tmp/auto-audit/fix/SOL191-browser"))
                output.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(output / "SOL191-sheet-hover.png"))
                page.keyboard.press("Escape")
                expect(card).to_have_count(0)
                ac.click()
                expect(card).to_have_count(1)
                expect(card).to_contain_text("Base calculation")
                page.screenshot(path=str(output / "SOL191-sheet-click.png"))
                # Use the actual connection protocol, not an injected renderer.
                page.evaluate('''() => {
                  const channel = new BroadcastChannel('tianxia-tabletop');
                  channel.postMessage({type: 'actor', actor_id: 'actor:factory.abcdef19',
                    armor_class: 17, armor_base: 12, armor_modifiers: [{source: 'Shield spell', value: 5}],
                    hp: {current: 9, maximum: 9}, resources: [], conditions: [], legal_button_ids: [],
                    turn: {is_current: true, manual: true, action: true, bonus_action: true, reaction: true}});
                  setTimeout(() => channel.close(), 500);
                }''')
                expect(ac.locator(".stat-big")).to_have_text("17")
                expect(card).to_contain_text("Current AC in this fight: 17")
                page.keyboard.press("Escape")
                ac.click()
                expect(card).to_contain_text("Current AC in this fight: 17")
                expect(card).to_contain_text("Shield spell: +5 AC")
                page.screenshot(path=str(output / "SOL191-sheet-live.png"))
                # Also capture the owner's Character Sheets rail at the same
                # desktop width, using the shipped page and real snapshot.
                snapshot = json.loads((ROOT / "tests/fixtures/gm_sheet/scratch_owner_sheet_snapshot.fixture.json").read_text())
                page.goto(f"http://127.0.0.1:{server.server_port}/static/index.html")
                page.evaluate('''snapshot => {
                  showScreen('projects');
                  renderOwnerSheet({project_id: 'abcdef19', owner_character_sheet: snapshot});
                }''', snapshot)
                owner_ac = page.locator(".owner-rail-stats [data-tip-click]")
                expect(owner_ac).to_have_count(1)
                owner_ac.hover()
                owner_card = page.locator(".tt-hovercard:visible")
                expect(owner_card).to_have_count(1)
                expect(owner_card).to_contain_text("10 base + 2 Dexterity modifier = 12")
                assert not owner_ac.get_attribute("title")
                page.screenshot(path=str(output / "SOL191-owner-sheet-hover.png"))
                page.keyboard.press("Escape")
                owner_ac.click()
                expect(owner_card).to_have_count(1)
                page.screenshot(path=str(output / "SOL191-owner-sheet-click.png"))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
