"""Six stock comparisons against the main merged for A2RINS1F5.

Keep this entry point: the existing detached stock job selects this file.
"""
import pytest

from tests import test_a2_glass_stock as stock


@pytest.mark.parametrize('seed', stock.STOCK_SEEDS)
def test_six_stock_captures_match_f4_main(tmp_path, monkeypatch, seed):
    monkeypatch.setenv('CF_REPLAY_BASE', '6536584b057d4c8e54a31f60350a62cc45f0e378')
    monkeypatch.setenv('CF_STOCK_EVIDENCE', '/var/tmp/auto-audit/fix/A2RINS1F5-evidence/stock')
    stock.test_six_stock_captures_equal_main(tmp_path, seed)
