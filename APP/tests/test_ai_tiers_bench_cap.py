"""The Tricky bench's fights must run to its own 40-round cap, not the native helper's default of 8.

Regression for the round-8 draws in TRICKYTUNE1: fight() defaults to maximum_rounds=8, so a bench that omits the
argument ends every equal fight as DRAW_DURATION at round 9. The bench must hand its ROUND_CAP to the match.
Round 4 (lead 2026-10-20) raised the cap from 20 to 40: at 20 the cap fired mid death-save sequence in equal
high-HP fights, which read as draws instead of the victory the engine gives once the dying side stabilises.
"""
from tests.ai_tiers_native_support import fight
from tests.test_ai_tiers_bench import ROUND_CAP


def test_bench_round_cap_reaches_the_match(tmp_path):
    assert ROUND_CAP == 40
    _, _, session = fight(tmp_path, equal=True, start_turn=False, bench_starts=True, maximum_rounds=ROUND_CAP)
    assert session.engine.state.maximum_rounds == ROUND_CAP


def test_native_helper_default_is_not_the_bench_cap(tmp_path):
    _, _, session = fight(tmp_path, equal=True, start_turn=False, bench_starts=True)
    assert session.engine.state.maximum_rounds == 8


def test_bench_gate_uses_a_never_tuned_held_out_seed_set():
    """TRICKYTUNE4R findings 1-2: the mirror gate is 0.85 unless the held-out set reaches 75% (lead
    2026-10-20; round-5 held-out was 72.9%, so 0.85 stays), and the held-out seeds must be disjoint
    from the tuning seeds, or the generalisation check is just the tuning run."""
    from tests.test_ai_tiers_bench import GATE, HELD_OUT_SEEDS, SEEDS
    from tests.test_ai_tiers_bench_heldout import HELD_OUT_GATE, HELD_OUT_MARGIN
    assert GATE == .85
    assert HELD_OUT_GATE == .75
    assert HELD_OUT_MARGIN == .15
    assert set(SEEDS) and set(HELD_OUT_SEEDS)
    assert not set(SEEDS) & set(HELD_OUT_SEEDS), "held-out seeds must never be tuning seeds"
