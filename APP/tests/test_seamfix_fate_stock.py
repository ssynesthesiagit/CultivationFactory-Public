"""Run the six official stock guards with isolated evidence and an exact base."""
from pathlib import Path
import pytest
from tests import test_a2_glass_stock as stock
from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_official_stock_guard(tmp_path, monkeypatch, seed):
    monkeypatch.setenv('CF_REPLAY_BASE', '8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setattr(stock, 'EVIDENCE', Path('/var/tmp/auto-audit/fix/SEAMFIX-trad-fate-nudge-1-evidence/stock'))
    stock.test_six_stock_captures_equal_main(tmp_path, seed)
