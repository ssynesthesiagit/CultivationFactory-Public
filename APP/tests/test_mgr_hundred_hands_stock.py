"""Six exact-base stock controls for the opt-in reaction refresh contract."""
import pytest
from tests import test_wall_height_replays as stock


@pytest.mark.parametrize('seed', stock.STOCK_SEEDS)
def test_exact_base_stock_replay(tmp_path, monkeypatch, seed):
    monkeypatch.setenv('CF_REPLAY_BASE', '8bd818c78df011c2b67145d8e33975468c3e6a75')
    stock.test_six_full_stock_ai_captures_stay_identical(tmp_path, seed)
