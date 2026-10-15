"""Six exact-owner-base stock replays for general host integrations."""
import pytest
from tests.test_a2_glass_stock import test_six_stock_captures_equal_main

@pytest.fixture(autouse=True)
def pin(monkeypatch):
    monkeypatch.setenv('CF_REPLAY_BASE','224183aa0820a83cee6069328add3c2ad954adfa')
    monkeypatch.setenv('CF_STOCK_EVIDENCE','/var/tmp/auto-audit/fix/MGR-T14-ling-seam-culinary-batches-3-evidence/stock')
