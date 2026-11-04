"""ATTACKLIST1: run the attack-group node tests on the public CI.

The behaviour lives in static/tabletop/attack-groups.js and its two surfaces (sheet.js, tabletop.js), so the
regression is a set of Node tests against the real source: the reading itself, the pop-out sheet's ATTACKS
section, and the table's action bar. This wrapper lets the public test runner (pytest) execute them.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES = [
    "tests/attacklist1_groups.test.mjs",
    "tests/attacklist1_sheet.test.mjs",
    "tests/attacklist1_bar.test.mjs",
    "static/tabletop/attack-chip-legal.test.mjs",
]


def test_attacks_are_grouped_by_weapon_on_the_sheet_and_the_bar():
    subprocess.run(["node", "--test", "--test-timeout=120000", *FILES], cwd=ROOT, check=True)
