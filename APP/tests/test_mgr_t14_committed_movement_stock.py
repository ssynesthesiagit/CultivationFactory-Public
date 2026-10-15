"""Six exact-base stock guards for the committed movement contracts."""
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_six_exact_base_stock_replays(tmp_path, monkeypatch, seed):
    import tests.test_a2_glass_stock as stock
    from pathlib import Path
    monkeypatch.setenv('CF_REPLAY_BASE', '8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setattr(stock, 'EVIDENCE', Path('/var/tmp/auto-audit/fix/MGR-T14-ling-seam-committed-movement-2-evidence/stock'))
    stock.test_six_stock_captures_equal_main(tmp_path, seed)

