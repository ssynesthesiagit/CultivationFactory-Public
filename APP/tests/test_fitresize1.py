"""FITRESIZE1: the board's Fit holds across viewport resizes (node test through the heavyq pytest gate)."""
from pathlib import Path
import subprocess

APP = Path(__file__).resolve().parents[1]


def test_fit_holds_across_viewport_resizes():
    result = subprocess.run(
        ["node", "--test", "--test-isolation=none", "--test-reporter=tap", "tests/fit_resize_board.test.mjs"],
        cwd=APP, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
