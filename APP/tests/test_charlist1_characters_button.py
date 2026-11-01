"""CHARLIST1: the table's Characters button opens the pop-out sheet on the character list.

Runs tests/charlist1_characters_button.test.mjs with node (the same pattern as
test_sheetpick1_sheet_picker.py). The node file reads the real tabletop.html, tabletop.js and sheet.js and
runs their functions in a vm with a fake window and DOM; no browser, no live server.
"""
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def test_characters_button_and_list_mode_through_real_files():
    out = subprocess.run(["node", "--test", str(APP / "tests" / "charlist1_characters_button.test.mjs")],
                         capture_output=True, text=True, cwd=APP)
    assert out.returncode == 0, f"the Characters button harness failed:\n{out.stdout}\n{out.stderr}"
