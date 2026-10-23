"""One-shot AUTORESOLVE1 evidence; synthetic service fights, no live transports."""
import json
import platform
import socket
import time
import zipfile

import pytest

from combat.gate5_service import CombatService
from tests.ai_tiers_fixtures import sheet

from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("per_side", [1, 4])
def test_durable_headless_timing(tmp_path, monkeypatch, capsys, per_side):
    def deny(*args, **kwargs):
        raise AssertionError("Timing evidence must not call a live server")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    ids = [f"00000000-0000-4000-8000-{i:012d}" for i in range(1, 2 * per_side + 1)]
    for i, pid in enumerate(ids):
        doc = sheet([], mechanics={}, name=f"Fighter {i + 1}", cl=10,
                    kit={"starting_kit": {"items": [
                        {"item_id": "tianxia.mortal.weapon.jian", "quantity": 1}]}})
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    tick = time.perf_counter()
    svc = CombatService(ROOT, tmp_path)
    startup_s = time.perf_counter() - tick
    tick = time.perf_counter()
    mid = svc.create_factory_match(
        project_ids=ids[:per_side],
        opponent_actor_ids=["actor:factory." + pid for pid in ids[per_side:]],
        match_seed="AUTORESOLVE1-MEASURE-1",
        arena_id="battlefield:factory_pillar_arena", maximum_rounds=3)["match_id"]
    create_s = time.perf_counter() - tick
    tick = time.perf_counter()
    times = []
    for step in range(300):
        started = time.perf_counter()
        response = svc.local_step(mid)
        times.append(time.perf_counter() - started)
        assert response["status"] == "COMMITTED"
        if response["match"]["state"]["terminal_result"]:
            break
    run_s = time.perf_counter() - tick
    session = svc._load_session(mid)
    terminal = session.engine.state.terminal_result
    assert terminal is not None, "Timing cap is not permission to invent an outcome"
    turns = sum(e.event_type == "TURN_STARTED" for e in session.engine.events)
    ended_turns = sum(e.event_type == "TURN_ENDED" for e in session.engine.events)
    tick = time.perf_counter()
    replay = svc.verify(mid)
    verify_s = time.perf_counter() - tick
    assert replay["status"] == "PASS"
    row = dict(host=platform.node(), platform=platform.platform(), actors=2 * per_side,
               seed="AUTORESOLVE1-MEASURE-1", arena="battlefield:factory_pillar_arena",
               round_cap=3, round_number=session.engine.state.round_number,
               terminal=terminal.kind.value, startup_s=startup_s, create_s=create_s,
               run_s=run_s, verify_s=verify_s, steps=len(times), turns_started=turns,
               turns_ended=ended_turns, events=len(session.engine.events),
               mean_step_s=sum(times)/len(times),
               p95_step_s=sorted(times)[max(0, int(.95*len(times))-1)],
               seconds_per_started_actor_turn=run_s/turns,
               seconds_per_round_equivalent=run_s/(turns/(2*per_side)))
    with capsys.disabled():
        print("AUTORESOLVE1_MEASUREMENT " + json.dumps(row, sort_keys=True), flush=True)
