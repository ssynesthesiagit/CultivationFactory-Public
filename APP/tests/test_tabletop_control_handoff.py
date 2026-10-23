from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_current_turn_ai_handoff_client_regression():
    subprocess.run(
        ["node", "--test", "tests/tabletop_control_handoff.test.mjs"],
        cwd=ROOT,
        check=True,
        timeout=30,
    )
