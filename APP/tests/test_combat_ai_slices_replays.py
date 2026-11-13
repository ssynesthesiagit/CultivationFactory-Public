"""Opt-in fork-pinned six stock captures with the experiment disabled."""
import pytest
from tests.combat_ai_slices_options import opt_in_options
from tests.test_save_reload_equivalence import STOCK_SEEDS


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_flag_off_matches_base(tmp_path, monkeypatch, request, seed):
    opts = opt_in_options(request.config)
    base = opts.get('combatai2_replay_base')
    if not base:
        pytest.skip('opt-in exact fork comparison through heavyq')
    from tests.test_wall_height_replays import test_six_full_stock_ai_captures_stay_identical
    monkeypatch.delenv('CF_COMBAT_AI_SLICES_1_2', raising=False)
    monkeypatch.setenv('CF_REPLAY_BASE', base)
    monkeypatch.setenv('WALLHEIGHT_REPLAY_EVIDENCE', opts['combatai2_replay_evidence'])
    test_six_full_stock_ai_captures_stay_identical(tmp_path, seed)
