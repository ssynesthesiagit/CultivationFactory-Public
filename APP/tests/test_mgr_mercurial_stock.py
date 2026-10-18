"""The six stock captures, explicitly pinned to this lane's exact base."""
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS
from tests import test_a2_glass_stock as stock


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_exact_base_stock(tmp_path, monkeypatch, seed):
    monkeypatch.setenv('CF_REPLAY_BASE', '8bd818c78df011c2b67145d8e33975468c3e6a75')
    # The stock helper binds EVIDENCE at import time; patch that public output
    # path directly so no run can write another lane's shared default folder.
    monkeypatch.setattr(stock, 'EVIDENCE', tmp_path / 'comparisons')
    stock.test_six_stock_captures_equal_main(tmp_path, seed)
