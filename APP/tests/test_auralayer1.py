"""Browser-free shared-renderer checks admitted through the heavyq pytest gate."""
import os
from pathlib import Path
import subprocess

APP = Path(__file__).resolve().parents[1]


def test_aura_height_dom_regressions():
    env = dict(os.environ)
    # Browser QA and historical renderer injection are opt-in, never in this gate.
    for name in ("RUN_AURALAYER1_BROWSER_TESTS", "AURALAYER1_BOARD_SOURCE",
                 "AURALAYER1_ELEVATION_SOURCE", "AURALAYER1_BASE_REF"):
        env.pop(name, None)
    result = subprocess.run(
        ["node", "--test", "--test-isolation=none", "--test-reporter=tap",
         "tests/area_elevation_board.test.mjs", "tests/area_elevation.browser.test.mjs"],
        cwd=APP, env=env, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
