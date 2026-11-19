"""Lead-only visual check; never launch a browser in the worker sandbox."""
import json
import os
import subprocess

import pytest

from tests.test_sol113_dying_table import fight, until_turn
from tests.test_factory_live_match import ROOT


def test_automatic_turn_ui_without_a_browser():
    subprocess.run(["node", str(ROOT / "tests/sol113_table_ui.cjs")], check=True)


@pytest.mark.skipif(os.environ.get("SOL113_BROWSER") != "1", reason="lead must run SOL113_BROWSER=1 outside the sandbox")
def test_dying_tally_in_actual_table_inspector(tmp_path, monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    service, table, mid, target = fight(tmp_path, monkeypatch)
    state = until_turn(service, table, mid, target, 4)
    row = next(a for a in state["presentation"]["actors"] if a["entity_id"] == target)
    source = (ROOT / "static/tabletop/tabletop.js").read_text()
    start = source.index("function renderInspector(")
    inspector = source[start:source.index("\n}", start) + 2]
    start = source.index("async function renderActionBar(")
    action_bar = source[start:source.index("\n}", start) + 2]
    start = source.index("async function toggleAIPlayback(")
    playback = source[start:source.index("\n}", start) + 2]
    start = source.index("function playedByWord(")
    played_by = source[start:source.index("\n}", start) + 2]
    seats = (ROOT / "static/tabletop/seats.js").read_text().replace("export ", "")
    script = seats + "\nconst actor = " + json.dumps(row) + ";" + """
      const $ = s => document.querySelector(s), app = {selected: new Set([actor.entity_id]), menu: {end_turn: 'end'}, speed: 0.5, playing: false};
      const actorById = () => actor, projectOf = () => null, presentation = () => ({terminal: false, current_actor_id: actor.entity_id});
      const TEAM_COLORS = ['gold'], teamIndex = () => 0, initials = () => 'TD';
      const pct = (n,d) => 100*n/d, escapeHtml = x => String(x ?? '');
      const resourceText = () => '', shownCondition = () => true, conditionTone = () => 'neutral';
      const conditionText = () => 'Unconscious: no actions, reactions, or movement until healed.';
      const isManualActor = () => true, setControl = () => {}, board = {centerOn: () => {}};
      const automaticSlot = actor => actor && actor.active === false;
      const movementLeft = () => 0;
    """ + played_by + inspector + playback + action_bar + "\nrenderInspector(); renderActionBar();"
    with pw.sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"], headless=True)
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.set_content('<div id="ttInspector"></div><div id="ttActionBar"></div>')
            page.add_script_tag(content=script)
            assert "Death saving throws: 2 successes, 0 failures" in page.locator("#ttInspector").inner_text()
            assert "Unconscious" in page.locator("#ttInspector").inner_text()
            assert "no actions, reactions, or movement" in page.locator("#ttActionBar").inner_text()
            assert "Your turn" not in page.locator("#ttActionBar").inner_text()
            assert not errors
        finally:
            browser.close()
