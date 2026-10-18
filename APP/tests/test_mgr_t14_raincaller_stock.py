"""Six stock captures pinned to this lane's exact requested base."""
from pathlib import Path
import pytest
from tests import test_a2_glass_stock as stock
from tests.test_save_reload_equivalence import STOCK_SEEDS

# Keep evidence inside pytest's task-local scratch tree for public CI.

@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_exact_base_stock(tmp_path,monkeypatch,seed):
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setenv('CF_STOCK_EVIDENCE_DIR',str(tmp_path/'evidence'))
    stock.test_six_stock_captures_equal_main(tmp_path,seed)
