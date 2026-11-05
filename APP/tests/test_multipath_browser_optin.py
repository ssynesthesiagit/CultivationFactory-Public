"""Lead runs Chromium outside the sandbox; ordinary pytest never launches it."""
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.skipif(os.environ.get("MULTIPATH_BROWSER") != "1", reason="lead: run outside sandbox with MULTIPATH_BROWSER=1")
def test_multipath_cards_and_header_at_1126px():
    subprocess.run(["node", str(Path(__file__).with_name("sol197_browser.mjs"))], check=True)
