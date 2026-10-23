"""Run the browser-independent lighting presentation and editor contract tests under the queued pytest gate."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_lighting_client_contracts():
    node = shutil.which("node")
    assert node, "Node.js is required for the tabletop's existing JavaScript test suite"
    result = subprocess.run(
        [node, "--test", "tests/lighting.test.mjs", "tests/lighting_editor.test.mjs"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
