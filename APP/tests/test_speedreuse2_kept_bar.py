"""FD-6 option B (SPEEDREUSE2): the table keeps its action bar across a free choice and needs no second state read.

Runs the production act/render/renderActionBar/keepActionBar/renderShapePanel/renderObservedState bodies in Node
against a test DOM (tests/speedreuse2_kept_bar.cjs); no browser, network or model.
"""
import subprocess
from pathlib import Path


def test_free_choice_keeps_the_action_bar_and_a_changed_menu_rebuilds_it():
    subprocess.run(["node", str(Path(__file__).with_name("speedreuse2_kept_bar.cjs"))], check=True, timeout=120)
