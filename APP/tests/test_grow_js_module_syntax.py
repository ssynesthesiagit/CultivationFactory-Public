"""static/tabletop/grow.js must parse as an ES module.

A template literal once closed with a stray "»" instead of a backtick. Plain `node --check` on the .js
file did not catch it (it parses as CommonJS and the template text swallowed the error), so the check
copies the file to .mjs and parses it as a module. Parsing is the behaviour: any terminator or bracket
error fails here.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
GROW = APP / "static/tabletop/grow.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_grow_js_parses_as_es_module(tmp_path):
    copy = tmp_path / "grow.mjs"
    shutil.copyfile(GROW, copy)
    result = subprocess.run(["node", "--check", str(copy)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
