"""Run the confirmation review harness with public synthetic movement data."""
import json
from pathlib import Path
import subprocess


def test_review_harness_reaches_route_confirmation_assertions():
    destination = {"x": 4, "y": 6, "z": 0}
    path = [{"x": 4, "y": 5, "z": 0}, destination]
    payload = {
        "state": {"menu": {"movement_grid": [[4, 6, 0, 5, "walk", False]]}},
        "quote": {"candidate": {
            "candidate_id": "synthetic-native-route",
            "canonical_path": path,
            "movement_cost_ft": 5,
            "metadata": {"hazard_exposure": True},
        }},
        "native": {
            "destination": destination, "path": path, "cost_ft": 5,
            "movement_mode": "walk", "hazard_exposure": True,
        },
    }
    result = subprocess.run(
        ["node", "tests/menuspeed7_review.mjs"],
        cwd=Path(__file__).resolve().parents[1],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30,
    )
    output = result.stdout + result.stderr
    diagnostic = " | ".join(line.strip() for line in output.splitlines()
                            if "Error" in line or "actual:" in line or "expected:" in line)
    assert result.returncode == 0, diagnostic + "\n" + output
    assert "safe/stale/privacy controls passed" in result.stdout
