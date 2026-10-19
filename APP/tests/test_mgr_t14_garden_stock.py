"""Garden's shared-engine replay guard, kept separate from public table tests."""
import pytest

from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_shared_seams_preserve_six_stock_replays(tmp_path, monkeypatch, seed):
    from tests import test_a2_glass_stock as stock
    # Preserve the existing guard verbatim. The canonical whole-file stock run
    # exercises this same implementation once for each of the same six seeds.
    # The guard reads its evidence directory from CF_STOCK_EVIDENCE; it has no
    # module-level EVIDENCE attribute to patch.
    assert not hasattr(stock, 'EVIDENCE'), 'stock guard reads its evidence directory from the environment'
    monkeypatch.setenv('CF_STOCK_EVIDENCE', str(tmp_path / 'stock'))
    stock.test_six_stock_captures_equal_main(tmp_path, seed)
