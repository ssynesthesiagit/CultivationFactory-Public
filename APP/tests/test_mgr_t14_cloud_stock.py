"""Six exact-base stock controls for the opt-in movement contracts.

The base is resolved by tests/replay_base.py (CF_REPLAY_BASE pin, else the
mainline merge-base), and evidence goes to CF_STOCK_EVIDENCE when set, else the
per-test temporary directory. No historical commit is pinned here, so the
comparison runs on public checkouts.
"""
import os
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS
from tests.test_a2_glass_stock import test_six_stock_captures_equal_main as capture


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_exact_base_stock(tmp_path, monkeypatch, seed):
    if not os.environ.get('CF_STOCK_EVIDENCE'):
        monkeypatch.setenv('CF_STOCK_EVIDENCE', str(tmp_path / 'stock'))
    capture(tmp_path, seed)
