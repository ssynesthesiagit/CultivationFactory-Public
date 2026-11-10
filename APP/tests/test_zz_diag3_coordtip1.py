"""TEMPORARY lane diagnostic for COORDTIP1. Not to be committed."""
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parent.parent


def _block(rel):
    r = subprocess.run(["node", "--test", "--test-reporter=spec", str(APP / rel)], capture_output=True, text=True, timeout=300, cwd=str(APP))
    text = (r.stdout + r.stderr)
    i = text.find("failing tests:")
    tail = text[i:] if i >= 0 else text[-2500:]
    return r.returncode, " ".join(tail.split())[:2600]


def test_diag3_ground():
    code, tail = _block("tests/ground_hover_board.test.mjs")
    assert code == 0, f"DIAG3 ground :: {tail}"


def test_diag3_zones():
    code, tail = _block("static/tabletop/zones.test.mjs")
    assert code == 0, f"DIAG3 zones :: {tail}"
