"""SHEETAVAIL2: run the pop-out sheet's row-availability node test on public CI.

The greying rule lives in static/tabletop/sheet.js, so its regression is a Node test against the real
applyLegal/activate source (tests/sheetavail2_sheet_rows.test.mjs). This wrapper lets the public test runner (pytest)
execute it, the same way tests/test_sheetavail1_rows.py and tests/test_option_tooltips.py run their .mjs files.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sheet_greys_every_action_row_the_table_refuses_and_names_the_condition():
    subprocess.run(
        ["node", "--test", "--test-timeout=120000", "tests/sheetavail2_sheet_rows.test.mjs"],
        cwd=ROOT, check=True)
