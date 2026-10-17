"""Exact-base six stock replays for the default-inert shared seam integration."""
from pathlib import Path
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS
from tests import test_a2_glass_stock as stock


@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_exact_base_stock(tmp_path,monkeypatch,seed):
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setattr(stock,'EVIDENCE',Path('/var/tmp/auto-audit/fix/MGR-T14-sol-reserve-mantis-style-mantis-hooks-1-evidence/stock'))
    stock.test_six_stock_captures_equal_main(tmp_path,seed)
