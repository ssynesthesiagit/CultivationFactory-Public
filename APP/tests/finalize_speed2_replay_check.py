"""The six stock captures are unchanged from this branch's fork point on main.

The base is the merge-base with main resolved by tests/replay_base.py, so a
later reviewed mainline AI change is not reported as this lane's regression.
"""

import pytest

from tests import test_wall_height_replays as stock


@pytest.mark.parametrize("seed", stock.STOCK_SEEDS)
def test_six_stock_captures_match_finalize_base(tmp_path, monkeypatch, seed):
    monkeypatch.setenv("WALLHEIGHT_REPLAY_EVIDENCE", str(tmp_path / "evidence"))
    stock.test_six_full_stock_ai_captures_stay_identical(tmp_path, seed)
