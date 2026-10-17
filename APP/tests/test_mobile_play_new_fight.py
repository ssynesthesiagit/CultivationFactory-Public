"""Phone loading and Factory setup, deterministic Node DOM transport regressions."""
from pathlib import Path
import subprocess
import pytest


@pytest.mark.parametrize('filename', [
    'mobile_play_new_fight.test.mjs',
    'mobile_play_binding.test.mjs',
    'mobile_play_deferred_control.test.mjs',
    'mobile_play_control_preferences.test.mjs',
    'mobile_play_control_recovery.test.mjs',
])
def test_mobile_play_new_fight(capsys, filename):
    # Existing controller tests already inject a fake board. Run them unchanged
    # with the same graphics-only import stub so public export omissions do not
    # prevent their actual ownership and turn-control assertions from running.
    source = Path(__file__).with_name(filename)
    board_stub = source.with_name('mobile_play_new_fight_board_stub.mjs')
    result = subprocess.run(['node', '--import', str(board_stub), '--test', '--test-isolation=none', '--test-reporter=tap', str(source)],
                            capture_output=True, text=True, timeout=120)
    with capsys.disabled():
        print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
