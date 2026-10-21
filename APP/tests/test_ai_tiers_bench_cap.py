"""The Tricky bench's fights must run to its own 20-round cap, not the native helper's default of 8.

Regression for the round-8 draws in TRICKYTUNE1: fight() defaults to maximum_rounds=8, so a bench that omits the
argument ends every equal fight as DRAW_DURATION at round 9. The bench must hand its ROUND_CAP to the match.
"""
from tests.ai_tiers_native_support import fight
from tests.test_ai_tiers_bench import ROUND_CAP


def test_bench_round_cap_reaches_the_match(tmp_path):
    assert ROUND_CAP == 20
    _, _, session = fight(tmp_path, equal=True, start_turn=False, bench_starts=True, maximum_rounds=ROUND_CAP)
    assert session.engine.state.maximum_rounds == ROUND_CAP


def test_native_helper_default_is_not_the_bench_cap(tmp_path):
    _, _, session = fight(tmp_path, equal=True, start_turn=False, bench_starts=True)
    assert session.engine.state.maximum_rounds == 8
