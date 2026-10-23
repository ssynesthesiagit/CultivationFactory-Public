"""Scheduler-only probe, through pytest/heavyq; does not start a browser."""
import json
from pathlib import Path
import subprocess

from tools.table_speed_probe import ROOT


def test_table_speed_client_scheduler(tmp_path, capsys):
    # Public synthetic feeds. A five-square walk and an attack roll cover both waits.
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
