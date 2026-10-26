"""Initial Foundation state is derived from every exact playable source."""
from copy import deepcopy

import pytest

from app.core import FoundryError
from non_sphere_authority.foundation_mechanics import (
    foundation_passive_definitions, initial_foundation_options,
    resolve_initial_foundation_state, verified_foundation_records,
)


@pytest.fixture(scope="module")
def foundations():
    return verified_foundation_records()


PATHS = ["tianxia.path.body_refining", "tianxia.path.qi_cultivation", "tianxia.path.spirit_awakening"]


def test_all_30_published_resources_start_empty_and_stage_choices_are_explicit(foundations):
    ambiguous = []
    for record in foundations.values():
        options = initial_foundation_options(record, PATHS)
        if options["default_stage"] is None:
            ambiguous.append(record["catalog_number"])
            with pytest.raises(FoundryError) as error:
                resolve_initial_foundation_state(record, PATHS)
            assert error.value.code == "CG1_FOUNDATION_INITIAL_STAGE_REQUIRED"
        else:
            assert resolve_initial_foundation_state(record, PATHS)["stage"] == record["stage"]
        for stage in options["stage_options"]:
            state = resolve_initial_foundation_state(record, PATHS, stage=stage)
            assert state["stage"] == stage
            assert state["resource"]["initial_current"] == 0
            assert state["resource"]["maximum"] == 1
            assert state["resource"]["execution_authority"] is False
            assert state["refill_current"] is False
            assert state["awards_stage_advancement"] is False
            assert state["grants_path_attainment"] is False
    assert sorted(ambiguous) == [6, 15, 24, 25, 27]


def test_karma_body_spirit_has_only_spirit_expression_and_no_automatic_integration(foundations):
    record = foundations["karma_knot_root_v0_2B"]
    state = resolve_initial_foundation_state(record, [PATHS[0], PATHS[2]])
    assert state["stage"] == "Awakened"
    assert state["active_expression_path_ids"] == [PATHS[2]]
    assert state["unsupported_active_path_ids"] == [PATHS[0]]
    assert state["dormant_expression_path_ids"] == [PATHS[1]]
    assert state["resource"]["name"] == "Karmic Due"
    assert "Cannot be spent on the event" in state["resource"]["rules"]["Same-Event Rule"]
    with pytest.raises(FoundryError):
        resolve_initial_foundation_state(record, [PATHS[2]], stage="Integrated")
    with pytest.raises(FoundryError):
        resolve_initial_foundation_state(record, [PATHS[0]])


@pytest.mark.parametrize("change", ["stage", "path", "starting_amount", "source_hash", "chakra"])
def test_changed_source_cannot_grant_an_initial_state(foundations, change):
    record = deepcopy(foundations["karma_knot_root_v0_2B"])
    if change == "stage":
        record["stage"] = "Perfected"
    elif change == "path":
        record["compatible_path_ids"].append("BODY_REFINING")
    elif change == "starting_amount":
        record["semantic_surfaces"]["resource"] = record["semantic_surfaces"]["resource"].replace("| **Starting Amount** | 0 |", "| **Starting Amount** | 1 |")
    elif change == "source_hash":
        record["source"]["section_sha256"] = "a" * 64
    else:
        record["authority_class"] = "THEORETICAL_CHAKRA"
    with pytest.raises(FoundryError) as error:
        resolve_initial_foundation_state(record, [PATHS[2]])
    assert error.value.details["reason"] == "source_record_mismatch"


def test_numeric_passive_inventory_matches_manual_source_audit_for_all_foundations(foundations):
    # Independent transcription of the printed base passives, not the parser's
    # own pattern table. Conditional/stage-dependent execution is not claimed.
    hp = {1: 2, 2: 1, 3: 1, 4: 1, 5: 1, 7: 1, 8: 2, 10: 1, 11: 1,
          13: 2, 14: 1, 16: 1, 17: 1, 18: 1, 23: 1, 26: 1, 27: 1}
    cp = {6, 19, 24, 25, 28, 29, 30}
    speed = {9, 14, 22}
    mismatches = []
    for source in foundations.values():
        number = source["catalog_number"]
        document = foundation_passive_definitions(source)
        modifiers = [modifier for row in document["passives"] for modifier in row["numeric_base_definitions"]]
        expected = {}
        if number in hp:
            expected["hp_maximum"] = hp[number]
        if number in cp:
            expected["path_resource_maximum"] = 1
        if number in speed:
            expected["speed_ft"] = 5
        actual = {}
        for modifier in modifiers:
            root = modifier["formula"]["root"]
            actual[modifier["statistic"]] = root["value"] if root["op"] == "constant" else root["terms"][0]["value"]
        assert len(actual) == len(modifiers)
        if actual != expected:
            mismatches.append({"foundation": source["display_name"], "expected": expected, "actual": actual})
    assert mismatches == []


def test_source_conditions_and_non_numeric_passives_survive_normalization(foundations):
    source = next(row for row in foundations.values() if row["catalog_number"] == 14)
    rows = foundation_passive_definitions(source)["passives"]
    frame = next(row for row in rows if row["numeric_base_definitions"])
    assert "while you are not wearing armor or restraints" in frame["source_fields"]["Effect"]
    assert any(row["scope"] == "source_condition_required" for row in frame["numeric_base_definitions"])
    assert "Advantage" in frame["source_fields"]["Effect"]
    assert frame["execution_authority"] is False
