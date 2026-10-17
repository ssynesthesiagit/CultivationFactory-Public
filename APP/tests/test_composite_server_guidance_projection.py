"""The Composite Playbooks tab shows the server-validated plan, not 179 records.

The GM profile carries ``server_validated_controller``: a sequence the
composite controller already validated against the sealed action packets and
resource pools.  The workspace projects it as display-only ordered steps and
binds only the plan's records; Command 5 keeps that sequence and blanks any
other source sequence.
"""
from __future__ import annotations

import pytest

from app.core import FoundryError
from factory_authoring.command5_profile import CharacterGMCommand5Profile
from factory_authoring.service import FactoryAuthoringWorkspaceService, SERVER_COMPOSITE_GUIDANCE_SCHEMA

CARDS = {
    "AIR_BASE_GATHER_CURRENT": {"display_name": "Gather Current", "record_hash": "a" * 64, "source_packet_ids": ["p1"], "source": {"path": "x"}},
    "AIR_BASE_WIND_LASH": {"display_name": "Wind Lash", "record_hash": "b" * 64, "source_packet_ids": ["p2"], "source": {"path": "x"}},
    "TAL_AIR_SKY_STEP": {"display_name": "Sky-Step", "record_hash": "c" * 64, "source_packet_ids": ["p3"], "source": {"path": "x"}},
}


def _controller() -> dict:
    return {
        "schema": SERVER_COMPOSITE_GUIDANCE_SCHEMA,
        "sequence": [
            {"step": 1, "round_offset": 0, "economy": "bonus_action", "record_id": "AIR_BASE_GATHER_CURRENT", "action_id": "action.1",
             "conditions": {"timing": "bonus_action", "range": "30 feet", "target": "A 10-foot cube", "resource_costs": []}},
            {"step": 2, "round_offset": 1, "economy": "action", "record_id": "AIR_BASE_WIND_LASH", "action_id": "action.2",
             "conditions": {"timing": "action", "range": "60 feet", "target": "One creature", "resource_costs": [{"resource_id": "tianxia.resource.qi", "amount": 0}]}},
        ],
        "fallback": {"record_id": "AIR_BASE_GATHER_CURRENT", "action_id": "action.1", "economy": "bonus_action", "conditions": {"timing": "bonus_action", "resource_costs": []}},
        "resource_budget": {"resource_budgets": [{"resource_id": "tianxia.resource.qi", "max_spend": 40, "total_sequence_cost": 0}]},
    }


def test_workspace_projects_the_validated_plan_and_binds_only_its_records():
    fields = FactoryAuthoringWorkspaceService._server_guided_playbook_fields(_controller(), CARDS)

    assert [step["display_name"] for step in fields["sequence"]] == ["Gather Current", "Wind Lash"]
    assert fields["sequence"][0]["economy"] == "bonus_action" and fields["sequence"][0]["round_offset"] == 0
    assert fields["sequence"][1]["resource_costs"] == [{"resource_id": "tianxia.resource.qi", "amount": 0}]
    assert fields["fallback"]["display_name"] == "Gather Current"
    assert fields["linked_action_record_ids"] == ["AIR_BASE_GATHER_CURRENT", "AIR_BASE_WIND_LASH"]
    assert [row["record_id"] for row in fields["record_bindings"]] == ["AIR_BASE_GATHER_CURRENT", "AIR_BASE_WIND_LASH"]
    assert fields["sequence_authority"] == SERVER_COMPOSITE_GUIDANCE_SCHEMA
    assert fields["sequence_classification"] == "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY"


def test_workspace_without_server_guidance_keeps_the_plain_grouping():
    assert FactoryAuthoringWorkspaceService._server_guided_playbook_fields(None, CARDS) is None


@pytest.mark.parametrize("mutation", ["schema", "record", "empty"])
def test_workspace_rejects_malformed_server_guidance(mutation):
    controller = _controller()
    if mutation == "schema":
        controller["schema"] = "Other.v1"
    elif mutation == "record":
        controller["sequence"][1]["record_id"] = "NOT_SELECTED"
    else:
        controller["sequence"] = []
    with pytest.raises(FoundryError) as caught:
        FactoryAuthoringWorkspaceService._server_guided_playbook_fields(controller, CARDS)
    assert caught.value.code == "FACTORY_WORKSPACE_CONTROLLER_GUIDANCE_INVALID"


def _playbook(**extra) -> dict:
    return {
        "playbook_id": "gm.playbook.test",
        "classification": "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
        "record_bindings": [{"record_id": "AIR_BASE_GATHER_CURRENT"}, {"record_id": "AIR_BASE_WIND_LASH"}],
        **extra,
    }


def test_command5_keeps_only_the_server_validated_sequence():
    surface = {"execution_authority": False, "actions": []}
    server_steps = [{"record_id": "AIR_BASE_GATHER_CURRENT", "display_name": "Gather Current"}]

    kept = CharacterGMCommand5Profile._linked_display_composites(
        [_playbook(sequence=server_steps, sequence_authority=SERVER_COMPOSITE_GUIDANCE_SCHEMA)], surface,
    )
    blanked = CharacterGMCommand5Profile._linked_display_composites(
        [_playbook(sequence=server_steps), _playbook(sequence=server_steps, sequence_authority="model-authored")], surface,
    )

    assert kept[0]["sequence"] == server_steps
    assert [row["sequence"] for row in blanked] == [[], []]


def test_command5_links_only_the_plan_records_from_a_reviewed_surface():
    surface = {
        "execution_authority": True,
        "actions": [
            {"record_id": "AIR_BASE_GATHER_CURRENT", "name": "Gather Current"},
            {"record_id": "AIR_BASE_WIND_LASH", "name": "Wind Lash"},
            {"record_id": "TAL_AIR_SKY_STEP", "name": "Sky-Step"},
        ],
    }
    linked = CharacterGMCommand5Profile._linked_display_composites(
        [_playbook(sequence=[{"record_id": "AIR_BASE_GATHER_CURRENT"}], sequence_authority=SERVER_COMPOSITE_GUIDANCE_SCHEMA)], surface,
    )
    assert linked[0]["linked_action_record_ids"] == ["AIR_BASE_GATHER_CURRENT", "AIR_BASE_WIND_LASH"]
    assert linked[0]["sequence"] == [{"record_id": "AIR_BASE_GATHER_CURRENT"}]
