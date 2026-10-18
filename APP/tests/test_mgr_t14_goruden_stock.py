"""Six exact-base stock controls after integrating native continuation seams."""
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS
from tests.test_wall_height_replays import test_six_full_stock_ai_captures_stay_identical as compare


@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_goruden_shared_contract_stock_replay(tmp_path,monkeypatch,seed):
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setenv('WALLHEIGHT_REPLAY_EVIDENCE',str(tmp_path/'comparison'))
    compare(tmp_path,seed)
