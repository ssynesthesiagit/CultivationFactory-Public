"""NOACTIONSHEET1: runs the sheet in-place setting test (node --test) through pytest so heavyq admits it.

The .mjs suite uses only the public static sheet module and a synthetic DOM model, so it runs on public CI.
"""
import os
import subprocess

import pytest

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.parametrize("path", ["tests/noaction_sheet1_inplace.test.mjs"])
def test_sheet_inplace_node_suite(path):
    result = subprocess.run(["node", "--test", path], cwd=APP, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
