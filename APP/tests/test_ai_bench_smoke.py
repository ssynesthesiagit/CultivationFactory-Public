"""Fixed-seed smoke for tools/ai_bench.py: the tool runs, every choice is legal, metrics are recorded,
and replays are deterministic. No win-rate threshold here; strength is measured by the tool's report.
Offline; no live model."""
import pytest

from combat.ai_mastermind import MastermindPlan
from tests.ai_tiers_native_support import OWNER, FOE
from tools import ai_bench


def test_switches_are_restored_after_each_configuration():
    # Every switch any configuration names, including use_tactics (review AIUP2F15R blocker).
    names = sorted({name for overrides in ai_bench.CONFIGS.values() for name in overrides})
    before = {name: getattr(MastermindPlan, name) for name in names}
    for config, overrides in ai_bench.CONFIGS.items():
        with ai_bench.offline_and_switches(overrides):
            for name, value in overrides.items():
                assert getattr(MastermindPlan, name) is value, (config, name)
        assert {name: getattr(MastermindPlan, name) for name in names} == before, config


def test_wilson_interval_brackets_the_rate():
    low, high = ai_bench.wilson(30, 50)
    assert low < .6 < high
    assert ai_bench.wilson(0, 0) == (0.0, 0.0)


@pytest.mark.parametrize("config", ["full", "no_plays", "no_tactics"])
def test_bench_smoke_is_legal_recorded_and_deterministic(tmp_path, config):
    arena, build = ai_bench.ARENAS[0], ai_bench.BUILDS[1]
    first = ai_bench.run_config(config, 1, tmp_path / "a", lambda row: None, arenas=(arena,), builds=(build,))
    second = ai_bench.run_config(config, 1, tmp_path / "b", lambda row: None, arenas=(arena,), builds=(build,))
    assert first["fights"] == 2
    assert sorted(r["boss"] for r in first["results"]) == sorted([OWNER, FOE])
    assert all(r["outcome"] in {"WIN", "LOSS", "DRAW"} for r in first["results"])
    assert first["INCOMPLETE"] == 0
    assert first["decisions"] > 0 and first["seconds_max"] >= first["seconds_median"] >= 0
    assert first["dealt_per_round"] >= 0 and first["taken_per_round"] >= 0
    assert 0 <= first["divergence_rate"] <= 1
    assert [r["replay_sha256"] for r in first["results"]] == [r["replay_sha256"] for r in second["results"]]
    assert [r["outcome"] for r in first["results"]] == [r["outcome"] for r in second["results"]]
    # The Play receipt is recorded for every MASTERMIND decision, with or without the play term.
    assert first["plays"]
