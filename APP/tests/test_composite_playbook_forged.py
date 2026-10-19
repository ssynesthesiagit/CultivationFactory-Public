"""Learned Forged Techniques join the registry as the character's own records; primary-resource-name costs parse."""
from __future__ import annotations

from factory_authoring.composite_playbook.sheet_adapter import (
    forged_technique_rows, forged_technique_to_action, parse_printed_cost, registry_from_sheet,
)

P = "tianxia.resource.qi"
SHEET = {"selected_record_sections": {"talents": [{"record_id": "T1", "display_name": "Strike",
                                                    "full_description": "Action Type: Action\nCost: 2 Qi"}]},
         "ability_scores_and_statistics": {"primary_resource": {"definitions": [
             {"resource_id": P, "name": "Qi", "current": 9, "max": 9}]}}}
FORGED = {"record_id": "tianxia.constructed.forged_technique.x", "display_name": "Gale Cut", "action_type": "Action",
          "cp_cost": {"base_form": 3, "final": 5}, "limits": ["once per turn"],
          "record_text": "Trigger: a creature ends its move adjacent"}


def test_structured_fields_lead_and_limits_become_conditions():
    action = forged_technique_to_action(FORGED, resource_id=P)
    assert action.economy == "action" and action.resource_costs == ((P, 5),) and action.raw["forged"] is True
    assert action.raw["external_preconditions"] == ("Trigger: a creature ends its move adjacent", "Limit: once per turn")
    assert forged_technique_to_action({"record_id": "x", "record_text": "no labels"}, resource_id=P) is None
    printed = forged_technique_to_action({"record_id": "y", "record_text": "Action Type: Bonus Action\nCost: 4 Qi"},
                                         resource_id=P, resource_names=("cp", "Qi"))
    assert printed.economy == "bonus_action" and printed.resource_costs == ((P, 4),)


def test_primary_resource_name_costs_parse_and_forged_rows_join_the_registry():
    assert parse_printed_cost("4 Qi", P, ("cp", "Qi")) == (((P, 4),), True)
    assert parse_printed_cost("4 Qi", P) == ((), False)
    assert parse_printed_cost("Expend Martial Focus", P, ("cp", "Qi")) == ((), False)
    sheet = {**SHEET, "advanced_systems": {"forged_techniques": {"entries": [FORGED]}}}
    assert [row["record_id"] for row in forged_technique_rows(sheet)] == [FORGED["record_id"]]
    registry, _pools, primary = registry_from_sheet(sheet)
    own = {a: registry.get(a) for a in registry.ids() if not registry.get(a).raw.get("base")}
    assert set(own) == {"T1", FORGED["record_id"]} and own["T1"].resource_costs == ((P, 2),)
    assert own[FORGED["record_id"]].raw["forged"] is True and registry.warnings == [] and primary == P
    assert len(registry_from_sheet(sheet, include_forged=False)[0]) == len(registry) - 1
