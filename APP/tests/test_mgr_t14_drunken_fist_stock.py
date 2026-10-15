"""Exact-base six stock native captures, including committed commands and rolls."""
import os
from pathlib import Path
import pytest
from tests.test_a2_glass_stock import test_six_stock_captures_equal_main as capture
from tests.test_save_reload_equivalence import STOCK_SEEDS

@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_exact_base_stock(tmp_path,monkeypatch,seed):
    from tests import test_a2_glass_stock as stock
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setattr(stock,'EVIDENCE',Path('/var/tmp/auto-audit/fix/MGR-T14-ling-reserve-drunken-fist-swaying-step-1-evidence/stock'))
    capture(tmp_path,seed)
