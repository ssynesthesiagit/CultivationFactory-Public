"""Opt-in six stock base/head captures and full route cost/legal-set equality.

FLIGHTSIGHT_REPLAY_BASE selects the Git baseline. Captures create only synthetic
test data, never load live saves, and launch no GUI. Evidence retains hashes and
counts; pytest's disk-backed basetemp owns disposable full captures/databases.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_save_reload_equivalence import STOCK_SEEDS

APP = Path(__file__).resolve().parents[1]
BASE = os.environ.get("FLIGHTSIGHT_REPLAY_BASE")
pytestmark = pytest.mark.skipif(not BASE, reason="opt in with FLIGHTSIGHT_REPLAY_BASE")


@pytest.mark.parametrize("scenario", [*STOCK_SEEDS, "routes"])
def test_stock_replays_and_route_prices_match_base(tmp_path, scenario):
    captures = []
    for label in ("base", "head"):
        args = [sys.executable, "-m", "tests.flightsight_capture", str(tmp_path / label), scenario]
        if label == "base":
            args.append(BASE)
        result = subprocess.run(args, cwd=APP, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                capture_output=True, text=True, timeout=600)
        assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-4000:]
        captures.append(json.loads(result.stdout.splitlines()[-1]))
    def encoded(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    evidence = {"scenario": scenario, "base": BASE, "identical": captures[0] == captures[1],
        "fields": {key: {"base_sha256": hashlib.sha256(encoded(captures[0][key])).hexdigest(),
                         "head_sha256": hashlib.sha256(encoded(captures[1][key])).hexdigest(),
                         "count": len(captures[0][key]) if isinstance(captures[0][key], (dict, list)) else captures[0][key]}
                   for key in captures[0]} if scenario != "routes" else
        {"destinations": len(captures[0]), "base_sha256": hashlib.sha256(encoded(captures[0])).hexdigest(),
         "head_sha256": hashlib.sha256(encoded(captures[1])).hexdigest()}}
    if os.environ.get("FLIGHTSIGHT_REPLAY_EVIDENCE"):
        output = Path(os.environ["FLIGHTSIGHT_REPLAY_EVIDENCE"])
        output.mkdir(parents=True, exist_ok=True)
        (output / (scenario + ".json")).write_text(json.dumps(evidence, indent=2) + "\n")
    assert encoded(captures[0]) == encoded(captures[1]), evidence
