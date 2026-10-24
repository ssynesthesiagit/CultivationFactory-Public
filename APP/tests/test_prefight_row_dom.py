import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_prefight_row_dom_title():
    subprocess.run(["node", str(Path(__file__).with_name("prefight_row_dom.test.mjs"))], check=True)
