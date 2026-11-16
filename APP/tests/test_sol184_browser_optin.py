"""Lead-only Chromium check of the real initiative renderer; no GUI by default."""
import json
import os

import pytest

from tests.hunt15_support import LEFT, act, fight, reload, turn
from tests.h1_support import ROOT


@pytest.fixture
def skipped_actor_presentation(tmp_path):
    """Reach an omitted slot through persisted Table actions, without a browser."""
    combat, table, mid = fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"], ally=[],
        effects=[{"type":"damage", "flat":10000, "damage_types":["untyped"], "applies_to":"self"}])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"

    # Defeat during an already-started turn leaves its forced automatic End.
    # It is not a player decision and has no manual end_turn menu entry.
    defeated = table.state(mid)
    assert defeated["menu"]["actor_id"] == LEFT
    assert not defeated["menu"]["manual"]
    assert "end_turn" not in defeated["menu"]
    assert defeated["pending_action"] is None
    assert table.auto_step(mid, defeated["last_sequence"])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    dead = engine.state.actors[LEFT]
    assert not dead.active
    turns_started = dead.turns_started
    order = engine.state.initiative_order
    dead_slot = order.index(LEFT)

    # Cross the next nominal slot, rather than merely ending the death turn.
    turn(table, mid, order[(dead_slot - 1) % len(order)])
    before = reload(combat, mid).state.event_sequence
    assert act(table, mid, "end")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    expected_actor = order[(dead_slot + 1) % len(order)]
    assert engine.state.current_actor_id == expected_actor
    assert engine.state.actors[LEFT].turns_started == turns_started
    assert not any(event.actor_id == LEFT and event.event_type in ("TURN_STARTED", "TURN_ENDED")
                   for event in engine.events if event.sequence > before)
    shown = table.state(mid)
    assert shown["menu"]["actor_id"] == expected_actor
    assert shown["menu"]["end_turn"]
    presentation = shown["presentation"]
    assert not presentation["terminal"]
    assert presentation["current_actor_id"] == expected_actor
    assert LEFT in presentation["initiative_order"]
    assert not next(actor for actor in presentation["actors"] if actor["entity_id"] == LEFT)["active"]
    return presentation


def test_skipped_actor_browser_fixture_without_chromium(skipped_actor_presentation):
    """The browser's exact scenario must work in ordinary sandbox pytest runs."""
    assert skipped_actor_presentation["current_actor_id"] != LEFT


@pytest.mark.skipif(os.environ.get("SOL184_BROWSER") != "1", reason="Lead must run SOL184_BROWSER=1 outside the sandbox")
def test_skipped_actor_is_not_the_acting_chip_in_chromium(skipped_actor_presentation):
    pw = pytest.importorskip("playwright.sync_api")
    presentation = skipped_actor_presentation
    source = (ROOT / "static/tabletop/tabletop.js").read_text()
    def function(name):
        start = source.index(f"function {name}(")
        return source[start:source.index("\n}", start)+2]
    script = "const p = " + json.dumps(presentation) + ";" + """
        const $ = s => document.querySelector(s), presentation = () => p;
        const actorById = id => p.actors.find(a => a.entity_id === id);
        const TEAM_COLORS = ['gold'], teamIndex = () => 0, isManualActor = () => false;
        const app = {state:{tokens:{}}}, initials = n => n.slice(0,2);
        const selectActor = () => {}, board = {centerOn: () => {}};
    """ + function("tokenImage") + "\n" + function("renderInitiative") + "\nrenderInitiative();"
    with pw.sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.set_content('<ol id="ttInitiative"></ol>')
            page.evaluate(script)
            assert page.locator("#ttInitiative .is-current").count() == 1
            assert "River Keeper" not in page.locator("#ttInitiative .is-current").inner_text()
            assert "River Keeper" in page.locator("#ttInitiative").inner_text()
        finally:
            browser.close()
