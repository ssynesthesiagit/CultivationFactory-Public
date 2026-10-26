"""SHEETAVAIL1: run the pop-out sheet's availability node test on public CI.

The behaviour lives in static/tabletop/sheet.js, so the regression is a Node test against the real
applyLegal/activate source. This wrapper lets the public test runner (pytest) execute it.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sheet_greys_rest_of_attack_rows_the_table_refuses():
    subprocess.run(
        ["node", "--test", "--test-timeout=120000", "tests/sheetavail1_rest_rows.test.mjs"],
        cwd=ROOT, check=True)
