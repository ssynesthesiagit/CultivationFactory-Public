"""Six stock AI captures of the Qi sub-paths, base and head, against the reviewed replay base."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from tests.replay_assertions import assert_replay_equal
from tests.replay_base import replay_base_or_skip
from tests.test_save_reload_equivalence import STOCK_SEEDS, _bytes_of, _first_difference

APP = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_qi_subpaths_stock_identity(tmp_path, seed):
    base = replay_base_or_skip()
    captures = []
    for arm in ('base', 'head'):
        command = [sys.executable, '-m', 'tests.wall_height_stock_capture', str(tmp_path / arm), seed]
        if arm == 'base':
            command.append(base)
        run = subprocess.run(command, cwd=APP, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                             text=True, capture_output=True, timeout=600)
        assert run.returncode == 0, run.stdout[-1500:] + run.stderr[-4000:]
        captures.append(json.loads(run.stdout.splitlines()[-1]))
    encoded = [_bytes_of(c).encode() for c in captures]
    result = {'seed': seed, 'base': base, 'identical': encoded[0] == encoded[1],
              'base_sha256': hashlib.sha256(encoded[0]).hexdigest(),
              'head_sha256': hashlib.sha256(encoded[1]).hexdigest(),
              'steps': captures[1]['steps'], 'first_difference': _first_difference(*captures)}
    (tmp_path / (seed + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    for label, raw in zip(['base', 'head'], encoded):
        with gzip.open(tmp_path / (seed + '.' + label + '.json.gz'), 'wb') as f:
            f.write(raw)
    assert captures[0]['state']['terminal_result'] and captures[1]['state']['terminal_result']
    assert_replay_equal(encoded[0], encoded[1], result)
