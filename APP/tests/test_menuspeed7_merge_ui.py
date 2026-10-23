"""Public/offline UI coverage for main's composition and kept-bar integration."""
from pathlib import Path
import subprocess


def test_phone_and_desktop_composition_after_lazy_menu_merge():
    result = subprocess.run(
        ["node", "--test", "tests/mobile_play.test.mjs",
         "tests/mobile_play_desktop_guard.test.mjs",
         "tests/mobile_option_composition.test.mjs",
         "tests/option_composition.test.mjs"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=120,
    )
    output = result.stdout + result.stderr
    diagnostic = " | ".join(line.strip() for line in output.splitlines()
                            if "error:" in line or "Error" in line)
    assert result.returncode == 0, diagnostic + "\n" + output
    assert "phone drafts three settings locally" in output
    assert "a real activation inside Options aims the local draft" in output
