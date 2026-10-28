"""Phone fog capture/persistence/render and guided binding-copy regressions."""
import subprocess
from pathlib import Path
from tests.node_support import node_test_command


def test_mobile_play_memory(capsys):
    result = subprocess.run(
        node_test_command('--test-reporter=tap',
         str(Path(__file__).with_name('mobile_play_memory.test.mjs'))),
        capture_output=True, text=True, timeout=120,
    )
    with capsys.disabled():
        print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
