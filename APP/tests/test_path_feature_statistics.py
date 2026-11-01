"""Path feature passive statistics: base AC calculations and always-on bonuses."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import FoundryError, sha256_json
from projector.path_feature_statistics import (
    load_path_feature_statistic_formulas,
    resolve_armor_class,
    statistic_formulas_path,
)

ROOT = Path(__file__).resolve().parents[1]
BASELINE = {
    "rule_id": "tianxia.core.unarmored_ac.owner_r1",
    "formula": {"formula_id": "tianxia.core.baseline.unarmored_ac.owner_r1"},
}
UNARMORED = "tianxia.path.body_refining.feature.unarmored_defense"
TEMPERED = "tianxia.subpath.body.iron_shirt.feature.tempered_flesh"
STAFF = "tianxia.subpath.body.bojutsu.feature.staff_of_one"


def _context(*, con: int, dex: int, pb: int) -> dict:
    return {
        "ability_scores": {"STR": 10, "DEX": 10 + 2 * dex, "CON": 10 + 2 * con, "INT": 10, "WIS": 10, "CHA": 10},
        "ability_modifiers": {"STR": 0, "DEX": dex, "CON": con, "INT": 0, "WIS": 0, "CHA": 0},
        "cl": 10,
        "pb": pb,
    }


def test_shipped_statistic_formulas_are_sealed_and_anchored() -> None:
    formulas = load_path_feature_statistic_formulas(ROOT)
    rules = {rule["feature_id"]: rule for rule in formulas["rules"]}
    body = rules[UNARMORED]
    assert body["kind"] == "base_ac_calculation"
    assert body["source"]["heading"] == "CL1 - Unarmored Defense"
    assert body["source"]["path"].endswith("Tianxia_Body_Refining_Player_Path_Chapter_R8.md")
    assert {rule["kind"] for rule in formulas["rules"]} == {"base_ac_calculation", "ac_bonus", "conditional_ac_bonus"}
    for rule in formulas["rules"]:
        if rule["kind"] == "ac_bonus":
            assert rule["requires_base_calculation_feature_id"] == UNARMORED
            assert rule["source"]["heading"]


def test_tampered_statistic_formulas_fail_the_seal(tmp_path: Path) -> None:
    source = statistic_formulas_path(ROOT).read_text(encoding="utf-8")
    target_root = tmp_path / "root"
    (target_root / "authority").mkdir(parents=True)
    (target_root / "authority" / statistic_formulas_path(ROOT).name).write_text(source.replace('"bonus": 1', '"bonus": 5', 1), encoding="utf-8")
    with pytest.raises(FoundryError) as excinfo:
        load_path_feature_statistic_formulas(target_root)
    assert excinfo.value.code == "PROJECTION_STATISTIC_FORMULAS_INVALID"


def test_body_refiner_uses_unarmored_defense_and_always_on_subpath_bonus() -> None:
    formulas = load_path_feature_statistic_formulas(ROOT)
    # The finalized CL10 Body Refiner: CON +1, DEX +1, PB 4 read AC 11 from the
    # baseline; Unarmored Defense (10 + CON + PB) gives 15.
    result = resolve_armor_class(formulas, [UNARMORED, "tianxia.path.body_refining.feature.iron_fist"], baseline_rule=BASELINE, baseline_value=11, baseline_trace={"value": 11}, context=_context(con=1, dex=1, pb=4))
    assert result["ac_base"] == 15
    assert result["ac_active"] == 15
    assert result["ac_generation"]["calculation"] == "path_feature"
    assert result["ac_generation"]["calculation_feature_id"] == UNARMORED
    assert [row["value"] for row in result["ac_generation"]["alternatives_considered"]] == [11, 15]
    assert result["ac_generation"]["always_on_bonuses"] == []
    assert [rule["feature_id"] for rule, _trace in result["applied_rules"]] == [UNARMORED]

    with_bonus = resolve_armor_class(formulas, [UNARMORED, TEMPERED, STAFF], baseline_rule=BASELINE, baseline_value=11, baseline_trace={"value": 11}, context=_context(con=1, dex=1, pb=4))
    assert with_bonus["ac_base"] == 15
    assert with_bonus["ac_active"] == 16
    assert [row["feature_id"] for row in with_bonus["ac_generation"]["always_on_bonuses"]] == [TEMPERED]
    # Staff of One needs a wielded Staff: named as pending, never added.
    assert STAFF in with_bonus["ac_generation"]["conditional_bonuses_pending_execution"]


def test_alternate_calculations_replace_rather_than_stack_and_baseline_wins_when_higher() -> None:
    formulas = load_path_feature_statistic_formulas(ROOT)
    # A frail Body Refiner with high DEX at CL1: 10 + DEX(+4) = 14 beats 10 + CON(-1) + PB 2 = 11.
    result = resolve_armor_class(formulas, [UNARMORED, TEMPERED], baseline_rule=BASELINE, baseline_value=14, baseline_trace={"value": 14}, context={**_context(con=-1, dex=4, pb=2), "cl": 1})
    assert result["ac_base"] == 14
    assert result["ac_generation"]["calculation"] == "unarmored_base"
    # Tempered Flesh applies only while Unarmored Defense is the chosen calculation.
    assert result["ac_generation"]["always_on_bonuses"] == []
    assert TEMPERED in result["ac_generation"]["conditional_bonuses_pending_execution"]
    assert result["applied_rules"] == []


def test_qi_cultivator_keeps_the_baseline_and_names_qi_armor_as_pending() -> None:
    formulas = load_path_feature_statistic_formulas(ROOT)
    result = resolve_armor_class(formulas, ["tianxia.path.qi_cultivation.feature.qi_armor", "tianxia.path.qi_cultivation.feature.qi_sensing"], baseline_rule=BASELINE, baseline_value=13, baseline_trace={"value": 13}, context=_context(con=0, dex=3, pb=3))
    assert result["ac_base"] == result["ac_active"] == 13
    assert result["ac_generation"]["calculation"] == "unarmored_base"
    assert result["ac_generation"]["conditional_bonuses_pending_execution"] == ["tianxia.path.qi_cultivation.feature.qi_armor"]


def test_seal_matches_canonical_hash_of_unsigned_document() -> None:
    formulas = load_path_feature_statistic_formulas(ROOT)
    unsigned = {key: value for key, value in formulas.items() if key != "seal_sha256"}
    assert formulas["seal_sha256"] == sha256_json(unsigned)
