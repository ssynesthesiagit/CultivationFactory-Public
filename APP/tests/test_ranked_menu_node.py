"""Queue-compatible offline Node checks; never enable browser execution here."""
import os
from pathlib import Path
import subprocess


def test_ranked_menu_and_seat_ui_node_contracts():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop("EMBEDMENU_BROWSER", None)
    # Keep assertions in one Node process, as test_mobile_play_node does: child
    # isolation can exit before reporting assertions in the worker sandbox.
    result = subprocess.run(["node", "--test", "--test-isolation=none", "static/tabletop/ranked-menu.test.mjs",
        "static/tabletop/ranked-menu.browser.test.mjs", "tests/seats_ui.test.mjs"],
        cwd=root, env=env, capture_output=True, text=True, timeout=30)
    print(result.stdout)
    # CI's compact report keeps the first line. Surface the failing assertions
    # there, rather than starting with a passing/skipped browser check.
    errors = [line.strip() for line in result.stdout.splitlines() if 'Error:' in line or 'error:' in line]
    failures = [line.strip() for line in result.stdout.splitlines()
                if any(word in line for word in ('✖', 'not ok', 'error:', 'Error:', 'actual:', 'expected:'))]
    assert result.returncode == 0, ' | '.join(errors + failures) + '\n' + result.stdout + result.stderr
