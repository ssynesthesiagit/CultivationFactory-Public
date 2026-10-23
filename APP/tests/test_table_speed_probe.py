"""Queued public synthetic Slice A timing/equivalence evidence (one sample/roster).

Timing is retained in JUnit parameter IDs because public CI drops passed stdout.
No timing target is substituted for a measured number or used as correctness.
"""
import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from tools.table_speed_probe import ROOT, measure


def pytest_generate_tests(metafunc):
    if "scenario" not in metafunc.fixturenames:
        return
    from tests.queue_guard import require_test_queue
    require_test_queue()
    base = metafunc.config._tmp_path_factory.getbasetemp()
    with pytest.MonkeyPatch.context() as patch, tempfile.TemporaryDirectory(prefix="measurement-", dir=base) as scratch:
        patch.setenv("CF_EMBED_MENU", "0")
        report = measure(Path(scratch))
    scenarios = []
    for case in report["scenarios"]:
        case = {key: value for key, value in case.items() if key != "feeds"}
        case["ranking"] = "disabled; no live model"
        scenarios.append(case)
    metafunc.parametrize("scenario", scenarios, ids=[
        "TABLESPEEDA_DATA=" + json.dumps(case, separators=(",", ":"), sort_keys=True) for case in scenarios])


def test_table_speed_loopback_phases(scenario):
    # Gate3 ensure_layout touches the journal on every successful load. Preserve
    # that measured metadata churn; only a byte change would violate idle combat.
    assert not scenario["idle_changed_content"], scenario["idle_changed_stamps"]
    assert scenario["same_journals"] and scenario["same_final_state"]
    assert scenario["verify_replay"] == "PASS"
    assert scenario["owned"]["start_commands"] == 1
    assert scenario["owned"]["interior_auto_steps"] == scenario["owned"]["interior_deferred_reads"] == 0
    assert scenario["owned"]["acquisitions"] == 1
    assert scenario["headless"]["steps_ms"]
    assert scenario["headless_retained_session"]["steps_ms"]


def test_table_speed_client_scheduler(tmp_path, capsys):
    # Browserless scheduler probe on public synthetic feeds (no DOM, layout or GPU).
    def row(sequence, kind, **kwargs):
        return {"event_sequence": sequence, "event_type": kind, "actor_id": "a", **kwargs}
    move = {"phase": "player_move", "last_sequence": 1, "dice": [], "events": [
        row(1, "MOVEMENT_COMMITTED", raw={"payload": {
            "path": [{"x": x, "y": 0} for x in range(6)], "destination": {"x": 5, "y": 0}}})]}
    ai = {**move, "phase": "ai"}
    synthetic = {"scenarios": [{"profiled": False, "actors": 2, "feeds": [move, ai]}]}
    result = subprocess.run(["node", str(ROOT / "tools/table_speed_playback.mjs")],
                            input=json.dumps(synthetic), text=True, capture_output=True, check=True, timeout=20)
    report = json.loads(result.stdout)
    assert [r["movement_timer_budget_ms"] for r in report["results"]] == [550, 300]
    assert all(r["catchup_requests"] == 0 for r in report["results"])
    with capsys.disabled():
        print("TABLESPEED1_CLIENT_JSON=" + json.dumps(report), flush=True)
