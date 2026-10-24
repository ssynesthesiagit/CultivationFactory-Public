"""Queued public synthetic Slice A timing/equivalence evidence (one measurement per roster).

The measurement runs once per module inside a fixture (test time, not collection time),
so a harness failure is reported as a test error instead of aborting pytest collection.
Scenario ids are static; the measured numbers are not in the JUnit ids because they are
only known after measuring. Public CI drops passed stdout, so the numbers are recorded in
docs/specs/TABLE_SPEED_SPEC.md with the run they came from. No timing target is used as
correctness, and no live model is called (CF_EMBED_MENU=0).
"""
import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from tools.table_speed_probe import ROOT, measure

SCENARIO_IDS = ["TABLESPEEDA_CASE=actors2-history0", "TABLESPEEDA_CASE=actors6-history0",
                "TABLESPEEDA_CASE=actors2-history100"]


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    from tests.queue_guard import require_test_queue
    require_test_queue()
    base = tmp_path_factory.getbasetemp()
    with pytest.MonkeyPatch.context() as patch, tempfile.TemporaryDirectory(prefix="measurement-", dir=base) as scratch:
        patch.setenv("CF_EMBED_MENU", "0")
        report = measure(Path(scratch))
    scenarios = []
    for case in report["scenarios"]:
        case = {key: value for key, value in case.items() if key != "feeds"}
        case["ranking"] = "disabled; no live model"
        scenarios.append(case)
    assert len(scenarios) == len(SCENARIO_IDS), len(scenarios)
    return scenarios


@pytest.fixture(params=range(len(SCENARIO_IDS)), ids=SCENARIO_IDS)
def scenario(request, measured):
    return measured[request.param]


def test_table_speed_loopback_phases(scenario):
    assert scenario["idle_changed_content"] == [], scenario["idle_changed_content"]
    assert scenario["same_journals"] and scenario["same_final_state"]
    assert scenario["verify_replay"] == "PASS"
    assert scenario["owned"]["start_commands"] == 1
    assert scenario["owned"]["interior_auto_steps"] == scenario["owned"]["interior_deferred_reads"] == 0
    assert scenario["owned"]["acquisitions"] == 1
    assert scenario["headless"]["steps_ms"]
    assert scenario["headless_retained_session"]["steps_ms"]


@pytest.mark.xfail(strict=True, reason=(
    "Known defect: idle loads touch Journal.ndjson (gate3 ensure_layout). TABLE_SPEED_SPEC.md "
    "Section 'Server build' / Slice B says to remove this gratuitous touch. Strict xfail: when the "
    "touch is removed this XPASSes and the marker must be deleted."))
def test_table_speed_idle_load_does_not_touch_journal(scenario):
    assert not scenario["idle_changed_stamps"], scenario["idle_changed_stamps"]


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
