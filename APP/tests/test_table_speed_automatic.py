"""Slice A: real saved table boundaries, synthetic characters, no live models."""
import json
import shutil
import threading
import time

import pytest
from fastapi.testclient import TestClient

from agent_seats import SeatRunner
from app.api import create_app
from app.core import Settings
from combat.execution_session import ExecutionSession
from combat.gate3_storage import Gate3InjectedCrash
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService, _match_lock, _table_action_lock
from tools.table_speed_probe import ROOT, fixture


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("CF_EMBED_MENU", "0")


def boundary(path, actors=2):
    combat = CombatService(ROOT, path)
    table = TabletopService(combat, path)
    mid = fixture(combat, path, actors, "TABLESPEEDA-" + str(actors))
    menu = table.state(mid)["menu"]
    out = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)
    ai = out["state"]["menu"]["actor_id"]
    combat.set_controller_mode(mid, actor_id=ai, controller_mode="LOCAL_AUTO")
    return combat, table, mid, ai


def finish(combat, mid, ai):
    count = 0
    for _ in range(32):
        result = combat.local_step(mid)
        assert result["status"] == "COMMITTED"
        count += 1
        if result["match"]["state"]["current_actor_id"] != ai:
            return count
    pytest.fail("fixture turn did not finish")


def verified(combat, mid):
    session = combat._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
    return session.engine.state.model_dump(mode="json")


@pytest.mark.parametrize("actors", [2, 6])
def test_owned_turn_equals_ordinary_load_step_bytes_and_uses_one_acquisition(tmp_path, actors, monkeypatch):
    data = tmp_path / "owned"
    combat, table, mid, ai = boundary(data, actors)
    shutil.copytree(data, tmp_path / "ordinary")
    ordinary = CombatService(ROOT, tmp_path / "ordinary")
    expected_steps = finish(ordinary, mid, ai)
    runner = SeatRunner(table, background=False)
    loads, projections = [], []
    load, state = combat._load_session, table.state
    monkeypatch.setattr(combat, "_load_session", lambda mid: (loads.append(mid), load(mid))[1])
    monkeypatch.setattr(table, "state", lambda *a, **kw: (projections.append(1), state(*a, **kw))[1])
    assert runner.drive(mid) == expected_steps
    assert runner.status(mid)["acquisitions"] == 1
    assert len(loads) == 1 and not projections  # no interior display/deferred menu reads
    assert verified(combat, mid) == verified(ordinary, mid)
    for name in ("Journal.ndjson", "ControllerJournal.ndjson"):
        assert (combat._match_dir(mid) / name).read_bytes() == (ordinary._match_dir(mid) / name).read_bytes()
    assert table.state(mid)["menu"]["manual"]


def wait_finished(runner, mid):
    deadline = time.monotonic() + 60
    while runner.status(mid)["running"]:
        assert time.monotonic() < deadline
        time.sleep(.01)
    return runner.status(mid)


def test_one_authorized_start_two_tabs_observe_without_driving_and_activity(tmp_path, monkeypatch):
    combat, table, mid, ai = boundary(tmp_path)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    runner = app.state.agent_seats
    table = runner.table
    entered, release = threading.Event(), threading.Event()
    original = table.auto_step
    def held(*args, **kwargs):
        if kwargs.get("_execution") is not None:
            entered.set()
            assert release.wait(30)
        return original(*args, **kwargs)
    monkeypatch.setattr(table, "auto_step", held)
    try:
        with TestClient(app) as client:
            url = f"/api/tabletop/matches/{mid}"
            assert client.post(url + "/automatic-run", json={}).status_code == 403
            headers = {"X-Foundry-Token": client.get("/api/session").json()["token"]}
            assert client.post(url + "/automatic-run", json={}, headers=headers).json()["running"]
            assert entered.wait(30)
            thread = runner._running[mid]
            # A second tab attaches to the same owner, never another decision loop.
            assert client.post(url + "/automatic-run", json={}, headers=headers).json()["running"]
            assert runner._running[mid] is thread
            assert client.post(url + "/auto-step", json={"after": 0}, headers=headers).json()["status"] == "MODEL_DECIDING"
            before = (combat._match_dir(mid) / "Journal.ndjson").read_bytes()
            for _ in range(3):
                assert client.get(url + "/seat-status").json()["running"]
            assert (combat._match_dir(mid) / "Journal.ndjson").read_bytes() == before
            [activity] = client.get("/api/tabletop/activity").json()
            assert activity["match_id"] == mid and activity["seconds_since_request"] < 5
            release.set()
            status = wait_finished(runner, mid)
            assert status["status"] == "IDLE" and status["steps"] > 0
            assert client.get(url + "/state").json()["menu"]["manual"]
    finally:
        release.set()
        wait_finished(runner, mid)
    verified(combat, mid)


@pytest.mark.parametrize("change", ["pause", "seat", "stop"])
def test_queued_control_commands_stop_between_commits(tmp_path, monkeypatch, change):
    combat, table, mid, ai = boundary(tmp_path)
    runner = SeatRunner(table)
    entered, release = threading.Event(), threading.Event()
    original = table.auto_step
    def held(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(30)
        return result
    monkeypatch.setattr(table, "auto_step", held)
    runner.start(mid)
    try:
        assert entered.wait(30)
        before = (combat._match_dir(mid) / "Journal.ndjson").read_bytes()
        if change == "seat":
            runner.set_seat(mid, ai, "MANUAL")
        elif change == "stop":
            table.control(mid, "pause")  # existing combat Stop authority
        else:
            runner.set_paused(mid, True)
        release.set()
        wait_finished(runner, mid)
        assert (combat._match_dir(mid) / "Journal.ndjson").read_bytes() == before
        assert runner.status(mid)["steps"] == 1
    finally:
        release.set()
        wait_finished(runner, mid)
    verified(combat, mid)


def test_human_ask_me_on_ai_turn_stops_and_pending_answer_survives_reacquisition(tmp_path):
    from tests.test_hunt5_player_choices import fixture as asking, FOE
    combat, table, mid, _, _ = asking(tmp_path, "TAL_FENCING_FOOTWORK")
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    runner = SeatRunner(table, background=False)
    before = verified(combat, mid)
    assert runner.drive(mid) == 1
    state = table.state(mid)
    pending = state["pending_action"]
    assert pending["method"] == "auto_step"
    assert pending["reaction"]["reaction"] == "Footwork"
    assert verified(combat, mid) == before  # unresolved decision is NOT committed
    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    fresh.combat.controller = combat.controller
    prompt = fresh.state(mid)["pending_action"]["reaction"]
    answer = {**prompt["context"], "selection": "DECLINE", "option_ids": []}
    out = fresh.auto_step(mid, **pending["request"], reactions=[answer])
    assert out["status"] == "COMMITTED"
    assert fresh.state(mid)["pending_action"] is None
    verified(fresh.combat, mid)


def test_summon_slots_run_with_owner_control_then_stop_at_human(tmp_path):
    from tests.test_h47_summon_table import table_fixture, candidate, OWNER
    combat, table, mid, _, commit = table_fixture(tmp_path)
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    runner = SeatRunner(table, background=False)
    assert runner.drive(mid) > 1
    state = table.state(mid)
    assert state["menu"]["manual"]
    assert state["menu"]["actor_id"] != OWNER
    assert any(a.get("owner_id") == OWNER for a in state["presentation"]["actors"])
    verified(combat, mid)


def test_new_writer_invalidates_owned_session_and_stale_append_writes_nothing(tmp_path):
    combat, table, mid, ai = boundary(tmp_path)
    owner = ExecutionSession(table, mid)
    with _match_lock(mid), _table_action_lock(table._match_dir(mid), mid):
        stale = owner.current()
    choice = combat.controller.choose_primary_action(combat.ai_decision_context(stale))
    assert combat.local_step(mid)["status"] == "COMMITTED"
    saved = {name: (combat._match_dir(mid) / name).read_bytes()
             for name in ("Journal.ndjson", "ControllerJournal.ndjson")}
    with pytest.raises(Exception, match="Another command changed"):
        stale.execute_controller_choice(choice, controller=combat.controller, policy_library=combat.policies)
    for name, value in saved.items():
        assert (combat._match_dir(mid) / name).read_bytes() == value
    with _match_lock(mid), _table_action_lock(table._match_dir(mid), mid):
        assert owner.current() is not stale
    assert owner.acquisitions == 2
    owner.release()
    verified(combat, mid)


def test_writer_race_during_decision_discards_session_and_reacquires(tmp_path, monkeypatch):
    combat, table, mid, ai = boundary(tmp_path / "owned")
    shutil.copytree(tmp_path / "owned", tmp_path / "ordinary")
    ordinary = CombatService(ROOT, tmp_path / "ordinary")
    total = finish(ordinary, mid, ai)
    original = combat.local_step
    raced = []
    def interleaved(mid, *args, session=None, **kwargs):
        if session is not None and not raced:
            raced.append(True)
            assert original(mid)["status"] == "COMMITTED"
        return original(mid, *args, session=session, **kwargs)
    monkeypatch.setattr(combat, "local_step", interleaved)
    runner = SeatRunner(table, background=False)
    assert runner.drive(mid) == total - 1
    assert runner.status(mid)["acquisitions"] == 2
    assert verified(combat, mid) == verified(ordinary, mid)
    for name in ("Journal.ndjson", "ControllerJournal.ndjson"):
        assert (combat._match_dir(mid) / name).read_bytes() == (ordinary._match_dir(mid) / name).read_bytes()


def test_crash_after_prepare_reacquires_through_verified_recovery(tmp_path):
    combat, table, mid, ai = boundary(tmp_path)
    session = combat._load_session(mid)
    choice = combat.controller.choose_primary_action(combat.ai_decision_context(session))
    def crash(stage, detail):
        if stage == "after_prepare_flush":
            raise Gate3InjectedCrash(stage)
    with pytest.raises(Gate3InjectedCrash):
        session.execute_controller_choice(choice, controller=combat.controller,
            policy_library=combat.policies, failure_injector=crash)
    fresh = CombatService(ROOT, tmp_path)
    table = TabletopService(fresh, tmp_path)
    runner = SeatRunner(table, background=False)
    try:
        runner.drive(mid)
    except Exception as error:
        pytest.fail(repr(getattr(error, "diagnostic", error)))
    assert runner.status(mid)["acquisitions"] == 1
    assert table.state(mid)["menu"]["manual"]
    verified(fresh, mid)


def test_error_is_observable_does_not_retry_until_explicit_start(tmp_path, monkeypatch):
    combat, table, mid, _ = boundary(tmp_path)
    runner = SeatRunner(table)
    original = table.auto_step
    def broken(*args, **kwargs):
        raise ValueError("synthetic failure")
    monkeypatch.setattr(table, "auto_step", broken)
    runner.start(mid)
    assert wait_finished(runner, mid)["status"] == "ERROR"
    assert runner.status(mid)["running"] is False
    table.state(mid)
    assert not runner.status(mid)["running"]
    monkeypatch.setattr(table, "auto_step", original)
    runner.start(mid)
    assert wait_finished(runner, mid)["status"] == "IDLE"
    verified(combat, mid)


def test_quantum_resumes_server_side_until_terminal_without_browser_wakeup(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    session = combat.persistence.create_match(match_seed="SPEEDA-TERMINAL", maximum_rounds=1)
    mid = session.match_id
    for actor in session.engine.state.actors.values():
        if actor.primary_combatant:
            combat.set_controller_mode(mid, actor_id=actor.entity_id, controller_mode="LOCAL_AUTO")
    runner = SeatRunner(table, background=False)
    assert runner.drive(mid, max_steps=1, _continue=True) > 1
    assert verified(combat, mid)["terminal_result"] is not None
    before = (combat._match_dir(mid) / "Journal.ndjson").read_bytes()
    assert runner.drive(mid) == 0
    assert (combat._match_dir(mid) / "Journal.ndjson").read_bytes() == before


def test_observations_do_not_touch_existing_journal(tmp_path):
    combat, table, mid, _ = boundary(tmp_path)
    path = combat._match_dir(mid) / "Journal.ndjson"
    stamp = (path.stat().st_mtime_ns, path.read_bytes())
    table.state(mid)
    table.events(mid, 0)
    assert (path.stat().st_mtime_ns, path.read_bytes()) == stamp


def test_browser_turn_observer_contract():
    import subprocess
    result = subprocess.run(["node", str(ROOT / "tests/table_speed_automatic.test.mjs")],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
