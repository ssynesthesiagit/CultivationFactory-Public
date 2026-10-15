"""Six exact-base stock replay guards for the shared object response seam."""
import pytest
from tests import test_a2_glass_stock as stock


@pytest.mark.parametrize('seed',stock.STOCK_SEEDS)
def test_mason_stock_identical(tmp_path,monkeypatch,seed):
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setattr(stock,'EVIDENCE',tmp_path/'captures')
    stock.test_six_stock_captures_equal_main(tmp_path,seed)
