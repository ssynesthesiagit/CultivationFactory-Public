"""Findings 2, 3, 4 and 5 (LIGHTS2): the editor's ambient rules and the shared-view combine, as behavior (node)."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_ambient_editor_and_view_rules():
    node = shutil.which("node")
    assert node, "Node.js is required for the tabletop's existing JavaScript test suite"
    result = subprocess.run([node, "--test", "tests/ambient_edit.test.mjs"], cwd=ROOT, capture_output=True, text=True,
                            timeout=60)
    if result.returncode:
        lines = (result.stdout + result.stderr).splitlines()
        failures = [line for line in lines if line.startswith(("not ok", "✖", "Error:", "AssertionError"))]
        raise AssertionError("Node test failures: " + " | ".join(failures or lines[-20:]))
