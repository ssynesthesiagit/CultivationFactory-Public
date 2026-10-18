from pathlib import Path

import pytest

from tools.perf_suite import FACTORY_PATHS, load_budgets
from tools.perf_suite import run as run_perf_suite, violations
from character_creation.insight_build_policy import (
    _sphere_attack_abilities_cached,
    sphere_attack_abilities,
)


def test_sphere_attack_rule_scan_is_cached_without_sharing_mutable_results():
    _sphere_attack_abilities_cached.cache_clear()
    owned = {"tianxia.sphere.wrestling"}

    first = sphere_attack_abilities(owned)
    first.add("BAD")
    second = sphere_attack_abilities(reversed(tuple(owned)))

    assert second == {"STR"}
    assert _sphere_attack_abilities_cached.cache_info().hits == 1


def test_factory_budget_keys_follow_the_runner_path_definition():
    for scenario in ("factory", "factory_snapshot"):
        budgets = load_budgets(source=scenario == "factory_snapshot")
        emitted = {f"{scenario}/{path}" for path in FACTORY_PATHS}
        covered = {key for key in budgets if key.startswith(f"{scenario}/")}
        assert covered == emitted


def test_unmeasured_factory_paths_are_not_presented_as_calibrated_budgets():
    budgets = load_budgets()
    assert not any(key.startswith(("factory/", "factory_snapshot/")) for key in budgets)


def test_factory_path_definition_covers_all_factory_paths():
    assert set(FACTORY_PATHS) == {"build_choices", "compile", "stage2", "finalize", "character_sheet"}
