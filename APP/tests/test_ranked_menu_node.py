"""Queue-compatible offline Node checks; never enable browser execution here."""
import os
from pathlib import Path
import subprocess


def test_ranked_menu_and_seat_ui_node_contracts():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop("EMBEDMENU_BROWSER", None)
    result = subprocess.run(["node", "--test", "static/tabletop/ranked-menu.test.mjs",
        "static/tabletop/ranked-menu.browser.test.mjs", "tests/seats_ui.test.mjs"],
        cwd=root, env=env, capture_output=True, text=True, timeout=30)
    print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
