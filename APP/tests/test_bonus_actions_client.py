"""Public, offline coverage of bonus-action loading and stranded local choices."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def assert_node_success(result):
    output = result.stdout + result.stderr
    # Public CI retains the first assertion line: lead with the Node failure.
    lines = [line.strip() for line in output.splitlines()]
    errors = [line for line in lines if any(word in line for word in
                                           ("error:", "Error:", "AssertionError"))]
    failed = [line for line in lines if "✖" in line or "not ok" in line]
    diagnostic = " | ".join(errors + failed)
    assert result.returncode == 0, diagnostic + "\n" + output


def test_bonus_action_client_regressions():
    result = subprocess.run(
        ["node", "--test", "tests/bonus_actions_client.test.mjs"],
        cwd=ROOT, text=True, capture_output=True, timeout=60,
    )
    assert_node_success(result)


def test_existing_chooser_and_draft_regressions():
    # Focus only on the production chooser, lazy expansion and choice lifecycle.
    result = subprocess.run(
        ["node", "--test", "tests/menuspeed7_lazy.test.mjs",
         "tests/option_composition.test.mjs", "tests/tabletop_target_selection.test.mjs",
         "tests/optionspeed1_sheet_controller_public.test.mjs",
         "static/tabletop/tabletop.test.mjs", "static/tabletop/tabletop_map_pick_hit.test.mjs"],
        cwd=ROOT, text=True, capture_output=True, timeout=120,
    )
    assert_node_success(result)
