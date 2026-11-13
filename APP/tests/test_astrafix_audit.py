"""Regressions for independent audit findings."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from combat import gate5_service, tabletop_service


def test_atomic_json_concurrent_writers_use_distinct_private_temps(tmp_path, monkeypatch):
    target = tmp_path / "profile.json"
    barrier = threading.Barrier(2)
    real_fsync = gate5_service.os.fsync

    def sync(fd):
        barrier.wait(timeout=5)
        real_fsync(fd)

    monkeypatch.setattr(gate5_service.os, "fsync", sync)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(gate5_service._atomic_json, target, {"writer": n}) for n in range(2)]
        for future in futures:
            future.result()
    assert json.loads(target.read_text())["writer"] in (0, 1)
    assert not list(tmp_path.glob("*.tmp.*"))
    assert target.stat().st_mode & 0o777 == 0o600


def test_private_events_do_not_leak_unreferenced_dice(monkeypatch, tmp_path):
    from combat import private_information
    service = object.__new__(tabletop_service.TabletopService)
    service._match_dir = lambda match: tmp_path
    service._names_for = lambda match, engine: ({}, {})
    service._diagnostic_fields = lambda match: {}
    engine = SimpleNamespace(state=SimpleNamespace(state_version=7, model_dump=lambda **kw: {}),
                             action_catalog={})
    private = {"event_type": "SECRET", "payload": {"roll_id": "private"}}
    rolls = [{"roll_id": "private"}]
    monkeypatch.setattr(tabletop_service, "journal_since", lambda *args: ([private], rolls, 4, []))
    monkeypatch.setattr(private_information, "event_audience", lambda engine, event: "owner")
    monkeypatch.setattr(tabletop_service, "concealed_condition_instances", lambda state: set())
    seen = []
    monkeypatch.setattr(tabletop_service, "format_history_feed", lambda events, dice, **kw: [])
    monkeypatch.setattr(tabletop_service, "dice_rows", lambda dice, *args: seen.extend(dice) or [])
    result = service.events("match", 0, engine=engine)
    assert seen == []
    assert result["dice"] == []
    assert (result["last_sequence"], result["state_version"]) == (4, 7)
