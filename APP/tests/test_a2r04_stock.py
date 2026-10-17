"""Six exact-base stock comparisons for the resumed A2R04 branch.

CF_REPLAY_BASE pins the historical lane base; this file runs locally through
the stock replay route. The imported tests use the normal stock capture code.
"""
import pytest

from tests.test_a2_glass_stock import test_six_stock_captures_equal_main


@pytest.fixture(autouse=True)
def exact_lane_base(monkeypatch):
    # test_a2_glass_stock reads its evidence root from CF_STOCK_EVIDENCE (no module attribute to patch).
    monkeypatch.setenv("CF_REPLAY_BASE", "eb79cee620f27f2ca46a83f824394b1e625a0560")
    monkeypatch.setenv("CF_STOCK_EVIDENCE", "/var/tmp/auto-audit/fix/A2R04F11-evidence/stock")
