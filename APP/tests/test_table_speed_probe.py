"""TABLESPEED1 measurement only: synthetic, bounded, no live models or browser."""
import json

from tools.table_speed_probe import measure


def test_table_speed_loopback_phases(tmp_path, capsys):
    report = measure(tmp_path)
    assert all(not case["idle_changed_files"] for case in report["scenarios"])
    assert all(case["same_journals"] and case["same_final_state"] for case in report["scenarios"])
    with capsys.disabled():
        print("TABLESPEED1_JSON=" + json.dumps(report, separators=(",", ":")), flush=True)
