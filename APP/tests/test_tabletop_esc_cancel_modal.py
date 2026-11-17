"""Public, deterministic regression for cancellation controls inside the modal."""
import subprocess
from pathlib import Path


def test_tabletop_modal_cancellation_controls():
    path = Path(__file__).resolve().parents[1] / "tests" / "tabletop_esc_cancel.test.mjs"
    result = subprocess.run(
        ["node", "--test", "--test-reporter=tap", str(path)],
        text=True, capture_output=True, timeout=60,
    )
    output = result.stdout + result.stderr
    failure = output.find("not ok")
    assert result.returncode == 0, output[failure if failure >= 0 else 0:].replace("\n", " | ")
