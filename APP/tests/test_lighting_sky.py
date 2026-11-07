"""Presentation-only sky regression, executed through the normal queued test gate."""
from pathlib import Path
import subprocess


def test_sky_presentation_contract():
    result = subprocess.run(["node", "--test", "tests/lighting_sky.test.mjs"], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
