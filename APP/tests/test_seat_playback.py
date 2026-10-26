"""Play/Pause through persisted table writes, including late provider replies."""
import threading
import json
import os
import subprocess

import pytest

from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_agent_seats import FakeProvider, raw_state, runner_for
from tests.test_hunt5_player_choices import fixture, FOE, PLAYER


@pytest.mark.parametrize("replacement", ["MANUAL", "AI"])
def test_removing_final_model_seat_releases_pause_for_browser_ai_after_reload(tmp_path, replacement):
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, fake = runner_for(tmp_path, table)
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    runner.set_seat(mid, FOE, "AI")
    runner.set_paused(mid, True)
    paused = runner.playback(mid)
    before = raw_state(runner, mid)
    with pytest.raises(TabletopError, match="Paused"):
        table.auto_step(mid, before["last_sequence"])
    runner.set_seat(mid, PLAYER, replacement)
    assert runner.playback(mid) == {"paused": 0, "revision": paused["revision"] + 1}
    assert runner.drive(mid, max_steps=1) == 0  # browser owns advancement now
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    reopened.combat.controller = combat.controller
    loaded, _ = runner_for(tmp_path, reopened, fake)
    assert not loaded.status(mid)["paused"]
    state = reopened.state(mid)
    assert state["menu"]["actor_id"] == FOE
    result = reopened.auto_step(mid, state["last_sequence"])
    assert result["status"] == "COMMITTED"
    assert result["state"]["last_sequence"] > before["last_sequence"]
    assert fake.prompts == []
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


def test_removing_one_of_two_model_seats_preserves_pause(tmp_path):
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, _ = runner_for(tmp_path, table)
    for actor in (PLAYER, FOE):
        runner.set_seat(mid, actor, "MODEL", "fake")
    runner.set_paused(mid, True)
    paused = runner.playback(mid)
    runner.set_seat(mid, PLAYER, "MANUAL")
    assert runner.playback(mid) == paused
    assert runner.drive(mid, max_steps=1) == 0


@pytest.mark.parametrize("builtin", [False, True])
def test_pause_survives_reload_and_play_resumes_commits(tmp_path, builtin):
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, fake = runner_for(tmp_path, table)
    runner.set_seat(mid, PLAYER if builtin else FOE, "MODEL", "fake")
    if builtin:
        runner.set_seat(mid, FOE, "AI")
    assert runner.set_paused(mid, True)["paused"]
    before = raw_state(runner, mid)
    assert runner.drive(mid, max_steps=1) == 0
    assert raw_state(runner, mid) == before
    assert fake.prompts == []
    if builtin:
        with pytest.raises(TabletopError, match="Paused"):
            table.auto_step(mid, before["last_sequence"])
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    reopened.combat.controller = combat.controller
    loaded, _ = runner_for(tmp_path, reopened, fake)
    assert loaded.status(mid)["paused"]
    assert loaded.seats(mid) == runner.seats(mid)
    assert loaded.drive(mid, max_steps=1) == 0
    assert not loaded.set_paused(mid, False)["paused"]
    assert loaded.drive(mid, max_steps=1) == 1
    assert raw_state(loaded, mid)["last_sequence"] > before["last_sequence"]
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
    assert all(type(v) is int for v in loaded.playback(mid).values())


@pytest.mark.parametrize("resume_before_reply", [False, True])
def test_pause_fences_a_blocked_model_turn_reply(tmp_path, resume_before_reply):
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    entered, release = threading.Event(), threading.Event()
    fake = FakeProvider()
    def blocked(config, prompt, png):
        entered.set()
        assert release.wait(15)
        return fake(config, prompt, png)
    runner, _ = runner_for(tmp_path, table, blocked, timeout=15)
    runner.set_seat(mid, FOE, "MODEL", "fake")
    before = raw_state(runner, mid)
    results = []
    worker = threading.Thread(target=lambda: results.append(runner.drive(mid, max_steps=1)))
    worker.start()
    try:
        assert entered.wait(15)
        runner.set_paused(mid, True)
        if resume_before_reply:
            runner.set_paused(mid, False)
    finally:
        release.set()
        worker.join(20)
    assert not worker.is_alive()
    assert results == [0]
    assert raw_state(runner, mid) == before
    if not resume_before_reply:
        runner.set_paused(mid, False)
    assert runner.drive(mid, max_steps=1) == 1


def test_writer_guard_fences_builtin_turn_after_pause(tmp_path):
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, _ = runner_for(tmp_path, table)
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    runner.set_seat(mid, FOE, "AI")
    before = raw_state(runner, mid)
    runner._local.active = True
    runner._local.expected_seats = runner.seats(mid)
    runner._local.expected_playback = runner.playback(mid)
    try:
        runner.set_paused(mid, True)
        with pytest.raises(TabletopError, match="Paused"):
            table.auto_step(mid, before["last_sequence"])
    finally:
        runner._local.active = False
        runner._local.expected_seats = None
        runner._local.expected_playback = None
    assert raw_state(runner, mid) == before


def test_paused_human_action_still_resolves_model_reaction_and_commits_after_reload(tmp_path):
    combat, table, mid, cid, _ = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    runner, fake = runner_for(tmp_path, table)
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    runner.set_paused(mid, True)
    before = raw_state(runner, mid)
    menu = before["menu"]
    result = table.act(mid, cid, menu["decision_id"], menu["state_version"], before["last_sequence"])
    assert result["status"] == "MODEL_DECIDING"
    assert result["state"]["menu"]["manual"]
    assert result["state"]["model_deciding"]
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    reopened.combat.controller = combat.controller
    loaded, _ = runner_for(tmp_path, reopened, fake)
    assert loaded.status(mid)["paused"]
    assert loaded.drive(mid, max_steps=3) == 1
    after = raw_state(loaded, mid)
    assert after["pending_action"] is None
    assert after["last_sequence"] > before["last_sequence"]
    assert len(fake.prompts) == 1
    assert loaded.decisions(mid)[-1]["kind"] == "REACTION"
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


def test_human_menu_model_reaction_followup_uses_real_node_lifecycle(tmp_path):
    from tests.r1i_service_support import OWNER, FOE as MODEL, fixture as team_fixture
    from combat.canonical import canonical_sha256
    def ask_opportunity(bundles):
        # The shared team fixture defaults its foe to Auto reactions. This model
        # must own the opportunity decision so the action pauses before Footwork.
        bundle = next(b for b in bundles if b["actor_id"] == MODEL)
        bundle["reaction_plan"]["mode"] = "ask"
        for row in bundle["typed_reactions"]:
            row["ask"] = True
        bundle.pop("bundle_sha256")
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat, table, mid, *_ = team_fixture(tmp_path, ["TAL_FENCING_FOOTWORK"], bundle_transform=ask_opportunity)
    entered, release = threading.Event(), threading.Event()
    fake = FakeProvider()
    def blocked(config, prompt, png):
        entered.set()
        assert release.wait(15)
        return fake(config, prompt, png)
    runner, _ = runner_for(tmp_path, table, blocked, timeout=15)
    runner.set_seat(mid, MODEL, "MODEL", "fake")
    state = raw_state(runner, mid)
    menu = state["menu"]
    assert menu["actor_id"] == OWNER
    move = next(m for m in menu["moves"] if m["destination"] == {"x": 2, "y": 6})
    result = table.act(mid, move["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "MODEL_DECIDING"
    results = []
    worker = threading.Thread(target=lambda: results.append(runner.drive(mid, max_steps=1)))
    worker.start()
    try:
        assert entered.wait(15)
        waiting = table.state(mid)
        assert waiting["menu"]["manual"] and waiting["model_deciding"]
        assert waiting["last_sequence"] == state["last_sequence"]
    finally:
        release.set()
        worker.join(20)
    assert not worker.is_alive() and results == [1]
    human = table.state(mid)
    assert human["pending_action"]["reaction"]["context"]["reactor_id"] == OWNER
    assert human["last_sequence"] == waiting["last_sequence"]
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    loaded, _ = runner_for(tmp_path, reopened, fake)
    assert reopened.state(mid)["pending_action"] == human["pending_action"]
    pending = human["pending_action"]
    answer = {**pending["reaction"]["context"], "selection": "DECLINE"}
    result = reopened.act(mid, **pending["request"], reactions=[*pending.get("reactions", []), answer])
    assert result["status"] == "COMMITTED"
    payload = {"waiting": waiting, "human": human, "committed": result["state"], "seats": loaded.seats(mid)}
    path = tmp_path / "seat-lifecycle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    env = {**os.environ, "SEAT_LIFECYCLE_FIXTURE": str(path)}
    node = subprocess.run(["node", "--test", "--test-isolation=none", "--test-reporter=tap", "--test-name-pattern=service-backed",
                           "tests/seats_ui.test.mjs"], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
    assert node.returncode == 0, node.stdout + node.stderr
    assert "# pass 1" in node.stdout
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
