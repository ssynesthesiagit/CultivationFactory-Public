"""Source-level Foundation formulas; causal/runtime acceptance is separate."""
from copy import deepcopy

import pytest

from app.core import FoundryError
import non_sphere_authority.foundation_mechanics as foundations
from stage2.service import _formula_value


@pytest.fixture(scope="module")
def records():
    return foundations.verified_foundation_records()


def _profile(records, identity, paths, *, stage=None):
    return foundations.resolve_initial_foundation_mechanics(records[identity], paths, stage=stage)


def _value(modifier, pb=6):
    return _formula_value(modifier["formula"], {"pb": pb})[0]


def test_karma_reserve_targets_only_the_source_supported_selected_path(records):
    identity = next(key for key in records if "karma_knot" in key.lower())
    result = _profile(records, identity, ["tianxia.path.body_refining", "tianxia.path.spirit_awakening"])
    assert result["initial_state"]["stage"] == "Awakened"
    assert [(row["resource_id"], _value(row)) for row in result["resource_modifiers"]] == [
        ("tianxia.resource.resonance", 6),
    ]
    assert result["hp_maximum_modifiers"] == []
    assert result["initial_state"]["resource"]["initial_current"] == 0
    assert result["initial_state"]["resource"]["maximum"] == 1


def test_devouring_womb_has_one_flat_pb_bonus_and_no_automatic_refinement(records):
    identity = "heaven_devouring_shedding_womb_v0_2B"
    paths = ["tianxia.path.body_refining", "tianxia.path.spirit_awakening"]
    result = _profile(records, identity, paths)
    assert [_value(row) for row in result["hp_maximum_modifiers"]] == [6]
    assert result["resource_modifiers"] == []
    assert result["initial_state"]["awards_stage_advancement"] is False
    with pytest.raises(FoundryError):
        _profile(records, identity, paths, stage="Refined")


@pytest.mark.parametrize("identity", ["weak_reed_tendons_v0_2B", "dragon_wind_vessel_v0_2E"])
def test_unavailable_initial_speed_is_not_an_unconditional_statistic(records, identity):
    result = _profile(records, identity, ["tianxia.path.body_refining"])
    assert result["statistic_modifiers"] == []
    assert any(row["statistic"] == "speed_ft" and row["availability"] == "unavailable"
               for row in result["conditional_modifiers"])


def test_white_crane_speed_preserves_the_footwork_condition(records):
    result = _profile(records, "white_crane_cloud_step_v0_2B", ["tianxia.path.body_refining"])
    assert [_value(row) for row in result["hp_maximum_modifiers"]] == [6]
    assert result["statistic_modifiers"] == []
    speed = next(row for row in result["conditional_modifiers"] if row["statistic"] == "speed_ft")
    assert speed["availability"] == "condition_required"
    assert "armor or restraints" in speed["source_fields"]["Effect"]


def test_unstable_empty_bowl_cannot_claim_the_stable_reserve(records):
    result = _profile(records, "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR",
                      ["tianxia.path.spirit_awakening"], stage="Unstable")
    assert result["resource_modifiers"] == []
    assert any("stable" in row["source_fields"].get("Limit", "")
               for row in result["conditional_modifiers"])


def test_every_published_initial_choice_preserves_resource_and_source_constraints(records):
    paths = ["tianxia.path.body_refining", "tianxia.path.qi_cultivation", "tianxia.path.spirit_awakening"]
    for identity, record in records.items():
        for stage in record["stage"].split(" or "):
            result = _profile(records, identity, paths, stage=stage)
            initial = result["initial_state"]
            assert initial["resource"]["initial_current"] == 0
            assert initial["resource"]["maximum"] == 1
            assert initial["refill_current"] is False
            assert result["source_record_sha256"] == initial["source_record_sha256"]
            assert all("source_feature_sha256" in row for field in (
                "resource_modifiers", "hp_maximum_modifiers", "statistic_modifiers", "conditional_modifiers",
            ) for row in result[field])


def test_changed_foundation_source_cannot_publish_mechanical_formulas(records):
    record = deepcopy(records["heaven_devouring_shedding_womb_v0_2B"])
    record["semantic_surfaces"]["features"] += "\nInvented benefit."
    with pytest.raises(FoundryError):
        foundations.resolve_initial_foundation_mechanics(record, ["tianxia.path.body_refining"])
