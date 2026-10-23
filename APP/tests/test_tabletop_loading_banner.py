"""Public regression check for deferred-menu loading UX."""
import subprocess
from pathlib import Path


def test_tabletop_loading_banner_node():
    path = Path(__file__).with_name("tabletop_loading_banner.test.mjs")
    result = subprocess.run(
        ["node", "--test", "--test-reporter=tap", str(path)],
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
