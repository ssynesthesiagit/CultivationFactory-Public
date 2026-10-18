"""Keep reviewed performance budgets aligned with the runner's emitted paths."""

from tools.perf_suite import FACTORY_PATHS, load_budgets, violations


def _passing_rows(keys):
    return [{"scenario": key.split("/", 1)[0], "path": key.split("/", 1)[1],
             "status": "PASS", "counters": {name: 0 for name in limits}}
            for key, limits in keys.items()]


def _replace_calls(rows, key, calls):
    for row in rows:
        if row["scenario"] + "/" + row["path"] == key:
            row["counters"]["application_calls"] = calls
            return
    raise AssertionError(f"missing fixture row {key}")


def test_factory_budgets_cover_every_emitted_successful_path():
    expected = {f"factory/{path}" for path in FACTORY_PATHS}
    budgets = load_budgets()
    actual = {key: value for key, value in budgets.items() if key.startswith("factory/")}

    assert set(actual) == expected
    rows = _passing_rows(actual)
    _replace_calls(rows, "factory/build_choices", 244399)
    assert not violations(rows, actual)


def test_snapshot_factory_budgets_cover_every_emitted_successful_path():
    expected = {f"factory_snapshot/{path}" for path in FACTORY_PATHS}
    budgets = load_budgets(source=True)
    actual = {key: value for key, value in budgets.items()
              if key.startswith("factory_snapshot/")}

    assert set(actual) == expected
    rows = _passing_rows(actual)
    _replace_calls(rows, "factory_snapshot/build_choices", 297835)
    assert not violations(rows, actual)


def test_saved_fight_preview_budgets_use_emitted_names():
    budgets = load_budgets(source=True, factory=False)
    assert "other1/area_preview" in budgets
    assert "other1/target_preview" in budgets
    assert "other1/engine_area_preview" not in budgets
    assert "other1/engine_target_preview" not in budgets

    rows = _passing_rows({key: budgets[key] for key in (
        "other1/area_preview", "other1/target_preview")})
    assert not violations(rows, {row["scenario"] + "/" + row["path"]: budgets[
        row["scenario"] + "/" + row["path"]] for row in rows})
