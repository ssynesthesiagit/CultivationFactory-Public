"""Afterimage map art: a generic ghost for TEMPORARY_IMAGE markers, never the white square, HP or name plate (node test)."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_afterimage_ghost_art_js():
    result = subprocess.run(["node", "--test", str(ROOT / "static/tabletop/afterimage-ghost.test.mjs")],
                            cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
