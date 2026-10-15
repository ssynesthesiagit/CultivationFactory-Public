"""Run the unchanged six stock guards with this lane's exact base and evidence.

The heavyq bridge forwards a restricted environment. Pin inside the test and
redirect the stock module's artifact directory so peer evidence stays untouched.
"""
from pathlib import Path

import pytest
from tests import test_a2_glass_stock as stock

BASE = '8bd818c78df011c2b67145d8e33975468c3e6a75'
EVIDENCE = Path('/var/tmp/auto-audit/fix/MGR-T14-sol-reserve-banner-cultivator-raise-the-standard-1-evidence/stock')


@pytest.mark.parametrize('seed', stock.STOCK_SEEDS)
def test_six_exact_base_stock_replays(tmp_path, monkeypatch, seed):
    from tests import replay_base
    monkeypatch.setenv('CF_REPLAY_BASE', BASE)
    monkeypatch.setattr(replay_base, '_session_base', None)
    monkeypatch.setattr(stock, 'EVIDENCE', EVIDENCE)
    stock.test_six_stock_captures_equal_main(tmp_path, seed)
