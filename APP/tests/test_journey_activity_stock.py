"""Six exact-base stock mechanical captures for the general journey/roll seams."""
import os
from pathlib import Path
import pytest
from tests import test_a2_glass_stock as stock
from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_exact_base_stock(tmp_path,monkeypatch,seed):
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setattr(stock,'EVIDENCE',Path('/var/tmp/auto-audit/fix/MGR-T14-ling-seam-journey-activities-2-evidence/stock'))
    stock.test_six_stock_captures_equal_main(tmp_path,seed)
