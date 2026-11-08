"""Keep owner table contracts in the protected pytest gate; no GUI/model calls."""
import subprocess
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def test_owner_ui_contract():
    for script in ["tests/owner_ui_contract.test.mjs", "tests/altitude_badge.test.mjs",
                   "tests/owner_ui_contract.browser.test.mjs"]:
        result = subprocess.run(["node", str(APP / script)], cwd=APP, capture_output=True,
                                text=True, timeout=120)
        assert result.returncode == 0, f"{script}:\n{result.stdout}\n{result.stderr}"
