"""Your own fighter's view is the default fog of war (owner 2026-10-04, live round 25).

"I want the default vision mode to not share vision with your allies, but keep that as an option as
allies view." Two halves, both covered here at the level they failed:

* the service hands the table a visibility set PER VIEWER (``TabletopService.state``'s
  ``fog_perception``), never per team, so both views read the same rules answer;
* the Fog picker decides whose perception is drawn (static/tabletop/fog_view.js), defaults to the
  creature the player controls, and remembers the choice on that device.

The picker half runs in ``tests/fog_view.test.mjs`` (node --test, no browser): the real fog_view
module, the real tabletop.js fog functions and the real visibility-polygon and line-of-sight code
over a hand-built yard, and -- given a fixture written from a real fight here, handed over in
``FOG_VIEW_FIXTURE`` because ``node --test`` forwards no positional arguments to the test file -- over
that fight's own actors and its real per-viewer answer. The run below requires that case to execute,
so it cannot pass by being skipped. Nothing here changes a rule, a roll or saved state.
"""
from __future__ import annotations

import json
import os
import subprocess
import xml.etree.ElementTree as ElementTree
import zipfile
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

PICKER_GATE = Path(__file__).with_name("fog_view.test.mjs")

# The one case that runs the shipped code over a real fight, by name, so a skipped or missing run of
# it is a failure here instead of a green suite that proved nothing (OCF6r1 review finding).
REAL_FIGHT_CASE = "a real mixed-control fight shows only your own fighter"

MINE = FACTORY_ACTOR_PREFIX + "ocf6-mine"
ALLY = FACTORY_ACTOR_PREFIX + "ocf6-ally"
FOE = FACTORY_ACTOR_PREFIX + "ocf6-foe"


def run_picker_gate(fixture: Path | None = None, require: bool = False) -> ElementTree.Element:
    """Run the real Node fog gate and return its JUnit report.

    The fixture path goes through ``FOG_VIEW_FIXTURE``, not a positional argument: ``node --test``
    treats every argument after the test file as another TEST FILE and forwards none of them to the
    file under test, so ``node --test gate.mjs fixture.json`` used to "pass" while the real-fight case
    silently skipped. ``FOG_VIEW_FIXTURE_REQUIRED`` makes the Node gate throw at load time when the
    fixture is missing, so the run cannot come back green with the case skipped.

    JUnit is the reporter to read rather than TAP, whose ``ok`` lines truncate long case names.
    """
    environment = dict(os.environ)
    environment.pop("FOG_VIEW_FIXTURE", None)
    environment.pop("FOG_VIEW_FIXTURE_REQUIRED", None)
    if fixture is not None:
        environment["FOG_VIEW_FIXTURE"] = str(fixture)
    if require:
        environment["FOG_VIEW_FIXTURE_REQUIRED"] = "1"
    # Run in one process: sandboxed Node 24 process isolation can report only the
    # file, omitting every named case even though the subprocess exits successfully.
    done = subprocess.run(["node", "--test", "--test-isolation=none", "--test-reporter=junit", str(PICKER_GATE)],
                          check=False, capture_output=True, text=True, env=environment)
    if done.returncode:
        # A failing or refused run reports the reason in the report itself, so show it rather than a
        # bare exit code.
        raise AssertionError(f"the node fog gate failed (exit {done.returncode}):\n{done.stdout[-4000:]}"
                             f"\n{done.stderr[-2000:]}")
    return ElementTree.fromstring(done.stdout)


def assert_case_ran(report: ElementTree.Element, name: str) -> None:
    """The named case must be reported, and reported as run rather than skipped.

    ``run_picker_gate`` has already turned a failing case into a raised assertion; this closes the
    skip hole on top of it, so the real-fight coverage cannot go back to being quietly absent.
    """
    cases = [case for case in report.iter("testcase") if case.get("name") == name]
    assert len(cases) == 1, (
        f"{name!r} was not reported by the node gate at all:\n{ElementTree.tostring(report)}")
    assert not list(cases[0]), (
        f"{name!r} was skipped or failed instead of run:\n{ElementTree.tostring(report)}")


def test_fog_picker_runs_the_shipped_javascript():
    """No browser and no canvas: `node --test` executes the real modules directly."""
    run_picker_gate()


@pytest.fixture(scope="module")
def walled_yard(tmp_path_factory):
    """A 16x8 yard split by one sight-blocking wall.

    ``MINE`` stands on the near side at (2, 4); ``ALLY`` and ``FOE`` stand together on the far side
    at (12, 4) and (13, 4). So every square only the ally can see is exactly the foe's corner, and a
    wall -- not a range edge -- is what hides it from the player's own fighter.
    """
    tmp_path = tmp_path_factory.mktemp("ocf6-yard")
    ids = [MINE, ALLY, FOE]
    docs = []
    for aid in ids:
        doc = sheet([], cl=17)
        doc["identity"]["display_name"] = aid.removeprefix(FACTORY_ACTOR_PREFIX).title()
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        docs.append(doc)
    bundles = [compile_character(doc, actor_id=aid) for aid, doc in zip(ids, docs)]
    combat = CombatService(ROOT, tmp_path)
    saved = combat.tabletop_maps.save({
        "display_name": "OCF6 walled yard", "width_squares": 16, "height_squares": 8,
        # A filled rect covers the square centres between its points, so x 8..9 is one column.
        "walls": [{"shape": "rect", "points": [[8, 0], [9, 7]], "filled": True}], "starts": {}})
    arena = combat.factory_arenas()["battlefield:map." + saved["map_id"]]
    mid = combat._finish_factory_match(
        bundles, ids, {MINE: "team:a", ALLY: "team:a", FOE: "team:b"},
        {MINE: {"x": 2, "y": 4}, ALLY: {"x": 12, "y": 4}, FOE: {"x": 13, "y": 4}},
        arena, [MINE, ALLY], [FOE],
        # The player drives MINE by hand; ALLY is an ally the AI plays for them.
        control_modes={MINE: "MANUAL", ALLY: "LOCAL_AUTO", FOE: "MANUAL"},
        match_seed="OCF6-OWN-VISION", display_name="OCF6", maximum_rounds=10)["match_id"]
    return combat, TabletopService(combat, tmp_path), tmp_path, mid


def test_the_service_answers_sight_per_viewer_not_per_team(walled_yard):
    """The table is handed one visibility set for EVERY creature, so a view is only a choice of
    which sets to read. Nothing is grouped by team, and the ally's answer is not merged into the
    player's fighter's."""
    _combat, table, _tmp_path, mid = walled_yard
    fog = table.state(mid, fog=True)["fog_perception"]
    assert {MINE, ALLY, FOE} <= set(fog), "every creature on the map gets its own answer"
    foe_square = [13, 4]
    assert foe_square in fog[ALLY]["cells"], "the ally does see the foe's square"
    assert FOE in fog[ALLY]["creatures"]
    assert foe_square not in fog[MINE]["cells"], "the player's fighter cannot see it through a wall"
    assert FOE not in fog[MINE]["creatures"]
    assert [2, 4] in fog[MINE]["cells"], "a fighter always sees its own square"
    assert MINE in fog[ALLY]["creatures"], "a teammate stays known even out of sight"


def test_the_fight_says_which_creatures_this_device_drives(walled_yard):
    """The picker keys "my character's view" off the fight's own control modes AND its sides, so the
    default view is the fighter the player controls -- not the whole side, and not a foe the GM
    drives by hand (OCF6 review finding 1: this fight is that exact case, and it was only ever
    asserted as control-mode strings, never as the view it produces)."""
    _combat, table, _tmp_path, mid = walled_yard
    actors = {row["entity_id"]: row for row in table.state(mid)["presentation"]["actors"]}
    assert actors[MINE]["controller"] == "MANUAL"
    assert actors[ALLY]["controller"] == "LOCAL_AUTO", "the ally is played by the AI, so it is not 'mine'"
    assert actors[FOE]["controller"] == "MANUAL", "a hand-driven foe is never the player's own fighter"
    assert actors[MINE]["team_index"] == actors[ALLY]["team_index"] == 0
    assert actors[FOE]["team_index"] == 1, "the Game Master's foe fights on the other side"


def test_the_table_hides_a_foe_the_game_master_drives(walled_yard, tmp_path):
    """The mixed-control fight above, through the real table code: the shipped viewer selection and
    the real TabletopService fog answer decide what the player can see.

    This is the level the bug showed at. The service hands out one visibility set per viewer, so the
    only thing standing between the player and the Game Master's foe's whole territory is which
    viewer the table picks -- and with a foe marked MANUAL, "any fighter I drive by hand" picked the
    enemy as well.

    The run is required to execute the real-fight case: ``FOG_VIEW_FIXTURE_REQUIRED`` makes the Node
    gate throw when the fixture does not arrive, and the JUnit report is checked for this case by
    name, so a skipped case fails here rather than passing silently.
    """
    _combat, table, _root, mid = walled_yard
    state = table.state(mid, fog=True)
    fixture = tmp_path / "mixed-control-fight.json"
    # The fixture carries the service's own field names, including the battlefield's width_squares /
    # height_squares, because the Node harness reads exactly what TabletopService sends.
    fixture.write_text(json.dumps({
        "actors": state["presentation"]["actors"],
        "fog_perception": state["fog_perception"],
        "battlefield": {key: state["presentation"]["battlefield"][key]
                        for key in ("width_squares", "height_squares")}}), encoding="utf-8")
    assert_case_ran(run_picker_gate(fixture, require=True), REAL_FIGHT_CASE)


def test_the_game_master_view_asks_for_nothing_and_a_reload_keeps_the_answer(walled_yard):
    """Off (Game Master view) is unchanged, and reloading the saved fight from disk reproduces the
    same per-viewer sets and the same fight state (item 7: nothing here is fight state, so nothing is
    lost or gained, and a fresh reader must reach the same answer)."""
    combat, table, tmp_path, mid = walled_yard
    assert table.state(mid)["fog_perception"] == {}, "with fog off the table is sent no fog at all"
    before = table.state(mid, fog=True)["fog_perception"]
    reloaded = TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid, fog=True)["fog_perception"]
    assert reloaded == before
    version = combat._load_session(mid).engine.state.state_version
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.state_version == version


def test_the_saved_fight_keeps_no_view_choice(walled_yard):
    """The view is a per-device display choice: it lives in localStorage, never in the saved fight,
    so an old saved fight replays identically and a Game Master sees the whole map by default."""
    combat, table, _tmp_path, mid = walled_yard
    stored = "\n".join(path.read_text(encoding="utf-8", errors="ignore")
                       for path in sorted(combat._match_dir(mid).rglob("*.json")))
    assert "fog_perception" not in stored, "the table's answer is derived for the reader, never saved"
    assert table.state(mid)["presentation"]["actors"][0]["display_name"]
