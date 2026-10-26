"""Exercise historical imports and the actual receipt gate without any fights."""
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize('contaminate_fixture', [False, True])
def test_historical_capture_provenance(tmp_path, contaminate_fixture):
    # Isolate the script's global import/open hooks from pytest. Execute its
    # real setup and receipt code, omitting only combat imports and captures.
    # Synthetic Git blobs deliberately predate replay_assertions.py.
    script = Path(__file__).with_name('prompt_ui_replay.py')
    probe = r'''
import ast
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

script, output, contaminate = sys.argv[1:]
source = Path(script).read_text()
tree = ast.parse(source, filename=script)
split = next(i for i, node in enumerate(tree.body)
             if isinstance(node, ast.ImportFrom) and node.module == 'combat.canonical')
receipt = next(i for i, node in enumerate(tree.body)
               if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == 'provenance' for t in node.targets))
blobs = {'APP/combat/__init__.py': b'origin = "historical combat"',
         'APP/tests/__init__.py': b'',
         'APP/tests/provenance_fixture.py': b'origin = "historical fixture"'}
oids = {path: hashlib.sha256(data).hexdigest() for path, data in blobs.items()}

def git_output(command, **kwargs):
    operation = command[3]
    if operation == 'rev-parse':
        return 'synthetic-historical-commit\n'
    if operation == 'ls-tree':
        return b''.join(('100644 blob ' + oids[path] + '\t' + path).encode() + b'\0'
                        for path in blobs)
    assert operation == 'cat-file', command
    return next(blobs[path] for path in blobs if oids[path] == command[-1])

subprocess.check_output = git_output
sys.argv = [script, 'historical-ref', output, output + '-scratch']
namespace = {'__file__': script, '__name__': '__main__'}
exec(compile(ast.Module(body=tree.body[:split], type_ignores=[]), script, 'exec'), namespace)
combat = importlib.import_module('combat')
fixture = importlib.import_module('tests.provenance_fixture')
assert combat.origin == 'historical combat'
assert fixture.origin == 'historical fixture'
namespace['assert_replay_equal']({'state': [1]}, {'state': [1]})
if contaminate == 'True':
    # A current-tree fixture must remain forbidden: no broad tests.* exclusion.
    fixture.__spec__ = SimpleNamespace(loader=object())
try:
    exec(compile(ast.Module(body=tree.body[receipt:-1], type_ignores=[]), script, 'exec'), namespace)
except AssertionError:
    assert contaminate == 'True', 'valid historical sources rejected'
    assert not Path(output + '.provenance.json').exists()
else:
    assert contaminate == 'False', 'current-tree fixture passed provenance'
    receipt = json.loads(Path(output + '.provenance.json').read_text())
    assert receipt['commit'] == 'synthetic-historical-commit'
    assert receipt['loaded_modules'] == ['combat', 'tests.provenance_fixture']
    assert receipt['git_blobs_read'] == oids
print('historical provenance gate verified')
'''
    result = subprocess.run(
        [sys.executable, '-B', '-c', probe, str(script),
         str(tmp_path / 'capture.json'), str(contaminate_fixture)],
        capture_output=True, text=True, timeout=15, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == 'historical provenance gate verified'
