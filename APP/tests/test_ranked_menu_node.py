"""Offline Node checks with browser execution disabled."""
import os
from pathlib import Path
import subprocess


def test_ranked_menu_and_seat_ui_node_contracts():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop("EMBEDMENU_BROWSER", None)
    # Default Node file isolation also works on runners predating the optional
    # --test-isolation flag; all assertions still reach this captured stream.
    result = subprocess.run(["node", "--test", "static/tabletop/ranked-menu.test.mjs",
        "static/tabletop/ranked-menu.browser.test.mjs", "tests/seats_ui.test.mjs"],
        cwd=root, env=env, capture_output=True, text=True, timeout=30)
    print(result.stdout)
    # Put failing assertions first so abbreviated output remains useful,
    # rather than starting with a passing/skipped browser check.
    errors = [line.strip() for line in result.stdout.splitlines() if 'Error:' in line or 'error:' in line]
    failures = [line.strip() for line in result.stdout.splitlines()
                if any(word in line for word in ('✖', 'not ok', 'error:', 'Error:', 'actual:', 'expected:'))]
    assert result.returncode == 0, ' | '.join(errors + failures) + '\n' + result.stdout + result.stderr
