"""Run the terrain-art Node regression file from the protected pytest queue."""

import subprocess
from pathlib import Path


def test_terrain_art_node_regressions():
    app = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "--test", "static/tabletop/terrain-art.test.mjs"],
        cwd=app,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
