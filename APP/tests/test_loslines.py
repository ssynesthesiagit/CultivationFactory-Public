"""Focused deterministic presentation gate. No browser or model calls."""
from pathlib import Path
import subprocess
import pytest


@pytest.mark.parametrize('name', [
    'tests/loslines_board.test.mjs',
    'static/tabletop/board.test.mjs',
    'static/tabletop/fog_memory_board.test.mjs',
    'tests/fog_mask.test.mjs',
    'tests/zone_visibility_board.test.mjs',
    'tests/hovercard_board_dom.test.mjs',
])
def test_loslines_node_regressions(name):
    app = Path(__file__).resolve().parents[1]
    result = subprocess.run(['node', '--test', '--test-isolation=none',
                             str(app / name)],
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
