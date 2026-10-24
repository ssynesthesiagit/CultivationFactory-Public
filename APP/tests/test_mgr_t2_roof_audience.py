"""Actual table audience wiring against real JS modules; no browser or private fights."""
import os
from pathlib import Path
import subprocess


def test_production_roof_audience_wiring():
    result = subprocess.run(
        ['node', '--test', '--test-isolation=none', 'tests/mgr_t2_roof_audience.test.mjs'],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, 'SOL219_BROWSER': '0', 'MGR_T2_TABLE_STDIN': '0'},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
