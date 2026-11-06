"""Public regression for the production desktop second-tab observer lifecycle."""
import subprocess
from pathlib import Path


def test_idle_second_tab_observes_run_completion():
    script = Path(__file__).with_name("table_speed_observer.test.mjs")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
