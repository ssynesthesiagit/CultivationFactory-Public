"""The opt-in checks must skip before any experiment or capture is started."""
from types import SimpleNamespace

import pytest

from tests.combat_ai_slices_options import opt_in_options
from tests.test_combat_ai_slices_batch import test_offline_paired_maps as batch_check
from tests.test_combat_ai_slices_replays import test_flag_off_matches_base as replay_check
from tests.test_combat_ai_slices_review_stock import test_review_stock_captures as stock_check


def config_with(overrides):
    def getoption(name):
        assert name == 'override_ini'
        return overrides
    return SimpleNamespace(getoption=getoption)


@pytest.mark.parametrize('overrides', [None, []])
@pytest.mark.parametrize('check', [batch_check, replay_check, stock_check])
def test_absent_opt_in_skips_before_work(overrides, check):
    request = SimpleNamespace(config=config_with(overrides))
    # None fixtures also ensure a wrapper cannot start work before skipping.
    args = (None, None, request)
    if check is not batch_check:
        args += ('LOCK5-A',)
    with pytest.raises(pytest.skip.Exception, match='opt-in'):
        check(*args)


def test_explicit_opt_in_options_are_preserved():
    config = config_with(['combatai2_batch=1', 'combatai2_output=/scratch/a=b.json',
                          'unrelated', 'combatai2_batch=0', 'combatai2_batch=1'])
    assert opt_in_options(config) == {
        'combatai2_batch': '1', 'combatai2_output': '/scratch/a=b.json'}
