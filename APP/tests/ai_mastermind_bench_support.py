"""Offline native benchmark setup and explicit decided-fight accounting.

Shared by the acceptance benchmark and its small regression tests. A safety
step limit is an incomplete measurement, never a loss or a completed draw.
"""
from tests.ai_tiers_native_support import fight

BENCH_ROUNDS = 20
STEP_LIMIT = 600


def bench_fight(path, talents=(), **kwargs):
    return fight(path, talents, maximum_rounds=BENCH_ROUNDS, **kwargs)


def outcome(terminal, boss_team):
    if terminal is None:
        raise AssertionError("Benchmark did not finish; increase its safety step limit")
    if terminal.winning_team_id is None:
        return "DRAW"
    return "WIN" if terminal.winning_team_id == boss_team else "LOSS"


def summarize(results):
    counts = {name: sum(r["outcome"] == name for r in results)
              for name in ("WIN", "LOSS", "DRAW")}
    decided = counts["WIN"] + counts["LOSS"]
    return {"fights": len(results), **counts, "decided": decided,
            "decided_win_rate": counts["WIN"] / decided if decided else 0,
            "draw_rate": counts["DRAW"] / len(results) if results else 0}
