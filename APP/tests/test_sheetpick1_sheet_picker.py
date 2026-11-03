"""SHEETPICK1: pop-out sheet load error text and character picker loading/retry lines.

Runs tests/sheetpick1_sheet_picker.test.mjs with node (the same pattern as test_mmx74_player_text.py).
The node file uses a fake DOM and a controlled fetch; no browser, no live server.
"""
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def test_sheet_load_error_and_picker_states_through_real_modules():
    out = subprocess.run(["node", "--test", str(APP / "tests" / "sheetpick1_sheet_picker.test.mjs")],
                         capture_output=True, text=True, cwd=APP)
    assert out.returncode == 0, f"the picker harness failed:\n{out.stdout}\n{out.stderr}"
