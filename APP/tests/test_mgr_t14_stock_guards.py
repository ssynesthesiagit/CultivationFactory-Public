"""Six exact-assigned-base stock replays; captures stay in this lane's evidence."""
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS
from tests import test_a2_glass_stock as capture

@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_exact_base_stock(tmp_path,monkeypatch,seed):
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    from pathlib import Path
    monkeypatch.setattr(capture,'EVIDENCE',Path('/var/tmp/auto-audit/fix/MGR-T14-ling-seam-scoped-information-2-evidence/legacy-stock-guards'))
    capture.test_six_stock_captures_equal_main(tmp_path,seed)
