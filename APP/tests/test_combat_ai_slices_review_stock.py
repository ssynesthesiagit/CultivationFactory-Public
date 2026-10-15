"""Opt-in stock guard; keep this lane's evidence out of other lanes' folders."""
from pathlib import Path
import pytest
from tests.combat_ai_slices_options import opt_in_options
from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_review_stock_captures(tmp_path, monkeypatch, request, seed):
    opts = opt_in_options(request.config)
    base = opts.get('combatai2f_stock_base')
    if not base:
        pytest.skip('opt-in stock capture through heavyq with an exact base')
    from tests import test_a2_glass_stock as stock
    monkeypatch.delenv('CF_COMBAT_AI_SLICES_1_2', raising=False)
    monkeypatch.setenv('CF_REPLAY_BASE', base)
    monkeypatch.setattr(stock, 'EVIDENCE', Path(opts['combatai2f_stock_evidence']))
    stock.test_six_stock_captures_equal_main(tmp_path, seed)
