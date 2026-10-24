"""Opt-in, lead-only phone screenshots against the scratch server. No fight writes.

Map, character and actions use the copied fight's real API. Controller-mode
changes are simulated in intercepted responses; no mutation reaches the server.
The reaction card is
an explicitly labelled intercepted fixture, so capturing it never advances or
alters the owner's fight. The scratch fight must be on the named viewer's turn.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlencode, urlparse

import pytest


class ScreenshotTransport:
    """Keep phone controller choices local while blocking every combat write."""

    def __init__(self, actor_id):
        self.actor_id = actor_id
        self.mode = None
        self.snapshot = None

    def handle(self, route):
        request = route.request
        path = urlparse(request.url).path
        if request.method == "POST" and path.endswith("/controller-mode"):
            body = request.post_data_json
            if (body.get("actor_id") == self.actor_id
                    and body.get("controller_mode") in {"MANUAL", "SUGGESTED"}):
                self.mode = body["controller_mode"]
                route.fulfill(status=200, content_type="application/json", body="{}")
                return
        if request.method != "GET":
            route.fulfill(status=409, content_type="application/json", body=json.dumps({
                "error": {"message": "Screenshot run is read-only", "code": "SCREENSHOT_READ_ONLY"}}))
        elif path.endswith("/state"):
            response = route.fetch()
            if response.status != 200:
                route.fulfill(response=response)
                return
            snapshot = response.json()
            if self.mode:
                for row in snapshot["presentation"]["actors"]:
                    if row["entity_id"] == self.actor_id:
                        row["controller"] = self.mode
                menu = snapshot.get("menu")
                if menu and menu.get("actor_id") == self.actor_id:
                    menu["control_mode"] = self.mode
                    menu["turn_mode"] = "Assisted" if self.mode == "SUGGESTED" else "Manual"
            self.snapshot = snapshot
            route.fulfill(status=200, content_type="application/json", body=json.dumps(snapshot))
        else:
            route.continue_()


def test_mobile_screenshot_transport_preserves_ranked_options_without_server_writes():
    """Regression: the old blanket POST rejection could never show Assisted."""
    from copy import deepcopy
    from types import SimpleNamespace

    actor = "actor:factory.phone"
    snapshot = {"presentation": {"actors": [{"entity_id": actor, "controller": "MANUAL"},
                                            {"entity_id": "other", "controller": "LOCAL_AUTO"}]},
                "menu": {"actor_id": actor, "manual": True, "control_mode": "MANUAL",
                         "ranked_slots": {"Action": ["ranked"]},
                         "actions": [{"options": [{"candidate_id": "ranked"}, {"candidate_id": "unranked"}]}]}}

    class Route:
        def __init__(self, method, path, body=None):
            self.request = SimpleNamespace(method=method, url="http://127.0.0.1:8799" + path, post_data_json=body)
            self.fetches = 0
            self.continued = False

        def fetch(self):
            assert self.request.method == "GET", "No mutation may reach the server"
            self.fetches += 1
            return SimpleNamespace(status=200, json=lambda: deepcopy(snapshot))

        def fulfill(self, **kwargs):
            self.result = kwargs

        def continue_(self):
            self.continued = True

    transport = ScreenshotTransport(actor)
    for mode in ("SUGGESTED", "MANUAL"):
        control = Route("POST", "/api/combat/matches/f/controller-mode", {"actor_id": actor, "controller_mode": mode})
        transport.handle(control)
        assert control.result["status"] == 200 and control.fetches == 0 and not control.continued
        state = Route("GET", "/api/tabletop/matches/f/state?fog=true")
        transport.handle(state)
        projected = json.loads(state.result["body"])
        assert projected["menu"]["control_mode"] == mode
        assert projected["menu"]["turn_mode"] == ("Assisted" if mode == "SUGGESTED" else "Manual")
        assert projected["menu"]["actions"] == snapshot["menu"]["actions"]
        assert projected["menu"]["ranked_slots"] == snapshot["menu"]["ranked_slots"]
        assert projected["presentation"]["actors"][1] == snapshot["presentation"]["actors"][1]
    for path, body in [("/api/tabletop/matches/f/act", {"candidate_id": "ranked"}),
                       ("/api/combat/matches/f/controller-mode", {"actor_id": "other", "controller_mode": "SUGGESTED"}),
                       ("/api/combat/matches/f/controller-mode", {"actor_id": actor, "controller_mode": "LOCAL_AUTO"})]:
        write = Route("POST", path, body)
        transport.handle(write)
        assert write.result["status"] == 409 and write.fetches == 0 and not write.continued
    # An opponent's turn must keep its real control and full menu.
    snapshot["menu"]["actor_id"] = "other"
    state = Route("GET", "/api/tabletop/matches/f/state")
    transport.handle(state)
    assert json.loads(state.result["body"])["menu"] == snapshot["menu"]


@pytest.mark.skipif(os.environ.get("MOBILE1_BROWSER") != "1",
                    reason="lead runs MOBILE1_BROWSER=1 outside sandbox; never launch a browser in a lane")
def test_mobile_play_phone_screenshots():
    pw = pytest.importorskip("playwright.sync_api")
    base = os.environ.get("MOBILE1_BASE", "http://127.0.0.1:8799").rstrip("/")
    parsed = urlparse(base)
    assert parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 8799, "Use only the scratch :8799 server."
    actor = os.environ.get("MOBILE1_ACTOR", "actor:factory.2ff3d22c-9024-4142-a7c3-54a32623f1b2")
    out = Path(os.environ.get("MOBILE1_SCREENSHOTS", "/var/tmp/auto-audit/MOBILE1-screenshots"))
    out.mkdir(parents=True, exist_ok=True)
    with pw.sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, device_scale_factor=1)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        # Simulate human control changes, while keeping the copied fight read-only.
        transport = ScreenshotTransport(actor)
        page.route("**/api/**", transport.handle)
        matches = context.request.get(f"{base}/api/combat/matches").json()
        match = os.environ.get("MOBILE1_MATCH") or next((r["match_id"] for r in matches if "Frozen Fishing Lake" in r.get("display_name", "")), None)
        assert match, "Set MOBILE1_MATCH to the owner's Frozen Fishing Lake scratch copy."
        url = f"{base}/play?" + urlencode({"match": match, "actor": actor, "view": "mobile1-browser"})
        page.goto(url, wait_until="networkidle")
        page.locator("#mapCover").wait_for(state="hidden")
        if page.locator("#actionSheet").is_visible():
            page.locator("#closeActions").tap()
        page.screenshot(path=str(out / "map.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= 390"), "Phone page overflows horizontally."
        # Exercise real touch pan and pinch through Chromium's input subsystem.
        cdp = context.new_cdp_session(page)
        before = page.locator(".tt-board").get_attribute("style")
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": 120, "y": 300, "id": 1}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": 160, "y": 320, "id": 1}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        assert page.locator(".tt-board").get_attribute("style") != before
        before = page.locator(".tt-board").get_attribute("style")
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": 100, "y": 320, "id": 1}, {"x": 220, "y": 320, "id": 2}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": 70, "y": 320, "id": 1}, {"x": 250, "y": 320, "id": 2}]})
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        assert page.locator(".tt-board").get_attribute("style") != before
        page.locator("#fit").tap()
        assert page.locator(".tt-token").first.evaluate("n => n.getBoundingClientRect().width") >= 28, "Fit must keep fighters readable."
        page.locator("#characterButton").tap()
        page.locator("#characterBody").get_by_text("Full rules text", exact=True).wait_for()
        page.locator("#characterBody details").first.wait_for()
        for resource in page.locator(".play-resource").all():
            assert not resource.locator("details").evaluate("n => n.open")
            assert len(resource.inner_text()) < 180, "Resource rules must remain behind Details."
        page.screenshot(path=str(out / "character-panel.png"))
        page.locator("#closeCharacter").tap()
        assert page.locator("#yourTurn").is_visible(), "Stage the scratch copy on this character's manual turn, then rerun. No automatic turn advancement."
        page.locator("#actionsButton").tap()
        assert not errors, f"Phone script errors before guided actions: {errors}"
        page.get_by_role("heading", name="Suggested plan — next step", exact=True).wait_for()
        page.get_by_role("button", name="Confirm this step", exact=True).wait_for()
        page.screenshot(path=str(out / "action-sheet.png"))
        page.get_by_role("button", name="Change — edit target, move or choose any alternative", exact=True).tap()
        for group in transport.snapshot["menu"]["actions"]:
            assert page.locator("#actionList").get_by_role("button", name=group["label"], exact=False).count() >= 1
        page.screenshot(path=str(out / "all-alternatives.png"))
        page.get_by_role("combobox", name="Played by", exact=True).select_option("MANUAL")
        page.wait_for_function("!document.querySelector('#actionList').textContent.includes('Suggested plan')")
        page.screenshot(path=str(out / "manual-actions.png"))
        small = page.locator("button:visible, select:visible, summary:visible").evaluate_all("""nodes => nodes.filter(n => !n.classList.contains('tt-token')).filter(n => {
            const r=n.getBoundingClientRect(); return r.width < 43.9 || r.height < 43.9;
        }).map(n=>n.textContent)""")
        assert not small, f"Controls smaller than 44px: {small}"
        page.locator("#closeActions").tap()
        snapshot = context.request.get(f"{base}/api/tabletop/matches/{match}/state?" + urlencode({"fog": "true", "fog_view": "own", "fog_actor_ids": actor})).json()
        reactor = next(a for a in snapshot["presentation"]["actors"] if a["entity_id"] == actor)
        opponent = next(a for a in snapshot["presentation"]["actors"] if a["entity_id"] != actor)
        snapshot["presentation"]["current_actor_id"] = opponent["entity_id"]
        snapshot["menu"] = {**snapshot["menu"], "actor_id": opponent["entity_id"], "manual": False}
        snapshot["pending_action"] = {"method": "auto_step", "request": {"decision_id": "screenshot", "state_version": 1}, "reactions": [],
            "reaction": {"title": "Screenshot fixture — your reaction", "reactor": reactor["display_name"], "reaction": "Parry (screenshot fixture)",
                "trigger": f"{opponent['display_name']} attacks {reactor['display_name']}.", "cost": "Your Reaction; no fight resources are spent in this screenshot fixture.",
                "summary": "Choose a response to the incoming attack. This card demonstrates a decision on another creature's turn.",
                "context": {"reactor_id": actor}, "choice": {"minimum": 1, "maximum": 1, "allow_decline": True,
                    "options": [{"id": f"fixture-{i}", "label": f"Eligible response {i+1}"} for i in range(12)]}}}
        def reaction_fixture(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(snapshot))
        page.route("**/api/tabletop/matches/*/state?*", reaction_fixture)
        page.locator("#reactionCard").wait_for(state="visible")
        assert page.locator("#reactionBody .play-options button").count() == 13
        page.screenshot(path=str(out / "reaction-card-fixture.png"))
        assert not errors, errors
        context.close()
        browser.close()
