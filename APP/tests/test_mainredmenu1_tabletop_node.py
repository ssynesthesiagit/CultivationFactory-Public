"""MAINREDMENU1: the node files that evaluate tabletop.js (whole file or sliced functions) run through pytest.

Each file runs in its own node process, as the repo's other node wrappers do, so one file's failure cannot hide another.
"""
import os
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
NODE_FILES = [
    'altitude_badge', 'altsight', 'fog_altitude', 'fog_mask', 'fog_view',
    'loslines3f22_fog', 'menuspeed6_loading', 'mgr_t2_roof_audience', 'walkable_roofs_movement_ui',
]


@pytest.mark.parametrize('name', NODE_FILES)
def test_tabletop_node_file(name):
    result = subprocess.run(
        ['node', '--test', f'tests/{name}.test.mjs'],
        cwd=APP, env={**os.environ, 'SOL219_BROWSER': '0'},
        capture_output=True, text=True, timeout=600,
    )
    output = result.stdout + result.stderr
    failure = output.find('not ok')
    assert result.returncode == 0, output[failure if failure >= 0 else 0:][:4000]
