"""Runs the node hover regressions under pytest, so `pytest` fails when the hover breaks.

The client card tests live in node because that is where the card and the board are (board.js is
shared with the map editor and runs in the browser). Nothing ran them automatically, so a broken
ground hover stayed green -- the pre-merge review's point. These wrappers make them part of the
python run like tests/test_newcomer_text.py already does for its own node test.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.mark.parametrize("script", ["ground_hover_board.test.mjs"])
def test_board_hover_wiring_and_timing(script: str) -> None:
    """The board's own hover: the per-square index, the two-second rest, and what cancels it."""
    result = subprocess.run(["node", "--test", str(HERE / script)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


def test_ground_card_builder() -> None:
    """The pure card builder, including that it states cover and hazard from the catalog."""
    script = HERE.parent / "static" / "tabletop" / "ground-text.test.mjs"
    result = subprocess.run(["node", "--test", str(script)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
