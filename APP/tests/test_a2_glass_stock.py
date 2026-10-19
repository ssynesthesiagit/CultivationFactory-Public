"""Six full stock captures against this branch's fork point on main."""
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


def _without_roll_explanations(value):
    """Ignore only additive d20 provenance; roll modes and all replay state remain exact."""
    if isinstance(value, dict):
        return {key: _without_roll_explanations(item) for key, item in value.items()
                if key != 'mode_sources'}
    if isinstance(value, list):
        return [_without_roll_explanations(item) for item in value]
    return value


def test_stock_projection_excludes_only_roll_explanation_metadata():
    sample = {'mode': 'DISADVANTAGE', 'total': 4, 'mode_sources': [{'effect': 'Prone'}],
              'nested': [{'mode': 'NORMAL', 'mode_sources': [{'effect': 'Fog'}], 'total': 12}]}
    assert _without_roll_explanations(sample) == {
        'mode': 'DISADVANTAGE', 'total': 4,
        'nested': [{'mode': 'NORMAL', 'total': 12}],
    }


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_six_stock_captures_equal_main(tmp_path, seed):
    base = replay_base_or_skip()
    captures = []
    # Retain main's explicit evidence override and per-run default, plus the
    # lane's historical ROOT/TMPDIR overrides for isolated queued captures.
    default_evidence = Path(os.environ['TMPDIR']) / 'stock' if os.environ.get('TMPDIR') else tmp_path.parent / 'stock'
    evidence = Path(os.environ.get('CF_STOCK_EVIDENCE') or os.environ.get('CF_STOCK_EVIDENCE_DIR')
                    or os.environ.get('CF_STOCK_EVIDENCE_ROOT') or default_evidence)
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
    # Roll-reason payloads are intentionally additive UI metadata. Preserve an
    # exact replay guard for every roll, choice and state field while requiring
    # this focused feature's tests to verify the omitted receipts separately.
    projected = [_without_roll_explanations(c) for c in captures]
    projected_encoded = [_bytes_of(c).encode() for c in projected]
    comparison = {'seed': seed, 'base': base, 'identical': projected_encoded[0] == projected_encoded[1],
                  'base_sha256': hashlib.sha256(projected_encoded[0]).hexdigest(),
                  'head_sha256': hashlib.sha256(projected_encoded[1]).hexdigest(),
                  'first_difference': _first_difference(projected[0], projected[1]),
                  'ignored_field': 'mode_sources (validated by test_rollreason1.py)'}
    (evidence / f'{seed}-comparison.json').write_text(json.dumps(comparison, indent=2) + '\n')
    assert before['state']['terminal_result'] and after['state']['terminal_result']
    assert_replay_equal(projected_encoded[0], projected_encoded[1], comparison)
