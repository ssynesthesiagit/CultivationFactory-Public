"""Opt-in verification of scoped base/head AI captures, without launching a browser.

Set AUTO110_AI_REPLAY_EVIDENCE to a directory with base/head captures produced by
the retained AUTO110 capture harness. Captures include legal choices, committed
events, rolls and final state; each arm must verify and mechanically replay first.
Focusing Defense owners may differ only in their per-Dodge eligibility record.
Private capture data stays outside the repository.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path

import pytest
from tests.replay_assertions import assert_replay_equal

from tests.test_save_reload_equivalence import STOCK_SEEDS, _bytes_of

FLAG = 'dw_focusing_defense:pair_at_dodge'
NAMES = ['stock-' + seed for seed in STOCK_SEEDS] + ['focusing-defense-owner']


def _without_record(value):
    """Exclude exactly the intended owner bookkeeping change, wherever journaled."""
    if isinstance(value, dict):
        return {key: _without_record(item) for key, item in value.items() if key != FLAG}
    if isinstance(value, list):
        return [_without_record(item) for item in value]
    return value


@pytest.mark.parametrize('name', NAMES)
def test_scoped_ai_replay_evidence(name):
    evidence = os.environ.get('AUTO110_AI_REPLAY_EVIDENCE')
    if not evidence:
        pytest.skip('opt in with AUTO110_AI_REPLAY_EVIDENCE; captures remain outside the repository')
    captures = []
    for arm in ('base', 'head'):
        root = Path(evidence) / arm
        raw = gzip.decompress((root / (name + '.json.gz')).read_bytes())
        summary = json.loads((root / (name + '.summary.json')).read_text())
        assert summary['sha256'] == hashlib.sha256(raw).hexdigest()
        assert summary['verify'] == summary['replay'] == 'PASS'
        capture = json.loads(raw)
        assert capture['steps'] > 10 and capture['choices'] and capture['events']
        for field, digest in summary['digests'].items():
            assert hashlib.sha256(_bytes_of(capture[field]).encode()).hexdigest() == digest
        captures.append(raw)
    if name.startswith('stock-'):
        assert_replay_equal(captures[0], captures[1], name)
    else:
        assert captures[0] != captures[1], 'owner capture must exercise changed bookkeeping'
        assert_replay_equal(_bytes_of(_without_record(json.loads(captures[0]))), _bytes_of(
            _without_record(json.loads(captures[1]))), 'owner differs beyond eligibility bookkeeping')
