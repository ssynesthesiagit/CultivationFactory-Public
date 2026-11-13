"""Six mandatory stock BASE/candidate captures; no opt-in gate or rebaseline.

The stock base is this branch's fork point on main (tests/replay_base.py), so a
later reviewed mainline AI change is not reported as this branch's regression.
"""
from pathlib import Path

import pytest

from tests import test_wall_height_replays as replay
from tests.test_save_reload_equivalence import STOCK_SEEDS

EVIDENCE = Path('/var/tmp/auto-audit/fix/MGR-T5-mapheights-evidence/replays')


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_six_stock_map_height_comparisons(tmp_path, monkeypatch, seed):
    # The base is resolved by the shared replay-base rule inside the captured
    # child; the spool intentionally does not forward arbitrary caller
    # environment, so no per-lane base is configured here.
    monkeypatch.setenv('WALLHEIGHT_REPLAY_EVIDENCE', str(EVIDENCE))
    replay.test_six_full_stock_ai_captures_stay_identical(tmp_path, seed)
