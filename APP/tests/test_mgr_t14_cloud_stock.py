"""Six exact-base stock controls for the opt-in movement contracts."""
import os
from pathlib import Path
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS
from tests.test_a2_glass_stock import test_six_stock_captures_equal_main as capture
import tests.test_a2_glass_stock as stock


@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_exact_base_stock(tmp_path,monkeypatch,seed):
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    evidence=Path('/var/tmp/auto-audit/fix/MGR-T14-ling-reserve-cloud-walker-light-as-a-feather-1-evidence/stock')
    monkeypatch.setattr(stock,'EVIDENCE',evidence)
    capture(tmp_path,seed)
