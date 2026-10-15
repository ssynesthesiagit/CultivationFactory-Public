"""The six stock AI captures stay identical to this branch's fork point on main."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.replay_base import replay_base_or_skip
from tests.test_save_reload_equivalence import STOCK_SEEDS, _bytes_of, _first_difference

APP = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_six_stock_ai_captures_match_reviewed_parent(tmp_path, seed):
    base = replay_base_or_skip()
    captures = []
    for arm in ('base', 'head'):
        command = [sys.executable, '-m', 'tests.wall_height_stock_capture', str(tmp_path / arm), seed]
        if arm == 'base':
            command.append(base)
        result = subprocess.run(command, cwd=APP, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                                text=True, capture_output=True, timeout=600)
        assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-4000:]
        captures.append(json.loads(result.stdout.splitlines()[-1]))
    before, after = captures
    encoded = [_bytes_of(c).encode() for c in captures]
    evidence = {'seed': seed, 'base': base, 'identical': encoded[0] == encoded[1],
                'base_sha256': hashlib.sha256(encoded[0]).hexdigest(),
                'head_sha256': hashlib.sha256(encoded[1]).hexdigest(),
                'steps': after['steps'], 'events': sum(map(len, after['events'])),
                'terminal': after['state']['terminal_result'] is not None,
                'first_difference': _first_difference(before, after)}
    (tmp_path / 'comparison.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, sort_keys=True))
    assert before['state']['terminal_result'] and after['state']['terminal_result']
    assert encoded[0] == encoded[1], evidence
