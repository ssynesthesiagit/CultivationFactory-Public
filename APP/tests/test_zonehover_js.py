"""Run the table's pure JavaScript hover tests without a browser."""
import subprocess
from pathlib import Path


def test_zone_hover_javascript():
    result = subprocess.run(
        ["node", "--test", "--test-isolation=none", "--test-reporter=tap", "tests/zonehover.test.mjs",
         "tests/zone_condition_text.test.mjs"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
