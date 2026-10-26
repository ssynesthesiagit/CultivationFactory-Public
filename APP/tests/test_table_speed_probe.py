"""Queued public synthetic Slice A timing/equivalence evidence (one sample/roster).

Timing is retained in JUnit parameter IDs because public CI drops passed stdout.
No timing target is substituted for a measured number or used as correctness.
"""
import json
import tempfile
from pathlib import Path

import pytest

from tools.table_speed_probe import measure


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
    assert not scenario["idle_changed_content"], scenario["idle_changed_stamps"]
    assert not scenario["idle_changed_stamps"]
    assert scenario["same_journals"] and scenario["same_final_state"]
    assert scenario["verify_replay"] == "PASS"
    assert scenario["owned"]["start_commands"] == 1
    assert scenario["owned"]["interior_auto_steps"] == scenario["owned"]["interior_deferred_reads"] == 0
    assert scenario["owned"]["acquisitions"] == 1
