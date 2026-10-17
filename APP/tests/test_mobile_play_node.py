"""Exact phone Node/DOM regressions through the protected pytest test queue."""
import subprocess
from pathlib import Path


def test_mobile_play_node_and_desktop_guard(capsys):
    here = Path(__file__).parent
    # The sandbox's Node child isolation exits before reporting assertions.
    # Both files are deterministic and run serially in one Node process instead.
    result = subprocess.run(["node", "--test", "--test-isolation=none", "--test-reporter=tap", str(here / "mobile_play.test.mjs"),
                             str(here / "mobile_play_desktop_guard.test.mjs")], capture_output=True, text=True, timeout=120)
    with capsys.disabled():
        print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
