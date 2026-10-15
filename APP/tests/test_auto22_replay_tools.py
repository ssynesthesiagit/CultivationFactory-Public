"""Evidence tools must prove entered cells and reject incomplete runs."""
import subprocess
import sys

import pytest

from tests.h1_support import ROOT
from tools.auto22r5f1_wall_replay import capture, failures


def successful_result():
    return {"replay": "PASS", "commit_reload": "PASS", "movement_budget": {"before_ft": 30, "after_ft": 10}, "forced_casts": [
        {"ability": name, "status": "EXECUTED"} for name in ("Gather Sand", "Dune Wall")],
        "move_probe": [{"wall_exempt_entered": [[3, 7]], "expected_cost_ft": 20,
                        "cost_ft": 20, "planned_cost_ft": 20}]}


@pytest.mark.parametrize("defect", ["no crossing", "failed cast", "missing cast", "replay", "crash", "quote", "cost", "budget", "reload", "observer"])
def test_evidence_gate_rejects_each_failure(defect):
    result = successful_result()
    assert failures(result, "wall") == []
    if defect == "no crossing":
        result["move_probe"][0]["wall_exempt_entered"] = []
    elif defect == "failed cast":
        result["forced_casts"][0]["status"] = "FAILED"
    elif defect == "missing cast":
        result["forced_casts"].pop()
    elif defect == "replay":
        result["replay"] = "FAIL"
    elif defect == "crash":
        result["crash"] = "traceback"
    elif defect == "quote":
        result["move_probe"][0]["planned_cost_ft"] = 5
    elif defect == "budget":
        result["movement_budget"]["after_ft"] = 30
    elif defect == "reload":
        result["commit_reload"] = "FAIL"
    elif defect == "observer":
        result["observer_errors"] = ["probe failed"]
    else:
        result["move_probe"][0]["expected_cost_ft"] = 5
    assert failures(result, "wall")


def test_persistent_crossing_records_entered_wall_and_exemption_cells(tmp_path):
    result = capture(ROOT, tmp_path, "wall", "SOLFAUTO22r6")
    assert result["failures"] == [], result
    assert result["commit_reload"] == result["replay"] == "PASS"
    assert result["movement_budget"] == {"before_ft": 30, "after_ft": 10}
    crossing, = result["move_probe"]
    assert crossing["path"] == [{"x": 3, "y": 6}, {"x": 3, "y": 7}]
    assert crossing["wall_exempt_entered"] == [(3, 7)]
    assert crossing["cost_ft"] == crossing["planned_cost_ft"] == crossing["expected_cost_ft"] == 20
    event = result["document"]["events"][crossing["sequence"] - 1]
    assert event["event_type"] == "MOVEMENT_COMMITTED"
    assert event["payload"]["path"] == crossing["path"]


def test_reachability_table_names_scope_and_prints_actual_old_and_new():
    output = subprocess.check_output([sys.executable, str(ROOT / "tools/auto22r5f1_unimpeded_reachability.py")], text=True)
    rows = [line.split("|") for line in output.splitlines() if "| uncovered |" in line]
    row = next(parts for parts in rows if parts[0].split() == ["2", "4", "4"])
    assert row[2].strip() == "2 /   4"
    assert row[3].strip().startswith("YES")
    assert "snapshot, not a guard" in output
