"""Six exact-base stock captures for the reused generic journey hooks."""
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS
from tests.test_a2_glass_stock import test_six_stock_captures_equal_main as capture

@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_exact_base_stock(tmp_path,monkeypatch,seed):
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    from tests import test_a2_glass_stock
    from pathlib import Path
    monkeypatch.setattr(test_a2_glass_stock,'EVIDENCE',Path('/var/tmp/auto-audit/fix/MGR-T14-ling-seam-patterns-placement-2-evidence/stock'))
    capture(tmp_path,seed)
