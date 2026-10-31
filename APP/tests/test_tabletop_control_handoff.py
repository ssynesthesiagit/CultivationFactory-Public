from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_current_turn_ai_handoff_client_regression():
    result = subprocess.run(
        ["node", "--test", "tests/tabletop_control_handoff.test.mjs"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
