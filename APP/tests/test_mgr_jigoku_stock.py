"""Six reproducible stock guards using the public branch baseline."""
import pytest
from tests import test_a2_glass_stock as stock
from tests.test_save_reload_equivalence import STOCK_SEEDS

@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_exact_base_stock(tmp_path,monkeypatch,seed):
    monkeypatch.setenv('CF_STOCK_EVIDENCE',str(tmp_path/'stock'))
    stock.test_six_stock_captures_equal_main(tmp_path,seed)
