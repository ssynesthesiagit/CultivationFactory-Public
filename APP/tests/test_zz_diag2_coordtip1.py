"""TEMPORARY lane diagnostic for COORDTIP1. Not to be committed."""
import re
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
FAIL = re.compile(r"(✖|not ok|failureType|error:)")


def _names(rel):
    r = subprocess.run(["node", "--test", "--test-reporter=spec", str(APP / rel)], capture_output=True, text=True, timeout=300, cwd=str(APP))
    out = (r.stdout + r.stderr).splitlines()
    fails = [l.strip()[:160] for l in out if FAIL.search(l)]
    passes = sum(1 for l in out if "✔" in l)
    return r.returncode, passes, fails[:12]


def test_diag_ground_names():
    code, passes, fails = _names("tests/ground_hover_board.test.mjs")
    assert code == 0, f"DIAG2 ground rc={code} pass={passes} :: " + " | ".join(fails)


def test_diag_zones_names():
    code, passes, fails = _names("static/tabletop/zones.test.mjs")
    assert code == 0, f"DIAG2 zones rc={code} pass={passes} :: " + " | ".join(fails)
