"""Stock capture replays for the A2WATER lane, run the same way anywhere.

The six stock seeds are played through the persistent session (the table's own
save/reopen path) and each capture is checked three ways:

* it is a real fight -- choices, events and rolls are all present;
* it replays identically -- the same seed played twice produces the same bytes,
  so this test fails on any nondeterminism it would otherwise hide;
* it matches the recorded baseline -- when CF_WATER_CAPTURE_BASELINE names a
  directory of baseline captures, every seed is compared byte for byte and the
  first differing JSON path is reported.

Captures are disposable and stay under tmp_path. Exporting them as retained lane
evidence is an explicit opt-in via CF_WATER_CAPTURE_EXPORT=<dir>, so an ordinary
test run on any checkout can neither fail for a missing directory nor overwrite
someone else's evidence.
"""
import json
import os
from pathlib import Path

import pytest
from tests.replay_assertions import assert_replay_equal

from tests.test_save_reload_equivalence import STOCK_SEEDS, _play, _bytes_of, _start_stock, _first_difference


def _export_dir():
    return os.environ.get('CF_WATER_CAPTURE_EXPORT')


def _baseline_dir():
    return os.environ.get('CF_WATER_CAPTURE_BASELINE')


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_stock_capture_is_a_real_and_deterministic_fight(tmp_path, seed):
    capture = _play(tmp_path, lambda path: _start_stock(path, seed))
    assert capture['choices'] and capture['events'] and capture['rolls']
    payload = _bytes_of(capture)
    (tmp_path / f'stock-{seed}.json').write_text(payload, encoding='utf-8')

    replay_dir = tmp_path / 'again'
    replay_dir.mkdir()
    again = _bytes_of(_play(replay_dir, lambda path: _start_stock(path, seed)))
    assert_replay_equal(again, payload, f'{seed} replayed differently on a second run')

    export = _export_dir()
    if export:
        target = Path(export)
        target.mkdir(parents=True, exist_ok=True)
        (target / f'stock-head-{seed}.json').write_text(payload, encoding='utf-8')

    baseline = _baseline_dir()
    if baseline:
        reference = Path(baseline) / f'stock-head-{seed}.json'
        assert reference.exists(), f'no recorded baseline for {seed} in {baseline}'
        recorded = json.loads(reference.read_text(encoding='utf-8'))
        difference = _first_difference(recorded, capture)
        assert difference is None, f'{seed} differs from the recorded baseline: {difference}'
        assert_replay_equal(_bytes_of(recorded), payload, seed)
