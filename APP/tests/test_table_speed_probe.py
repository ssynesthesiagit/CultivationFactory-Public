"""Bounded measurement plus equivalence checks, run only through heavyq.

The public collector retains JUnit testcase IDs but discards passed-test stdout.
Use supported parametrization IDs to preserve each scenario's numeric evidence.
Measurement happens once at queued collection; parameter cases validate results.
No timing threshold is treated as a combat correctness assertion.
"""
import json
import subprocess
import tempfile

import pytest

from tools.table_speed_probe import measure, ROOT


def pytest_generate_tests(metafunc):
    if "scenario" not in metafunc.fixturenames:
        return
    from tests.queue_guard import require_test_queue
    require_test_queue()
    base = metafunc.config._tmp_path_factory.getbasetemp()
    with pytest.MonkeyPatch.context() as patch, tempfile.TemporaryDirectory(prefix="measurement-", dir=base) as scratch:
        from pathlib import Path
        patch.setenv("CF_EMBED_MENU", "0")  # no live model ranking in measurements
        report = measure(Path(scratch))
        result = subprocess.run(["node", str(ROOT / "tools/table_speed_playback.mjs")],
                                input=json.dumps(report), text=True, capture_output=True, check=True, timeout=60)
        client = json.loads(result.stdout)
    scenarios = []
    for case in report["scenarios"]:
        # No prose or private files in this evidence: only synthetic timing data.
        case = {key: value for key, value in case.items() if key != "feeds"}
        case["probe_version"] = report["probe_version"]
        case["client_scheduler"] = [row for row in client["results"] if row["actors"] == case["actors"]]
        case["ranking"] = "disabled; no live model"
        scenarios.append(case)
    metafunc.parametrize("scenario", scenarios, ids=[
        "TABLESPEED1_DATA=" + json.dumps(case, separators=(",", ":"), sort_keys=True) for case in scenarios])


def test_table_speed_loopback_phases(scenario):
    # Gate3 ensure_layout touches the journal on every successful load. Preserve
    # that measured metadata churn; only a byte change would violate idle combat.
    assert not scenario["idle_changed_content"], scenario["idle_changed_stamps"]
    assert scenario["same_journals"] and scenario["same_final_state"]
    assert scenario["verify_replay"] == "PASS"
    assert scenario["headless"]["steps_ms"]
    assert scenario["headless_retained_session"]["steps_ms"]
