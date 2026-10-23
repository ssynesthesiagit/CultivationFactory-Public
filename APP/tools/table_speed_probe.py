"""Bounded Slice A measurement harness: ordinary HTTP, both headless baselines and owned run.

Invoked by tests/test_table_speed_probe.py through heavyq. Uses synthetic public
characters, a real loopback uvicorn server on an OS-assigned port, no browser or
model. Profiles are separate from unprofiled timings (sys.setprofile overhead).
All fixture files are beneath the caller's temporary directory.
"""
from __future__ import annotations

from collections import defaultdict
from contextvars import ContextVar
import hashlib
import io
import logging
import json
from pathlib import Path
import shutil
import socket
import threading
import time
import zipfile

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
TRACE = ContextVar("table_speed_trace", default=None)
SELECT = {
    "gate5_service.py": {"_load_session", "presentation", "decision", "local_step", "_match_view",
                         "presentation_session", "_legal_candidates"},
    "gate3_storage.py": {"_load_lock_genesis", "_validate_saved_journal", "_plan_load",
                          "_replay_from", "_engine_from_loaded", "read_journal",
                          "_write_manifest", "atomic_write_bytes"},
    "gate4_persistence.py": {"_engine_from_loaded"},
    "tabletop_service.py": {"state", "events", "act", "auto_step"},
    "gate3_reducer.py": {"apply_events"},
    "routing.py": {"serialize_response"},
    "responses.py": {"render"},
}


def profile(frame, event, arg):
    trace = TRACE.get()
    if trace is None or event not in ("call", "return"):
        return
    file = frame.f_code.co_filename.rsplit("/", 1)[-1]
    name = frame.f_code.co_name
    if name not in SELECT.get(file, ()):
        return
    key = file + ":" + name
    ident = (threading.get_ident(), key)
    if event == "call":
        depth = trace["depth"].get(ident, 0)
        trace["depth"][ident] = depth + 1
        if not depth:
            trace["starts"][ident] = time.perf_counter()
    else:
        depth = trace["depth"].get(ident, 0)
        if depth <= 0:  # hook can be enabled while an older frame is returning
            return
        trace["depth"][ident] = depth - 1
        if depth == 1:
            started = trace["starts"].pop(ident, None)
            if started is not None:
                trace["calls"][key] += 1
                trace["ms"][key] += (time.perf_counter() - started) * 1000


class Meter:
    def __init__(self, app):
        self.app, self.rows = app, []

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        measured = b"x-table-speed-profile" in dict(scope.get("headers", []))
        trace = {"depth": {}, "starts": {}, "calls": defaultdict(int), "ms": defaultdict(float)}
        token = TRACE.set(trace if measured else None)
        if measured:
            threading.setprofile_all_threads(profile)
        start = time.perf_counter()
        size = 0

        async def metered_send(message):
            nonlocal size
            if message["type"] == "http.response.body":
                size += len(message.get("body", b""))
            await send(message)
        try:
            await self.app(scope, receive, metered_send)
        finally:
            self.rows.append({"path": scope["path"], "server_ms": (time.perf_counter() - start) * 1000,
                              "bytes": size, "profiled": measured,
                              "calls": dict(trace["calls"]), "spans_ms": dict(trace["ms"])})
            TRACE.reset(token)
            if measured:
                threading.setprofile_all_threads(None)


def sheet():
    return {
        "identity": {"display_name": "Probe cultivator", "cultivation_level": 17,
                     "proficiency_bonus": 6, "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "modifier": m, "score": 10 + 2*m}
                          for a, m in (("STR", 4), ("DEX", 2), ("CON", 4), ("INT", 0), ("WIS", 0), ("CHA", 0))],
            "armor_class": {"base_value": 14}, "hit_points": {"maximum": 120},
            "initiative": {"bonus": 2}, "speed": {"walking_ft": 30},
            "primary_resource": {"name": "Stamina", "maximum": 40},
            "technique_attack_bonus": 10, "technique_save_dc": 18},
        "spheres_and_talents": {
            "sphere_record_ids": ["tianxia.sphere.brute", "tianxia.sphere.sabers"],
            "learned_talent_record_ids": ["TAL_BRUTE_MOUNTAIN_MOVING_PALM", "tianxia.talent.sabers.forward_cut"]},
        "equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}]}}],
    }


def fixture(combat, data, actors, seed):
    from combat.gate5_service import FACTORY_ACTOR_PREFIX
    ids = [f"probe-{i}" for i in range(actors)]
    for pid in ids:
        path = data / "portable_characters" / pid / "current.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet()))
    half = actors // 2
    combat.tabletop_maps.save({"display_name": "Probe yard", "width_squares": 12, "height_squares": 8,
                              "walls": [], "starts": {
                                  "team1": [[3, 2 + i] for i in range(half)],
                                  "team2": [[5, 2 + i] for i in range(half)]}})
    return combat.create_factory_match(
        project_ids=ids[:half], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + p for p in ids[half:]],
        control_modes={FACTORY_ACTOR_PREFIX + p: "MANUAL" for p in ids},
        arena_id="battlefield:map.probe-yard", match_seed=seed, maximum_rounds=200)["match_id"]


def disk_stamp(directory):
    return {str(p.relative_to(directory)): [p.stat().st_mtime_ns, p.stat().st_size,
                                           hashlib.sha256(p.read_bytes()).hexdigest()]
            for p in directory.rglob("*") if p.is_file() and not p.name.startswith(".")}


def measure(tmp_path):
    from app.api import create_app
    from app.core import Settings
    from combat.gate5_service import CombatService
    data = tmp_path / "data"
    app = create_app(Settings.from_env(ROOT, data))
    seats = app.state.agent_seats
    # No model seats exist: the production driver is inert, as at an ordinary table.
    combat, table = app.state.combat, seats.table
    meter = Meter(app)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    assert port != 8765
    server = uvicorn.Server(uvicorn.Config(meter, host="127.0.0.1", port=port,
                                          log_level="error", lifespan="off", timeout_keep_alive=600))
    errors = io.StringIO()
    error_handler = logging.StreamHandler(errors)
    logging.getLogger("uvicorn.error").addHandler(error_handler)
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    report = {"probe_version": 5, "port": port, "clock": "perf_counter wall milliseconds", "scenarios": []}
    try:
        deadline = time.monotonic() + 20
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline, "fixture server did not start"
            time.sleep(.02)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=180) as client:
            token = client.get("/api/session").json()["token"]

            def request(mid, suffix, body=None, profiled=False):
                previous_count = len(meter.rows)
                start = time.perf_counter()
                headers = {"X-Foundry-Token": token}
                if profiled:
                    headers["X-Table-Speed-Profile"] = "1"
                try:
                    response = client.request("GET" if body is None else "POST",
                                              f"/api/tabletop/matches/{mid}/{suffix}",
                                              headers=headers, json=body)
                except httpx.HTTPError as exc:
                    raise AssertionError(f"HTTP probe {suffix}, profile={profiled}, "
                                         f"server_alive={thread.is_alive()}: {exc}; "
                                         f"server_errors={errors.getvalue()[-1800:]!r}") from exc
                fetch_ms = (time.perf_counter() - start) * 1000
                response.raise_for_status()
                start = time.perf_counter()
                value = response.json()
                decode_ms = (time.perf_counter() - start) * 1000
                # The ASGI finalizer can finish just after the socket body arrives.
                deadline = time.monotonic() + 2
                expected_path = f"/api/tabletop/matches/{mid}/" + suffix.split("?")[0]
                while (len(meter.rows) <= previous_count or meter.rows[-1]["path"] != expected_path) and time.monotonic() < deadline:
                    time.sleep(.001)
                row = {**meter.rows[-1], "fetch_ms": fetch_ms, "decode_ms": decode_ms}
                return value, row

            def settled():
                started = time.perf_counter()
                deadline = time.monotonic() + 180
                while table._warm_running:
                    assert time.monotonic() < deadline, "background menu preparation exceeded 180 seconds"
                    time.sleep(.01)
                return (time.perf_counter() - started) * 1000

            # Every case is a fresh fight; headless clones the exact AI-turn boundary.
            for actors, history in ((2, 0), (6, 0), (2, 100)):
                for profiled in (False, True):
                    mid = fixture(combat, data, actors, f"TABLESPEEDA-{actors}-{history}")
                    if history:
                        from combat.gate2_runtime_models import ActionIntent
                        session = combat._load_session(mid)
                        for index in range(history):
                            end = next(c for c in session.engine.legal_candidates() if c.kind == "END_TURN")
                            session.submit_intent(ActionIntent(
                                intent_id=f"speed-history-{index}", decision_id=end.decision_id,
                                candidate_id=end.candidate_id, state_version=end.state_version,
                                actor_id=end.actor_id, target_ids=end.target_ids, option_ids=end.option_ids,
                                destination=end.destination, reaction_decisions=()),
                                primary_decision_record=None, reaction_provider=None)
                    initial = table.state(mid)
                    human = initial["menu"]["actor_id"]
                    for actor in initial["presentation"]["actors"]:
                        if actor["entity_id"] != human:
                            combat.set_controller_mode(mid, actor_id=actor["entity_id"], controller_mode="LOCAL_AUTO")
                    state, initial_read = request(mid, "state?fog=true&compact=true", profiled=profiled)
                    case = {"actors": actors, "history_commits": history, "profiled": profiled, "initial_read": initial_read,
                            "requests": [], "idle": [], "ai_steps": [], "feeds": [], "warm_waits_ms": []}
                    report["scenarios"].append(case)
                    # A real player movement, issued from the compact menu's native quote.
                    menu = table.state(mid)["menu"]
                    move = next(m for m in menu["moves"] if m.get("path") and len(m["path"]) >= 2)
                    payload = {"candidate_id": move["candidate_id"], "decision_id": menu["decision_id"],
                               "state_version": menu["state_version"], "after": state["last_sequence"], "reactions": []}
                    result, row = request(mid, "act", payload, profiled)
                    assert result["status"] == "COMMITTED", result
                    case["requests"].append({"phase": "player_move", **row})
                    case["feeds"].append({"phase": "player_move", **result["events"]})
                    case["warm_waits_ms"].append({"phase": "player_move", "ms": settled()})
                    state, row = request(mid, "state?fog=true&compact=true", profiled=profiled)
                    case["requests"].append({"phase": "deferred_menu_state", **row})
                    # An unchanged idle cycle: the actual poll is events + seats, then full state.
                    before = disk_stamp(combat._match_dir(mid))
                    for _ in range(3):
                        for suffix in (f"events?after={state['last_sequence']}", "seat-status", "state?fog=true&compact=true"):
                            _, row = request(mid, suffix, profiled=profiled)
                            case["idle"].append(row)
                    after = disk_stamp(combat._match_dir(mid))
                    case["idle_changed_files"] = sorted(k for k in before.keys() | after.keys()
                                                       if before.get(k) != after.get(k))
                    case["idle_changed_content"] = sorted(k for k in before.keys() | after.keys()
                        if (before.get(k) or [None])[1:] != (after.get(k) or [None])[1:])
                    case["idle_changed_stamps"] = {k: {"before": before.get(k), "after": after.get(k)}
                                                   for k in case["idle_changed_files"]}
                    menu = table.state(mid)["menu"]
                    result, _ = request(mid, "act", {"candidate_id": menu["end_turn"],
                        "decision_id": menu["decision_id"], "state_version": menu["state_version"],
                        "after": state["last_sequence"], "reactions": []})
                    assert result["status"] == "COMMITTED", result
                    case["warm_waits_ms"].append({"phase": "end_turn", "ms": settled()})
                    state, _ = request(mid, "state?fog=true&compact=true")
                    ai_actor = state["presentation"]["current_actor_id"]
                    # Measure exactly one automatic actor's turn in BOTH rosters.
                    # All following slots are human boundaries, not extra AI work.
                    for actor in state["presentation"]["actors"]:
                        if actor["entity_id"] != ai_actor:
                            combat.set_controller_mode(mid, actor_id=actor["entity_id"], controller_mode="MANUAL")
                    boundary_copy = tmp_path / f"owned-boundary-{actors}-{history}"
                    shutil.copytree(combat._match_dir(mid), boundary_copy)
                    # Same saved boundary for headless CombatService.local_step comparison.
                    clone_data = tmp_path / f"headless-{actors}-{profiled}"
                    shutil.copytree(data, clone_data)
                    headless = CombatService(ROOT, clone_data)
                    retained_data = tmp_path / f"retained-{actors}-{profiled}"
                    shutil.copytree(data, retained_data)
                    retained = CombatService(ROOT, retained_data)
                    acquisition_start = time.perf_counter()
                    retained_session = retained._load_session(mid)
                    retained_acquisition_ms = (time.perf_counter() - acquisition_start) * 1000
                    retained_steps = []
                    for _ in range(24):
                        started = time.perf_counter()
                        retained_result = retained.local_step(mid, session=retained_session)
                        retained_steps.append((time.perf_counter() - started) * 1000)
                        assert retained_result["status"] == "COMMITTED", retained_result
                        if retained_session.engine.state.current_actor_id != ai_actor:
                            break
                    else:
                        raise AssertionError("retained-session AI did not end its turn")
                    case["headless_retained_session"] = {"steps_ms": retained_steps,
                                                         "total_ms": sum(retained_steps),
                                                         "acquisition_ms": retained_acquisition_ms}
                    head_steps, head_start = [], time.perf_counter()
                    for _ in range(24):
                        step_start = time.perf_counter()
                        hresult = headless.local_step(mid)
                        head_steps.append((time.perf_counter() - step_start) * 1000)
                        assert hresult["status"] == "COMMITTED", hresult
                        if hresult["match"]["state"]["current_actor_id"] != ai_actor:
                            break
                    else:
                        raise AssertionError("AI did not end its bounded turn")
                    case["headless"] = {"steps_ms": head_steps, "total_ms": (time.perf_counter()-head_start)*1000}
                    baseline_start = time.perf_counter()
                    for _ in range(24):
                        menu = state["menu"]
                        result, row = request(mid, "auto-step", {"after": state["last_sequence"],
                            "decision_id": menu["decision_id"], "state_version": menu["state_version"],
                            "reactions": []}, profiled)
                        assert result["status"] == "COMMITTED", result
                        case["ai_steps"].append(row)
                        case["feeds"].append({"phase": "ai", **result["events"]})
                        case["warm_waits_ms"].append({"phase": "ai", "ms": settled()})
                        # render(menu_pending) -> refresh(events, full state + seats).
                        _, row = request(mid, f"events?after={result['events']['last_sequence']}", profiled=profiled)
                        case["requests"].append({"phase": "ai_deferred_events", **row})
                        _, row = request(mid, "seat-status", profiled=profiled)
                        case["requests"].append({"phase": "ai_deferred_seats", **row})
                        state, row = request(mid, "state?fog=true&compact=true", profiled=profiled)
                        case["requests"].append({"phase": "ai_deferred_state", **row})
                        if state["presentation"]["current_actor_id"] != ai_actor:
                            break
                    else:
                        raise AssertionError("table AI did not end its bounded turn")
                    case["legacy_command_to_human_menu_ms"] = (time.perf_counter() - baseline_start) * 1000
                    a = combat._load_session(mid).engine.state.model_dump(mode="json")
                    b = headless._load_session(mid).engine.state.model_dump(mode="json")
                    assert a == b
                    assert a == retained._load_session(mid).engine.state.model_dump(mode="json")
                    case["same_final_state"] = True
                    # Compare mechanical bytes, not the table's ephemeral lock/seat metadata.
                    for name in ("Journal.ndjson", "ControllerJournal.ndjson"):
                        left = combat._match_dir(mid) / name
                        right = headless._match_dir(mid) / name
                        assert left.read_bytes() == right.read_bytes(), name
                        assert left.read_bytes() == (retained._match_dir(mid) / name).read_bytes(), name
                    expected_journals = {name: (combat._match_dir(mid) / name).read_bytes()
                                         for name in ("Journal.ndjson", "ControllerJournal.ndjson")}
                    # Reopen the exact pre-turn boundary on the same app/machine.
                    # Only synthetic scratch saves are replaced; all preparation
                    # above has joined before replacing this fixture directory.
                    match_dir = combat._match_dir(mid)
                    shutil.rmtree(match_dir)
                    shutil.copytree(boundary_copy, match_dir)
                    owned_start = time.perf_counter()
                    owned_request_index = len(meter.rows)
                    status, start_row = request(mid, "automatic-run", {})
                    observations = []
                    deadline = time.monotonic() + 180
                    while status["running"]:
                        assert time.monotonic() < deadline, "owned run exceeded 180 seconds"
                        time.sleep(.05)
                        status, row = request(mid, "seat-status")
                        observations.append(row)
                    assert status["status"] == "IDLE", status
                    interior_requests = meter.rows[owned_request_index:]
                    owned_state, human_row = request(mid, "state?fog=true&compact=true")
                    assert owned_state["menu"]["manual"]
                    case["owned"] = {"start_commands": sum(r["path"].endswith("/automatic-run") for r in interior_requests),
                                     "interior_auto_steps": sum(r["path"].endswith("/auto-step") for r in interior_requests),
                                     "interior_deferred_reads": sum(r["path"].endswith(("/state", "/events")) for r in interior_requests),
                                     "command_to_human_menu_ms": (time.perf_counter() - owned_start) * 1000,
                                     "turn_ms": status["turn_ms"],
                                     "acquisition_ms": status["acquisition_ms"],
                                     "acquisitions": status["acquisitions"],
                                     "hot_ms": status["turn_ms"] - status["acquisition_ms"],
                                     "steps": status["steps"], "start_request": start_row,
                                     "status_reads": len(observations), "human_menu_request": human_row}
                    assert status["steps"] == len(head_steps) == len(retained_steps) == len(case["ai_steps"])
                    assert a == combat._load_session(mid).engine.state.model_dump(mode="json")
                    for name, expected in expected_journals.items():
                        assert (match_dir / name).read_bytes() == expected, name
                    case["same_journals"] = True
                    assert combat.verify(mid)["status"] == "PASS"
                    assert combat.replay(mid)["status"] == "PASS"
                    case["verify_replay"] = "PASS"
                    shutil.rmtree(clone_data)
                    shutil.rmtree(retained_data)
                    # Keep only bounded feed JSON for the browserless JS playback probe.
    finally:
        server.should_exit = True
        thread.join(15)
        sock.close()
        threading.setprofile_all_threads(None)
        logging.getLogger("uvicorn.error").removeHandler(error_handler)
    assert not thread.is_alive(), "fixture server failed to stop within 15 seconds"
    return report
