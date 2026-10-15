"""Exact-base unchanged stock controls for the integrated shared Asset contract."""
from pathlib import Path
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_stock_exact_base(tmp_path,monkeypatch,seed):
    from tests import test_a2_glass_stock as stock
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    evidence=Path('/var/tmp/auto-audit/fix/MGR-T14-ling-reserve-iron-cloth-cultivator-silken-whip-1-evidence/stock')
    monkeypatch.setattr(stock,'EVIDENCE',evidence)
    stock.test_six_stock_captures_equal_main(tmp_path,seed)
