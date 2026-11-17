"""Six stock captures against this branch's fork point on main.

The base is the merge-base with main resolved by tests/replay_base.py, so
mainline changes the branch merged in are not blamed on it.  Release checks
that must compare one exact commit pin it with CF_REPLAY_BASE.
"""
import os

import pytest

from tests import test_wall_height_replays as stock


@pytest.mark.parametrize("seed", stock.STOCK_SEEDS)
def test_stock_ai_flight_captures_match_base(tmp_path, monkeypatch, seed):
    monkeypatch.setenv("WALLHEIGHT_REPLAY_EVIDENCE", os.environ.get("AIFLIGHT_REPLAY_EVIDENCE", "/var/tmp/auto-audit/fix/REL6-evidence/replays"))
    stock.test_six_full_stock_ai_captures_stay_identical(tmp_path, seed)
