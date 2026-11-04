"""Focused delayed phone-entry regression using fake HTTP and no browser/model."""
from pathlib import Path
import subprocess
from tests.stateload1_node_support import require_runtime_assets


def test_mobile_play_deferred_control(capsys):
    require_runtime_assets()
    source = Path(__file__).with_name("mobile_play_deferred_control.test.mjs")
    result = subprocess.run(
        ["node", "--test", "--test-isolation=none", "--test-reporter=tap", str(source)],
        capture_output=True, text=True, timeout=120,
    )
    with capsys.disabled():
        print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
