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
# The public exporter's literal dependency scan does not strip import cache
# query strings yet. Declare the resources used by these offline harnesses so
# their CI snapshot contains the same modules as the working tree.
CACHE_BUSTED_RESOURCES = [
    "static/tabletop/active.js",
    "static/tabletop/art-kit.js",
    "static/tabletop/decor-place.js",
    "static/tabletop/feed-presentation.js",
    "static/tabletop/map-height-cards.js",
    "static/tabletop/map-history.js",
    "static/tabletop/object-arrange.js",
    "static/tabletop/object-art-catalog.js",
    "static/tabletop/object-delete.js",
    "static/tabletop/remembered_scenery.js",
    "static/tabletop/scenery-raster.js",
    "static/tabletop/wall-object-art.js",
    "static/tabletop/zonepaint.js",
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
    if result.returncode:
        lines = result.stdout.splitlines()
        error_at = next((i for i, line in enumerate(lines)
                         if "Error [" in line or "Error:" in line or "error:" in line), 0)
        cause = " ".join(line.strip() for line in lines[error_at:error_at + 5])
        pytest.fail(f"{test_file}: {cause}\n{result.stdout}")


def test_cache_busted_node_resources_available():
    for resource in CACHE_BUSTED_RESOURCES:
        assert (APP / resource).is_file(), resource


def test_tabletop_entrypoint_and_board_cache_versions_match():
    html = (APP / "static/tabletop/tabletop.html").read_text()
    script = (APP / "static/tabletop/tabletop.js").read_text()
    entry = re.findall(r'src="/static/tabletop/tabletop\.js\?v=([^"&]+)"', html)
    board = re.findall(r'from "\./board\.js\?v=([^"&]+)"', script)
    assert len(entry) == len(board) == 1
    assert entry == board, "The page and merged board must refresh together"
