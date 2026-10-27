"""Six stock AI replays for A2GBODSUB6; capture files stay inside pytest's temporary directory."""
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS, _play, _bytes_of, _start_stock


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_stock_capture_r5(tmp_path, seed):
    capture = _play(tmp_path, lambda root: _start_stock(root, seed))
    assert capture['choices'] and capture['events'] and capture['rolls']
    (tmp_path / f'head-{seed}.json').write_text(_bytes_of(capture))
