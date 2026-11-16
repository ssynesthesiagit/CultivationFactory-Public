"""Run the JavaScript production polling harness under the protected pytest queue."""
import subprocess
from pathlib import Path


def test_tabletop_event_sync_node_regressions():
    test_file = Path(__file__).with_name("tabletop_event_sync.test.mjs")
    subprocess.run(["node", "--test", str(test_file)], check=True)
