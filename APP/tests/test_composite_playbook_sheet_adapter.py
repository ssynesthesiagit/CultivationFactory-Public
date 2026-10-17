"""Sealed owner-sheet records -> ActionRegistry (synthetic records, no game text)."""
from __future__ import annotations

from factory_authoring.composite_playbook import (
    ActionRegistry,
    load_base_actions,
    registry_from_sheet,
    sheet_record_to_action,
)
from factory_authoring.composite_playbook.sheet_adapter import parse_printed_cost

PRIMARY = "RES_TEST_PRIMARY"


def _record(record_id, name, text):
    return {"record_id": record_id, "display_name": name, "full_description": text, "section": "talents"}


STRIKE = _record("TAL_TEST_STRIKE", "Test Strike",
                 "#### Test Strike\nAction Type: Action\nFactory Combat Bucket: action\nCost: 1 CP\nMake a technique attack.")
STEP = _record("TAL_TEST_STEP", "Test Step",
               "#### Test Step\n**Action Type:** Bonus Action\nCost: None\nMove 10 feet.")
GUARD = _record("TAL_TEST_GUARD", "Test Guard",
                "#### Test Guard\nAction Type: Reaction\nFactory Combat Bucket: reaction\n"
                "Trigger: An ally within 30 feet is hit\nPrerequisite: CL 5+\nCost: Expend Martial Focus\nReduce the damage.")
MODIFIER = _record("TAL_TEST_MODIFIER", "Test Modifier", "#### Test Modifier\nWhile you hold a ready stance, gain +1.")


def _snapshot(**overrides):
    snapshot = {
        "selected_record_sections": {
            "talents": [STRIKE, STEP, MODIFIER],
            "sphere_automatic_components": [GUARD, STRIKE],  # duplicate id across sections
            "spheres": [_record("tianxia.sphere.test", "Test Sphere", "Action Type: Action\nCost: None")],
        },
        "ability_scores_and_statistics": {"primary_resource": {"definitions": [
            {"resource_id": PRIMARY, "name": "Test Points", "current": 12, "max": 12}]}},
    }
    snapshot.update(overrides)
    return snapshot


def test_parse_printed_cost():
    assert parse_printed_cost("None", PRIMARY) == ((), True)
    assert parse_printed_cost(None, PRIMARY) == ((), True)
    assert parse_printed_cost("2 CP", PRIMARY) == (((PRIMARY, 2),), True)
    assert parse_printed_cost("2 CP.", PRIMARY) == (((PRIMARY, 2),), True)
    assert parse_printed_cost("Expend Martial Focus", PRIMARY) == ((), False)


def test_record_without_action_type_is_not_an_action():
    assert sheet_record_to_action(MODIFIER, section="talents", resource_id=PRIMARY) is None


def test_record_with_action_type_becomes_an_action():
    action = sheet_record_to_action(GUARD, section="sphere_automatic_components", resource_id=PRIMARY)
    assert action.action_id == "TAL_TEST_GUARD" and action.economy == "reaction"
    assert action.resource_costs == () and action.raw["cost_parsed"] is False
    assert action.raw["external_preconditions"] == ("Trigger: An ally within 30 feet is hit", "Prerequisite: CL 5+")
    bold = sheet_record_to_action(STEP, section="talents", resource_id=PRIMARY)
    assert bold.economy == "bonus_action" and bold.resource_costs == () and bold.raw["cost_parsed"] is True


def test_registry_from_sheet_dedups_skips_spheres_and_adds_base_actions():
    registry, pools, primary_id = registry_from_sheet(_snapshot())
    assert primary_id == PRIMARY
    assert pools == {PRIMARY: {"name": "Test Points", "current": 12, "maximum": 12}}
    own = [a for a in registry.ids() if not registry.get(a).raw.get("base")]
    assert own == ["TAL_TEST_STRIKE", "TAL_TEST_STEP", "TAL_TEST_GUARD"]
    assert "tianxia.sphere.test" not in registry
    assert registry.get("TAL_TEST_STRIKE").resource_costs == ((PRIMARY, 1),)
    assert len(registry) == 3 + len(load_base_actions())
    assert registry.get("base.5e.dodge").economy == "action"
    assert registry.get("base.5e.opportunity_attack").economy == "reaction"
    assert any("TAL_TEST_GUARD" in w and "not parsed" in w for w in registry.warnings)


def test_registry_without_base_actions_and_without_primary_resource():
    registry, pools, primary_id = registry_from_sheet(
        _snapshot(ability_scores_and_statistics={}), include_base_actions=False)
    assert primary_id is None and pools == {}
    assert len(registry) == 3
    assert any("primary_resource" in w for w in registry.warnings)


def test_base_actions_data_file_is_the_bootstrap_delegation_list():
    base = load_base_actions()
    assert len(base) == 13
    assert {b.economy for b in base} == {"action", "reaction"}
    assert all(b.resource_costs == () and b.raw["base"] for b in base)


def test_from_sheet_actions_accepts_the_projected_surface():
    assert len(ActionRegistry.from_sheet_actions({"actions": []})) == 0
    registry = ActionRegistry.from_sheet_actions(
        {"actions": [{"action_id": "ACT_X", "display_name": "X", "economy": "action"}]})
    assert "ACT_X" in registry
