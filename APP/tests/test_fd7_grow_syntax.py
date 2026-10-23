"""FD7GCF1 review fix: static/tabletop/grow.js must parse as an ES module.

The Golden Core block had template literals closed with a stray "»" instead of a backtick.
Plain `node --check` on the .js file does not catch that (it parses as CommonJS and the
template text swallowed the error), so the check copies the file to .mjs and parses it as a module.
The text check fails on any stray guillemet in the file, which is what the broken lines contained.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
GROW = APP / "static/tabletop/grow.js"


def test_grow_js_has_no_stray_guillemet_terminators():
    source = GROW.read_text(encoding="utf-8")
    bad = [n for n, line in enumerate(source.splitlines(), 1) if "\u00bb" in line]
    assert bad == [], f"stray U+00BB used as template terminator on lines {bad}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_grow_js_parses_as_es_module(tmp_path):
    copy = tmp_path / "grow.mjs"
    shutil.copyfile(GROW, copy)
    result = subprocess.run(["node", "--check", str(copy)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
