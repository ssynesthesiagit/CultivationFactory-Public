"""Historical provider discovery must stay inside the requested Git tree."""
from pathlib import Path
import subprocess
import sys


def test_old_tree_provider_discovery_is_isolated(tmp_path):
    script = '''
from pathlib import Path
from tests.wall_height_stock_capture import revision_sources
root = revision_sources('ded5fcaa', Path(__import__('sys').argv[1]))
from combat import ext
ext._load()
assert not (root / 'combat/ext/air_second_pass.py').exists()
assert (root / 'combat/ext/__init__.py').exists()
try:
    __import__('combat.ext.air_second_pass')
except ModuleNotFoundError:
    pass
else:
    raise AssertionError('a missing baseline module must still fail closed')
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-3000:]
