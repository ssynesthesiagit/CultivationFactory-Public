"""Slice A: real saved table boundaries, synthetic characters, no live models."""
import gc
import json
import shutil
import threading
import time
import weakref

import pytest
from fastapi.testclient import TestClient

from agent_seats import SeatRunner
from app.api import create_app
from app.core import Settings
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


def test_each_warm_commit_matches_a_verified_cold_load(tmp_path, monkeypatch):
    """SPEEDHOST1: compare every committed state, including an answer between automatic runner steps."""
    from combat.gate3_reducer import canonical_state_sha256
    from combat.gate4_controller import LocalDeterministicController
    from tests.test_hunt5_player_choices import fixture as asking, FOE
    from tools.speedbench_scenarios import build, mantis_fixture, operation

    def check(table, mid, fight):
        warm = table.fights._fights.get(mid)
        assert warm is not None, f"{fight}: commit did not preserve a warm session"
        cold = table.combat._load_session(mid).engine.state
        hot = warm.session.engine.state
        cold_hash = canonical_state_sha256(cold)
        hot_hash = canonical_state_sha256(hot)
        if not cold_hash == warm.state_hash == hot_hash:
            cold_fields = cold.model_dump(mode="json")
            hot_fields = hot.model_dump(mode="json")
            first = next((key for key in cold_fields if cold_fields[key] != hot_fields.get(key)), "state_hash")
            pytest.fail(f"STOPPED: warm≠cold at {fight}/{cold.state_version}, first differing state field: {first}")
        return cold

    data = tmp_path / "speedbench"
    bench, _ = build(data, records=0)
    mantis = mantis_fixture(data)
    _, _, manual, cid, _ = asking(data, "TAL_FENCING_FOOTWORK")
    table = TabletopService(CombatService(ROOT, data), data)
    committed = table.fights.committed
    session = table.fights.session
    checked = []
    reuses = 0

    def check_commit(mid):
        committed(mid)
        checked.append(check(table, mid, name).state_version)

    def track_session(mid):
        nonlocal reuses
        before = table.fights.acquisitions
        loaded = session(mid)
        reuses += table.fights.acquisitions == before
        return loaded

    with monkeypatch.context() as m:
        m.setattr(table.fights, "committed", check_commit)
        m.setattr(table.fights, "session", track_session)
        for name, mid in [(n, bench) for n in ("toggle", "melee", "area", "movement")] + [("mantis_native", mantis)]:
            run = operation(data, mid, name, table=table)
            boundary_commits = len(checked)
            run()
            assert len(checked) == boundary_commits + 1, name

        # Force the human continuation even when the benchmark's ordinary attacks need no answer.
        name = "Footwork manual USE"
        menu = table.state(manual)["menu"]
        args = (manual, cid, menu["decision_id"], menu["state_version"], 0)
        before = len(checked)
        table.act(*args, prepare_only=True)
        pending = table.act(*args)
        assert pending["status"] == "REACTION_REQUIRED"
        assert len(checked) == before
        prompt = pending["reaction"]
        option = next(o["id"] for o in prompt["choice"]["options"] if "Stay put" in o["label"])
        answer = {**prompt["context"], "selection": "USE", "option_ids": [option]}
        assert table.act(*args, reactions=[answer])["status"] == "COMMITTED"
        assert len(checked) == before + 1
    assert reuses > 0

    combat, table, mid, _, _ = asking(tmp_path / "ask-me", "TAL_FENCING_FOOTWORK")
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    runner = SeatRunner(table, background=False)
    before = canonical_state_sha256(combat._load_session(mid).engine.state)
    assert runner.drive(mid, max_steps=1) == 1
    pending = table.state(mid)["pending_action"]
    assert pending["reaction"]["reaction"] == "Footwork"
    assert canonical_state_sha256(combat._load_session(mid).engine.state) == before
    answer = {**pending["reaction"]["context"], "selection": "DECLINE", "option_ids": []}
    assert table.auto_step(mid, **pending["request"], reactions=[answer])["status"] == "COMMITTED"
    after = check(table, mid, "Footwork")
    combat.controller = LocalDeterministicController()
    assert runner.drive(mid, max_steps=1) == 1
    assert check(table, mid, "Footwork").state_version > after.state_version


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
        if kwargs.get("_receipt"):                      # only the seat runner's own steps
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
            assert client.get(url + "/state?include_menu=true").json()["menu"]["manual"]
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


def test_new_writer_invalidates_warm_session_and_stale_append_writes_nothing(tmp_path):
    combat, table, mid, ai = boundary(tmp_path)
    owner = table.fights
    loads = owner.acquisitions
    with _match_lock(mid), _table_action_lock(table._match_dir(mid), mid):
        stale = owner.session(mid)
    choice = combat.controller.choose_primary_action(combat.ai_decision_context(stale))
    assert combat.local_step(mid)["status"] == "COMMITTED"
    saved = {name: (combat._match_dir(mid) / name).read_bytes()
             for name in ("Journal.ndjson", "ControllerJournal.ndjson")}
    with pytest.raises(Exception, match="This fight changed or was replaced"):
        stale.execute_controller_choice(choice, controller=combat.controller, policy_library=combat.policies)
    for name, value in saved.items():
        assert (combat._match_dir(mid) / name).read_bytes() == value
    with _match_lock(mid), _table_action_lock(table._match_dir(mid), mid):
        assert owner.session(mid) is not stale
    assert owner.acquisitions == loads + 2
    verified(combat, mid)


def test_outside_commit_after_load_or_proof_reloads_for_current_menu(tmp_path, monkeypatch):
    """SPEEDHOST1: a verified engine must not inherit a later outside writer's journal binding."""
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = fixture(combat, tmp_path, 2, "TABLESPEEDA-OUTSIDE")
    outside = CombatService(ROOT, tmp_path)

    def outside_end_turn(version):
        context = outside.decision(mid)["context"]
        assert context["state_version"] == version
        candidate = next(c for c in context["legal_candidates"] if c["kind"] == "END_TURN")
        intent = {key: candidate.get(key) for key in
                  ("candidate_id", "decision_id", "state_version", "actor_id", "target_ids", "destination", "option_ids")}
        result = outside.submit_intent(mid, intent, [], None)
        saved_version = result["match"]["state"]["state_version"]
        assert saved_version > version
        return saved_version

    def end_turn_from_current_menu(expected_version):
        menu = table.state(mid)["menu"]
        assert menu["state_version"] == expected_version
        result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, _receipt=True)
        assert result["status"] == "COMMITTED"
        return result["state_version"]

    load = combat._load_session
    after_load = []

    def load_then_commit(match_id):
        session = load(match_id)
        after_load.append(outside_end_turn(session.engine.state.state_version))
        return session

    with monkeypatch.context() as m:
        m.setattr(combat, "_load_session", load_then_commit)
        with _match_lock(mid), _table_action_lock(table._match_dir(mid), mid):
            table.fights.session(mid)
    assert len(after_load) == 1

    prove = combat.presentation_session
    after_proof = []

    def prove_then_commit(session):
        proven = prove(session)
        assert proven is session
        after_proof.append(outside_end_turn(session.engine.state.state_version))
        return proven

    with monkeypatch.context() as m:
        m.setattr(combat, "presentation_session", prove_then_commit)
        end_turn_from_current_menu(after_load[0])
    assert len(after_proof) == 1
    assert end_turn_from_current_menu(after_proof[0]) > after_proof[0]


def test_idle_sweeper_does_not_keep_fight_host_alive(tmp_path):
    """SPEEDHOST1: warming a disposable table must not tie its host's lifetime to the daemon thread."""
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = fixture(combat, tmp_path, 2, "TABLESPEEDA-SWEEPER")
    with _match_lock(mid), _table_action_lock(table._match_dir(mid), mid):
        table.fights.session(mid)
    sweeper = table.fights._sweeper
    assert sweeper is not None and sweeper.is_alive()
    host = weakref.ref(table.fights)
    del table
    gc.collect()
    assert host() is None


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
