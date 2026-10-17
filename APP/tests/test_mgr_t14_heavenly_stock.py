"""Heavenly merge's six replay guards, separate from focused public-CI tests.

Use the shared current-main base and evidence rules. Historical base pins and
the removed stock.EVIDENCE attribute cannot validate a newly merged branch.
"""
import pytest

from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_exact_base_stock_replays(tmp_path, seed):
    from tests import test_a2_glass_stock as stock
    stock.test_six_stock_captures_equal_main(tmp_path, seed)
