"""Opt-in complete stock AI fights and ordinary table base/head byte equality.

Set SOL68_REPLAY_BASELINE_APP to the APP directory of the retained base
(e.g. 65cf60c9 for pre-LUNA68 or 01fa8dbf for the Sol finish).
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
BASELINE = os.environ.get('SOL68_REPLAY_BASELINE_APP')


@pytest.mark.skipif(not BASELINE, reason='set SOL68_REPLAY_BASELINE_APP to a separate baseline APP')
@pytest.mark.parametrize('scenario', ['stock-1', 'stock-2', 'stock-3', 'normal-table'])
def test_unaffected_ai_events_and_decisions_remain_byte_identical(tmp_path, scenario):
    base_app = Path(BASELINE).resolve()
    assert base_app != APP and (base_app / 'combat' / 'gate4_runner.py').is_file()
    driver = APP / 'tests' / 'projection_replay_capture.py'

    def run(label, root):
        # Use the same capture driver, even for revisions older than this
        # test, without adding that driver's checkout to the import path.
        command = [sys.executable, '-P', str(driver), str(tmp_path / label), scenario]
        env = {**os.environ, 'PYTHONPATH': str(root), 'PYTHONDONTWRITEBYTECODE': '1', 'CF_EMBED_MENU': '0'}
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=900)
        assert result.returncode == 0, result.stderr[-3000:]
        return json.loads(result.stdout)

    before = run('base', base_app)
    after = run('head', APP)
    for kind in ('events', 'decisions', 'controller_journal', 'rolls', 'state'):
        old = json.dumps(before[kind], sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        new = json.dumps(after[kind], sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        assert old == new, (scenario, kind, hashlib.sha256(old).hexdigest(), hashlib.sha256(new).hexdigest())
        print(f'{scenario} {kind}: count={len(before[kind])} bytes={len(old)} sha256={hashlib.sha256(old).hexdigest()}')
