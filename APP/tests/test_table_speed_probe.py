"""TABLESPEED1 measurement only: synthetic, bounded, no live models or browser."""
import json
import subprocess

from tools.table_speed_probe import measure, ROOT


def test_table_speed_loopback_phases(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CF_EMBED_MENU", "0")  # no live model ranking in measurements
    report = measure(tmp_path)
    result = subprocess.run(["node", str(ROOT / "tools/table_speed_playback.mjs")],
                            input=json.dumps(report), text=True, capture_output=True, check=True, timeout=60)
    report["client_scheduler"] = json.loads(result.stdout)
    report["ranking"] = "CF_EMBED_MENU=0; excludes model ranking latency"
    with capsys.disabled():
        print("TABLESPEED1_JSON=" + json.dumps(report, separators=(",", ":")), flush=True)
    assert all(not case["idle_changed_files"] for case in report["scenarios"]), [
        (case["actors"], case["profiled"], case["idle_changed_files"]) for case in report["scenarios"]]
    assert all(case["same_journals"] and case["same_final_state"] for case in report["scenarios"])
