"""Six full stock captures against this branch's fork point on main."""
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
EVIDENCE = Path(os.environ.get('CF_STOCK_EVIDENCE_DIR', '/var/tmp/auto-audit/fix/A2GLASS-evidence/stock'))


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_six_stock_captures_equal_main(tmp_path, seed):
    base = replay_base_or_skip()
    captures = []
    evidence = Path(os.environ['CF_STOCK_EVIDENCE']) if os.environ.get('CF_STOCK_EVIDENCE') else tmp_path / 'stock-evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    for arm in ('base', 'head'):
        command = [sys.executable, '-m', 'tests.wall_height_stock_capture', str(tmp_path / arm), seed]
        if arm == 'base':
            command.append(base)
        result = subprocess.run(command, cwd=APP, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                                text=True, capture_output=True, timeout=600)
        assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-4000:]
        capture = json.loads(result.stdout.splitlines()[-1])
        encoded = _bytes_of(capture).encode()
        (evidence / f'{seed}-{arm}.json').write_bytes(encoded)
        captures.append(capture)
    before, after = captures
    encoded = [_bytes_of(c).encode() for c in captures]
    comparison = {'seed': seed, 'base': base, 'identical': encoded[0] == encoded[1],
                  'base_sha256': hashlib.sha256(encoded[0]).hexdigest(),
                  'head_sha256': hashlib.sha256(encoded[1]).hexdigest(),
                  'first_difference': _first_difference(before, after)}
    (evidence / f'{seed}-comparison.json').write_text(json.dumps(comparison, indent=2) + '\n')
    assert before['state']['terminal_result'] and after['state']['terminal_result']
    assert encoded[0] == encoded[1], comparison
