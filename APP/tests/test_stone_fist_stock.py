"""Six complete stock transcripts, compared with the exact assigned base."""
import hashlib
import json
from pathlib import Path
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS, _play, _bytes_of, _start_stock

# Public, compact golden expectations captured from the assigned exact base
# (df24524e8e0fcb5af7c88b63482b24471ee92958). No repository-history reads
# are needed at test time, and every replay is compared rather than merely saved.
REFERENCE_SHA256 = {
    'GATE4-AN-1': '93bdb2a5a856d1a7b5ffa0d5fefd6db357af0d1e9a7ef67181c4d22f78ae8e2c',
    'GATE4-LEE': '205c585659c53a8272e3cdec1f033b94fcd7219427dde37846b11b78d376afd6',
    'GATE4-TEST': '605839eed8bbd2b1d6827cd34b8f4f4ba1459c0a59d7947fc7a45ef2e9889e53',
    'LOCK5-A': '04ee289faa1ce9668a25ee23181c574d1a0a2a62c975c2e05d66881ae77bf2e9',
    'LOCK5-B': '152dbaa3de85325eea4d5ee24e5f3dcb910de15d081323e4c7012527aab9d670',
    'LOCK5-C': '55505283393d5aae4844de67c8f8a32362c161ae5a92b4500f3df1af5964d437',
}

@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_stock_replay(tmp_path,seed):
    capture=_play(tmp_path,lambda root:_start_stock(root,seed))
    text=_bytes_of(capture)
    digest=hashlib.sha256(text.encode()).hexdigest()
    (tmp_path/'capture.json').write_text(text)
    (tmp_path/'capture.sha256').write_text(digest)
    assert seed in REFERENCE_SHA256
    assert digest == REFERENCE_SHA256[seed], f'{seed} transcript differs from exact-base reference'
