"""Run the six established stock comparisons against this lane's exact base."""
import pytest
from tests.test_a2_glass_stock import test_six_stock_captures_equal_main as _stock
from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize("seed", STOCK_SEEDS)
def test_stock_against_assigned_base(tmp_path, monkeypatch, seed):
    from tests import test_a2_glass_stock as stock_module
    monkeypatch.setenv("CF_REPLAY_BASE", "8bd818c78df011c2b67145d8e33975468c3e6a75")
    monkeypatch.setattr(stock_module, "EVIDENCE", tmp_path / "compact-stock")
    _stock(tmp_path, seed)
