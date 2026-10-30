"""Run real wall painter geometry regressions without launching a browser."""
import subprocess
from pathlib import Path
from tests.node_support import node_test_command


def test_wall_rotation_node():
    app = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        node_test_command('tests/sol214_wall_rotation.test.mjs',
         'static/tabletop/wall-art.test.mjs', 'tests/doors_geometry.test.mjs'),
        cwd=app, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
