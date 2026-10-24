"""NOACTIONINPLACE1 F2: runs the kept-action-bar browser-model tests (node --test) through pytest so heavyq admits them.

The .mjs files use only public static modules and an inline DOM model, so they run on public CI."""
import os
import subprocess

import pytest

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.parametrize("path", [
    "tests/noaction_inplace1_kept_bar.test.mjs",
    "static/tabletop/ranked-menu.test.mjs",
])
def test_kept_bar_node_suite(path):
    result = subprocess.run(["node", "--test", path], cwd=APP, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
