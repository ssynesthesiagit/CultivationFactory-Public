"""The six stock guards pinned to this lane's exact supplied base.

The queue's restricted environment transport does not carry CF_REPLAY_BASE.
Invoke the unchanged stock guard with a test-local explicit pin instead.
"""
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS
from tests.test_a2_glass_stock import test_six_stock_captures_equal_main as capture


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_exact_base_stock(tmp_path, monkeypatch, seed):
    monkeypatch.setenv('CF_REPLAY_BASE', '8bd818c78df011c2b67145d8e33975468c3e6a75')
    import tests.test_a2_glass_stock as stock
    monkeypatch.setattr(stock, 'EVIDENCE', tmp_path / 'compact-stock')
    capture(tmp_path, seed)
