"""Six stock AI fights compared with the main revision merged for A2RINS1RB1."""
import pytest

from tests import test_a2_glass_stock as stock


@pytest.mark.parametrize("seed", stock.STOCK_SEEDS)
def test_six_stock_captures_match_merged_main(tmp_path, monkeypatch, seed):
    # Reuse the established deterministic capture harness, comparing exactly
    # against merged main, excluding unrelated changes since the original fork.
    monkeypatch.setenv("CF_REPLAY_BASE", "ec7dc534aba2d58dd07d3b9d7af718b66e15e9fe")
    monkeypatch.setenv("CF_STOCK_EVIDENCE", "/var/tmp/auto-audit/fix/A2RINS1RB1-evidence/stock")
    stock.test_six_stock_captures_equal_main(tmp_path, seed)
