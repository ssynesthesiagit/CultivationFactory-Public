"""Per-tab view identity through real JS modules and a real persisted Willow move.

No API or save schema changes: an ephemeral match supplies unmodified service
state/event responses, then the production table/board functions replay them.
"""
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ElementTree

ROOT = Path(__file__).resolve().parents[1]
REAL_CASE = "real Willow commit and cold reload preserve distinct player roofs through production playback"


def run_node(path, *, recording=None):
    environment = {**os.environ, "SOL219_BROWSER": "0"}
    environment.pop("VIEWER_IDENTITY_RECORDING", None)
    environment.pop("VIEWER_IDENTITY_RECORDING_REQUIRED", None)
    if recording:
        environment["VIEWER_IDENTITY_RECORDING"] = str(recording)
        environment["VIEWER_IDENTITY_RECORDING_REQUIRED"] = "1"
    result = subprocess.run(
        ["node", "--test", "--test-isolation=none", "--test-reporter=junit", path],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return ElementTree.fromstring(result.stdout)


def test_viewer_identity_module():
    run_node("tests/viewer_identity.test.mjs")


def test_real_willow_move_reload_and_two_player_views(tmp_path):
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.test_factory_live_match import _install
    from tests.test_lock2_persistence import act

    data = tmp_path / "fight"
    projects = ["identity-mine", "identity-ally", "identity-foe"]
    mine, ally, foe = [FACTORY_ACTOR_PREFIX + project for project in projects]
    for project in projects:
        _install(data, project)
    combat = CombatService(ROOT, data)
    village = combat.tabletop_maps.get("builtin-willow-village-compound")
    saved = combat.tabletop_maps.save({
        **village, "map_id": "identity-doorway", "display_name": "Identity doorway",
        "starts": {"team1": [[6, 11], [13, 15]], "team2": [[26, 15]]},
    })
    mid = combat.create_factory_match(
        project_ids=projects[:2], opponent_actor_ids=[foe],
        arena_id="battlefield:map." + saved["map_id"],
        control_modes={actor_id: "MANUAL" for actor_id in (mine, ally, foe)},
        match_seed="PLAYER-VIEW-WILLOW", maximum_rounds=5,
    )["match_id"]
    table = TabletopService(combat, data)
    for _ in range(6):
        if table.state(mid)["menu"]["actor_id"] == mine:
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == mine

    steps = []
    for path, inside in [
        ([{"x": 6, "y": 11}, {"x": 6, "y": 10}, {"x": 6, "y": 9}], True),
        ([{"x": 6, "y": 9}, {"x": 6, "y": 10}, {"x": 6, "y": 11}], False),
    ]:
        before = table.state(mid, fog=True)
        menu = before["menu"]
        quote = table.preview_move_path(mid, menu["decision_id"], menu["state_version"], mine, path)
        committed = table.commit_move_path(
            mid, quote["candidate"]["candidate_id"], menu["decision_id"], menu["state_version"],
            mine, path, before["last_sequence"],
        )
        assert committed["status"] == "COMMITTED"
        assert any(row["event_type"] == "MOVEMENT_COMMITTED" for row in committed["events"]["events"])
        # Cold service reconstruction must recover the same committed position
        # and pass the existing mechanical journal replay without view fields.
        cold = CombatService(ROOT, data)
        table = TabletopService(cold, data)
        after = table.state(mid, fog=True)
        position = next(row["position"] for row in after["presentation"]["actors"] if row["entity_id"] == mine)
        assert {key: position[key] for key in ("x", "y")} == path[-1]
        assert cold._load_session(mid).mechanical.replay()["status"] == "PASS"
        steps.append({"before": before, "events": committed["events"], "after": after, "inside": inside})

    original = {path.relative_to(data): path.read_bytes() for path in data.rglob("*") if path.is_file()}
    recording = tmp_path / "willow-views.json"
    recording.write_text(json.dumps({"matchId": mid, "mine": mine, "ally": ally, "steps": steps}), encoding="utf-8")
    report = run_node("tests/viewer_identity_wiring.test.mjs", recording=recording)
    cases = [case for case in report.iter("testcase") if case.get("name") == REAL_CASE]
    assert len(cases) == 1 and not list(cases[0]), "the real commit/cold-reload case must execute, never skip"
    assert {path.relative_to(data): path.read_bytes() for path in data.rglob("*") if path.is_file()} == original
    assert all(b"tt-viewer" not in value for value in original.values()), "view binding is never saved in the fight"
