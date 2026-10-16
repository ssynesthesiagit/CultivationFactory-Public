"""Six full stock AI base/head captures; task-owned resources only.

The base arm is the merge-base of this checkout with the first
of ``main``/``origin/main``/``github/main``/``swarmlord-main``
that resolves here -- or the first parent of the checkout when
the checkout *is* that ref, so the comparison is never the
checkout against itself.  See tests/replay_base.py.  A release
check that needs one exact commit pins it with CF_REPLAY_BASE
instead of editing this file.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.replay_base import replay_base_or_skip
from tests.test_save_reload_equivalence import STOCK_SEEDS, _bytes_of, _first_difference

APP = Path(__file__).resolve().parents[1]


def test_no_revision_entry_point_consumes_uncommitted_worktree_module(tmp_path, monkeypatch):
    """The CLI's omitted-revision path gives the replay its checkout sources."""
    from tests import wall_height_stock_capture as capture
    from tests import test_save_reload_equivalence as stock

    candidate_app = tmp_path / 'APP'
    package_name = f'wallheight_candidate_probe_{tmp_path.name.replace("-", "_")}'
    package = candidate_app / package_name
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('')
    module = package / 'uncommitted.py'
    module.write_text("MARKER = 'working-tree-change'\n")

    monkeypatch.setattr(capture, 'APP', candidate_app)
    # capture.main() reassigns stock.ROOT; register it so teardown restores the real root for later replays.
    monkeypatch.setattr(stock, 'ROOT', stock.ROOT)
    consumed = []

    def replay_with_selected_sources(_fight_dir, _start):
        monkeypatch.syspath_prepend(str(stock.ROOT))
        imported = importlib.import_module(f'{package_name}.uncommitted')
        consumed.append(imported.MARKER)
        return {'marker': imported.MARKER}

    monkeypatch.setattr(stock, '_play', replay_with_selected_sources)
    capture.main([str(tmp_path / 'capture'), 'synthetic-seed'])

    assert stock.ROOT == candidate_app
    assert consumed == ['working-tree-change']


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_six_full_stock_ai_captures_stay_identical(tmp_path, seed):
    base = replay_base_or_skip()
    captures = []
    for arm in ('base', 'head'):
        command = [sys.executable, '-m', 'tests.wall_height_stock_capture', str(tmp_path / arm), seed]
        if arm == 'base':
            command.append(base)
        result = subprocess.run(command, cwd=APP, env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'},
                                text=True, capture_output=True, timeout=600)
        assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-4000:]
        captures.append(json.loads(result.stdout.splitlines()[-1]))
    before, after = captures
    encoded = [_bytes_of(c).encode() for c in captures]
    evidence = {'seed':seed, 'base':base, 'identical':encoded[0] == encoded[1],
                'base_sha256':hashlib.sha256(encoded[0]).hexdigest(),
                'head_sha256':hashlib.sha256(encoded[1]).hexdigest(),
                'steps':after['steps'], 'events':sum(map(len, after['events'])),
                'terminal':after['state']['terminal_result'] is not None,
                'first_difference':_first_difference(before, after)}
    if os.environ.get('WALLHEIGHT_REPLAY_EVIDENCE'):
        directory = Path(os.environ['WALLHEIGHT_REPLAY_EVIDENCE'])
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (seed + '.json')).write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, sort_keys=True))
    assert before['state']['terminal_result'] and after['state']['terminal_result']
    assert encoded[0] == encoded[1], evidence
