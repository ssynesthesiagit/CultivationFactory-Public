"""TEMPORARY lane diagnostic for COORDTIP1. Not to be committed."""
import re
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
KEEP = re.compile(r"not ok|error:|expected|actual|location:|message|Error")


def _run(rel):
    r = subprocess.run(["node", "--test", str(APP / rel)], capture_output=True, text=True, timeout=300, cwd=str(APP))
    lines = [l.strip() for l in (r.stdout + r.stderr).splitlines() if KEEP.search(l)]
    return r.returncode, " || ".join(lines)[:3500]


def test_diag_ground_hover():
    code, msg = _run("tests/ground_hover_board.test.mjs")
    assert code == 0, f"DIAG ground rc={code} :: {msg}"


def test_diag_zones():
    code, msg = _run("static/tabletop/zones.test.mjs")
    assert code == 0, f"DIAG zones rc={code} :: {msg}"
