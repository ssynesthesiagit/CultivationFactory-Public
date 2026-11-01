"""Exercise the source declarations toolbar without a browser."""
import subprocess
from pathlib import Path


def test_source_inputs_button_node():
    subprocess.run(["node", "--test", str(Path(__file__).with_name("source_inputs_button.test.mjs"))], check=True)
