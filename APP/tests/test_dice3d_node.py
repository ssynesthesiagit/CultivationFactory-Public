"""Run the public dice renderer's Node suite through the test queue."""
import subprocess
from pathlib import Path


APP = Path(__file__).resolve().parents[1]


def test_dice3d_node_suite():
    result = subprocess.run(
        ["node", "--test", "static/tabletop/dice3d.test.mjs"],
        cwd=APP, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
