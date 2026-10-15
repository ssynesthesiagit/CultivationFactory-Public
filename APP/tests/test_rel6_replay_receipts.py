"""REL6 stock comparison allowing only the reviewed voluntary-movement receipt.

Misc Subpaths 3 journals forced=False for walking and self teleports. The strict
historical byte check reports this addition; every other byte must stay equal.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_save_reload_equivalence import STOCK_SEEDS, _bytes_of, _first_difference

APP = Path(__file__).resolve().parents[1]
EVIDENCE = Path('/var/tmp/auto-audit/fix/REL6-evidence/replay-receipts')


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_stock_changes_only_add_voluntary_movement_receipts(tmp_path, seed):
    captures = []
    for arm in ('base', 'head'):
        command = [sys.executable, '-m', 'tests.wall_height_stock_capture', str(tmp_path / arm), seed]
        if arm == 'base':
            command.append('1de73b36')
        result = subprocess.run(command, cwd=APP, text=True, capture_output=True, timeout=600)
        assert result.returncode == 0, result.stderr[-4000:]
        captures.append(json.loads(result.stdout.splitlines()[-1]))
    before, after = captures
    hashes = [hashlib.sha256(_bytes_of(c).encode()).hexdigest() for c in captures]
    receipts = []
    assert len(before['events']) == len(after['events'])
    for commit_index, (left, right) in enumerate(zip(before['events'], after['events'])):
        assert len(left) == len(right)
        for event_index, (base_event, head_event) in enumerate(zip(left, right)):
            old, new = base_event.get('payload') or {}, head_event.get('payload') or {}
            if 'forced' not in old and 'forced' in new:
                assert head_event['event_type'] == 'MOVEMENT_COMMITTED'
                assert new['forced'] is False
                receipts.append(f'/events/{commit_index}/{event_index}/payload/forced')
                del new['forced']
    difference = _first_difference(before, after)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / (seed + '.json')).write_text(json.dumps({
        'seed': seed, 'base': '1de73b36', 'base_sha256': hashes[0], 'head_sha256': hashes[1],
        'added_voluntary_movement_receipts': receipts, 'other_difference': difference,
        'steps': after['steps'], 'terminal': after['state']['terminal_result'] is not None,
    }, indent=2) + '\n')
    assert before['state']['terminal_result'] and after['state']['terminal_result']
    assert receipts
    assert _bytes_of(before) == _bytes_of(after), difference
