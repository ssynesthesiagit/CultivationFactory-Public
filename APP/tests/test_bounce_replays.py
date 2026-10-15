"""BOUNCEf2 whole-tree stock AI comparisons against this branch's fork point on main.

No environment opt-in: the queue bridge may discard custom environment flags.
The common harness reads all baseline APP modules/resources from one Git tree,
the merge-base with main resolved by tests/replay_base.py.
"""
import pytest

from tests import test_wall_height_replays as stock


@pytest.mark.parametrize('seed', stock.STOCK_SEEDS)
def test_six_stock_captures_match_main(tmp_path, monkeypatch, seed):
    monkeypatch.setenv('WALLHEIGHT_REPLAY_EVIDENCE', str(tmp_path / 'evidence'))
    stock.test_six_full_stock_ai_captures_stay_identical(tmp_path, seed)
