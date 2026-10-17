"""The six unchanged stock guards, pinned to this packet's exact base."""
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_exact_base_stock(tmp_path, monkeypatch, seed):
    from tests.test_a2_glass_stock import test_six_stock_captures_equal_main
    monkeypatch.setenv('CF_REPLAY_BASE', 'e61aba146188bbc218cb0c2f0abf144c583f78f8')
    test_six_stock_captures_equal_main(tmp_path, seed)
