"""Compatibility entry point for the six canonical current-base stock guards."""
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_six_exact_base_stock_replays(tmp_path, seed):
    import tests.test_a2_glass_stock as stock
    stock.test_six_stock_captures_equal_main(tmp_path, seed)
