"""Offline wall/fog and tabletop entrypoint checks, runnable by the pytest CI queue."""

from pathlib import Path
import re
import subprocess

import pytest


APP = Path(__file__).resolve().parents[1]
NODE_TESTS = [
    "static/tabletop/board-terrain.test.mjs",
    "static/tabletop/fog_memory_board.test.mjs",
    "static/tabletop/objects.test.mjs",
    "static/tabletop/region-wall-art.test.mjs",
    "static/tabletop/board.test.mjs",
    "static/tabletop/tabletop.test.mjs",
    "tests/fog_mask.test.mjs",
    "tests/tabletop_event_sync.test.mjs",
    "tests/fog_view.test.mjs",
    "tests/objects_entrypoints.test.mjs",
]


@pytest.mark.parametrize("test_file", NODE_TESTS)
def test_region_wall_rendering_node(test_file):
    result = subprocess.run(
        ["node", "--test", "--test-isolation=none", test_file],
        cwd=APP,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout


def test_tabletop_entrypoint_and_board_cache_versions_match():
    html = (APP / "static/tabletop/tabletop.html").read_text()
    script = (APP / "static/tabletop/tabletop.js").read_text()
    entry = re.findall(r'src="/static/tabletop/tabletop\.js\?v=([^"&]+)"', html)
    board = re.findall(r'from "\./board\.js\?v=([^"&]+)"', script)
    assert len(entry) == len(board) == 1
    assert entry == board, "The page and merged board must refresh together"
