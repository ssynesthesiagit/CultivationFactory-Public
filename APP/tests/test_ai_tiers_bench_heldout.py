"""Held-out Tricky bench: the seeds the round-4 hill climb never saw (100-103).

Opt-in and run through HeavyQ only, like tests/test_ai_tiers_bench.py. This file exists separately so
the queue selects the seed set by choosing the file; nothing can relax the tuning gate.

Why: TRICKYTUNE4R found the round-4 tactics were chosen on the same 48 fights they were measured on.
This set is never used for tuning. Four new seeds (100-103) over the same 3 builds x 2 battlefields
x both seats run mirrored (each build plays both seats), scored with the round-4 rule (40-round cap;
at the cap a side whose every primary combatant is DYING/STABLE/out loses, draws otherwise). It is
the same 48-fight size as the tuning bench: the queue kills a single test after 2400 s, and a
six-seed set on main's tactics ran past that limit on 2026-10-20 (67 of 72 fights completed).

The gate requires both:
- an absolute floor of HELD_OUT_GATE (0.75) of decided fights, the lead's "below 75% is FAIL" line.
  The round-5 final-tactics run measured WIN 35 LOSS 13 DRAW 0 = 72.9%, so this gate fails;
- a win rate at least HELD_OUT_MARGIN (15 points) above main's tactics on these same seeds, measured
  once in the round-5 control run by running this file on a main checkout. HELD_OUT_MAIN_WIN_RATE is
  that control's printed result, recorded here; it is never tuned against.

Lead decision 2026-10-20: equal-build mirrors are dice-limited near 80% (TRICKYTUNE4 section 4);
TRICKYTUNE5 targets 85% on a wider realistic bench.
"""
import json
import os
from pathlib import Path

import pytest

from tests.test_ai_tiers_bench import (
    BENCH_MARKER,
    DECISION_LIMIT,
    DRAW_GATE,
    HELD_OUT_SEEDS,
    run_bench,
    summarize,
)

BENCH_ENABLED = os.environ.get("CF_AI_BENCH") == "1" or BENCH_MARKER.exists()
pytestmark = pytest.mark.skipif(not BENCH_ENABLED,
    reason="opt-in bench: set CF_AI_BENCH=1 or create APP/tests/.ai_bench_enabled")

HELD_OUT_GATE = .75
HELD_OUT_MARGIN = .15
# Main's tactics on HELD_OUT_SEEDS with the round-4 scoring, from the one round-5 control run
# (2026-10-20, Tabik): WIN 26 LOSS 21 DRAW 1 of 48, 26/47 = 55.3% of decided fights.
HELD_OUT_MAIN_WIN_RATE = 26 / 47


def test_heldout_seed_equal_build_tricky_benchmark(tmp_path, capsys):
    results, decisions, contexts, scoring = run_bench(tmp_path, HELD_OUT_SEEDS, capsys)
    report, summary = summarize(results, decisions, contexts, scoring)
    report["seed_set"] = "heldout"
    report["seeds"] = list(HELD_OUT_SEEDS)
    (tmp_path / "AIUP1-heldout.json").write_text(json.dumps(report, indent=2) + "\n")
    with capsys.disabled():
        print("AIUP1 HELDOUT " + json.dumps(report), flush=True)
    assert len(results) >= 40
    assert report["win_rate"] >= HELD_OUT_GATE, summary
    assert report["win_rate"] >= HELD_OUT_MAIN_WIN_RATE + HELD_OUT_MARGIN, (
        f"held-out must beat main's held-out {HELD_OUT_MAIN_WIN_RATE:.1%} by >= {HELD_OUT_MARGIN:.0%}: {summary}")
    assert report["draw_rate"] <= DRAW_GATE, summary
    assert report["maximum_controller_seconds"] <= DECISION_LIMIT, summary
