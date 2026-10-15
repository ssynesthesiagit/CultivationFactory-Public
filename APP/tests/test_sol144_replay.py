"""Opt-in retained-base AI byte comparisons, no full checkout or live data.

Only status_text.py changed on the Python execution path in SOL144. Load that
base module through an import loader in a separate process, then compare all
mechanical and controller capture fields without normalization. Capture itself
also verifies saved mechanical replay. Temp data belongs to pytest basetemp.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

APP = Path(__file__).resolve().parents[1]
SCRIPT = r'''
import importlib.abc, importlib.util, json, subprocess, sys
from pathlib import Path
revision = sys.argv[3]
if revision:
    source = subprocess.check_output(['git', 'show', revision + ':APP/combat/status_text.py']).decode()
    class Baseline(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'combat.status_text':
                return importlib.util.spec_from_loader(fullname, self)
        def create_module(self, spec):
            return None
        def exec_module(self, module):
            module.__file__ = str(Path.cwd() / 'combat/status_text.py')
            exec(compile(source, module.__file__, 'exec'), module.__dict__)
    sys.meta_path.insert(0, Baseline())
from tests.projection_replay_capture import capture
from combat.canonical import canonical_sha256
result = capture(Path(sys.argv[1]), sys.argv[2])
print(json.dumps({key: {'sha256': canonical_sha256(value), 'count': len(value)}
                  for key, value in result.items()}, sort_keys=True))
'''


@pytest.mark.skipif(not os.environ.get('SOL144_REPLAY_BASE'), reason='requires explicit retained Git base')
@pytest.mark.parametrize('scenario', ['stock-1', 'normal-table'])
def test_existing_ai_bytes_and_saved_replay(tmp_path, scenario):
    changed = subprocess.check_output(['git', 'diff', '--name-only', os.environ['SOL144_REPLAY_BASE'],
                                       '--', 'APP/combat'], cwd=APP.parent, text=True).splitlines()
    assert changed == ['APP/combat/status_text.py'], 'expand the baseline loader for any additional combat changes'
    def run(label, revision):
        result = subprocess.run([sys.executable, '-c', SCRIPT, str(tmp_path / label), scenario, revision],
            cwd=APP, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stderr[-3000:] + result.stdout[-3000:]
        return json.loads(result.stdout.splitlines()[-1])
    before = run('base', os.environ['SOL144_REPLAY_BASE'])
    after = run('head', '')
    assert before == after
    print(json.dumps({'scenario': scenario, 'identical': after}, sort_keys=True))
