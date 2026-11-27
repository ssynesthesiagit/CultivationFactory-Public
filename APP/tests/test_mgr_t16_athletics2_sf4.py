"""Acceptance fixtures must import without unrelated historical fight tests."""
import subprocess
import sys
from pathlib import Path

ACCEPTANCE_MODULES = (
    'test_mgr_t16_athletics2_sf3',
    'test_mgr_t16_athletics2_rb1',
    'test_mgr_t16_athletics2_review',
    'test_mgr_t16_athletics_1_fx2',
)


def test_acceptance_fixtures_do_not_import_historical_fights():
    script = '''
import importlib
import importlib.abc
import sys

class NoHistoricalFights(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.rsplit('.', 1)[-1] in {
            'test_r9i_karma_persistence',
            'test_a2_athletics_second_pass',
        }:
            raise AssertionError('Acceptance fixture imported historical test: ' + fullname)

sys.meta_path.insert(0, NoHistoricalFights())
sys.path.insert(0, 'tests')  # cwd is APP; import the fixtures by the bare name pytest gives them
for module in sys.argv[1:]:
    importlib.import_module(module)
'''
    result = subprocess.run([sys.executable, '-c', script, *ACCEPTANCE_MODULES],
                            cwd=Path(__file__).resolve().parents[1],
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
