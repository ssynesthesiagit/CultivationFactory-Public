"""Focused stored-binding entry regressions; fake transport, no browser/model."""
from pathlib import Path
import subprocess


def test_mobile_play_stored_binding(capsys):
    source = Path(__file__).with_name("mobile_play_binding.test.mjs")
    result = subprocess.run(
        ["node", "--test", "--test-isolation=none", "--test-reporter=tap", str(source)],
        capture_output=True, text=True, timeout=120,
    )
    with capsys.disabled():
        print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
