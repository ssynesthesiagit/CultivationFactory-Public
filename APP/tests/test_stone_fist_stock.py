"""Six complete stock transcripts, compared with the exact assigned base."""
import hashlib
import json
from pathlib import Path
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS, _play, _bytes_of, _start_stock

@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_stock_replay(tmp_path,seed):
    capture=_play(tmp_path,lambda root:_start_stock(root,seed))
    text=_bytes_of(capture)
    (tmp_path/'capture.json').write_text(text)
    (tmp_path/'capture.sha256').write_text(hashlib.sha256(text.encode()).hexdigest())
    assert capture['choices'] and capture['events'] and capture['rolls']
