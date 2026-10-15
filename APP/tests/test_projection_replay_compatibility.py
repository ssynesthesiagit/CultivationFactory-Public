"""Opt-in complete stock AI fights and ordinary table base/head byte equality.

SOL68_REPLAY_BASE=65cf60c9 enables subprocess comparisons with the retained
pre-LUNA68 commit. Set it to 01fa8dbf to check the Sol finish alone.
All event/decision/state/roll fields are compared, with no normalization.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

APP = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not os.environ.get('SOL68_REPLAY_BASE'), reason='requires explicit retained Git base')
@pytest.mark.parametrize('scenario', ['stock-1', 'stock-2', 'stock-3', 'normal-table'])
def test_unaffected_ai_events_and_decisions_remain_byte_identical(tmp_path, scenario):
    def run(label, revision=None):
        command = [sys.executable, '-m', 'tests.projection_replay_capture', str(tmp_path / label), scenario]
        if revision:
            command.append(revision)
        return json.loads(subprocess.check_output(command, cwd=APP))

    before = run('base', os.environ['SOL68_REPLAY_BASE'])
    after = run('head')
    for kind in ('events', 'decisions', 'controller_journal', 'rolls', 'state'):
        old = json.dumps(before[kind], sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        new = json.dumps(after[kind], sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        assert old == new, (scenario, kind, hashlib.sha256(old).hexdigest(), hashlib.sha256(new).hexdigest())
        print(f'{scenario} {kind}: count={len(before[kind])} bytes={len(old)} sha256={hashlib.sha256(old).hexdigest()}')
