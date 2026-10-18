"""Run the six unchanged stock guards with this lane's exact base and evidence."""
from pathlib import Path
import pytest
from tests import test_a2_glass_stock as stock
from tests.test_a2_glass_stock import test_six_stock_captures_equal_main


@pytest.fixture(autouse=True)
def exact_lane_base(monkeypatch, tmp_path):
    monkeypatch.setenv('CF_REPLAY_BASE', '8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setattr(stock, 'EVIDENCE', tmp_path / 'stock-evidence')
