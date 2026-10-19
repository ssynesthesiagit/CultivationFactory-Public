"""Opt-in local stock evidence; normal public tests need no Git history."""
import os
import pytest


@pytest.mark.parametrize("seed_index", range(6))
def test_exact_base_stock(tmp_path, monkeypatch, seed_index):
    if os.environ.get("CF_RUN_STOCK_HISTORY_EVIDENCE") != "1":
        pytest.skip("set CF_RUN_STOCK_HISTORY_EVIDENCE=1 for local history-based replay evidence")
    # Import history-dependent capture tooling only for an explicitly requested
    # local evidence run; public CI can collect and skip this test safely.
    from tests import test_a2_glass_stock as stock
    from tests.test_save_reload_equivalence import STOCK_SEEDS

    monkeypatch.setenv("CF_STOCK_EVIDENCE", str(tmp_path / "stock"))
    stock.test_six_stock_captures_equal_main(tmp_path, STOCK_SEEDS[seed_index])
