"""SHEETHANDS1: run the sheet's weapon-copy node test on public CI.

The behaviour lives in static/tabletop/sheet.js, so the regression is a Node test
against the real groupButtons/applyLegal source. This wrapper lets the public test
runner (pytest) execute it.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sheet_groups_physical_weapon_copies_and_uses_the_offered_copy():
    subprocess.run(
        ["node", "--test", "--test-timeout=120000", "tests/sheet_hands1_copies.test.mjs"],
        cwd=ROOT, check=True)
