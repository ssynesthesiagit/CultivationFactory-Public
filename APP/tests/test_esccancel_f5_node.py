"""Public Node regression tests for optional reaction-dialog cancellation."""
import subprocess
from pathlib import Path


def test_tabletop_esc_cancel_production_dispatch():
    test_file = Path(__file__).with_name("tabletop_esc_cancel.test.mjs")
    result = subprocess.run(
        ["node", "--test", str(test_file)],
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
