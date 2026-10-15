"""Six exact-base stock comparisons for the resumed A2R04 branch.

CF_REPLAY_BASE pins the historical lane base; this file runs locally through
the stock replay route. The imported tests use the normal stock capture code.
"""
from pathlib import Path

import pytest

from tests import test_a2_glass_stock as stock
from tests.test_a2_glass_stock import test_six_stock_captures_equal_main


@pytest.fixture(autouse=True)
def exact_lane_base(monkeypatch):
    monkeypatch.setenv("CF_REPLAY_BASE", "eb79cee620f27f2ca46a83f824394b1e625a0560")
    monkeypatch.setattr(stock, "EVIDENCE", Path(
        "/var/tmp/auto-audit/fix/MGR-T14-sol-resume-smoke-sound-contracts-1230-1-evidence/stock"))
