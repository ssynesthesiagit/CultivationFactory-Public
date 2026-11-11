import json

from combat.ext.needle import cell_id
from combat.gate2_runtime_models import Position
from combat.placement_menu import CHOICE
from tests.h49_fog_support import assert_roundtrip
from tests.lighting_darkness_support import darkness_rules  # noqa: F401 (fixture)
from tests.menu_identity import action_group
from tests.r1i_service_support import FOE, OWNER, SECOND, fixture


def test_darkness_fog_matches_engine_endpoint_policy(tmp_path, darkness_rules, capsys):
    combat, table, mid, send, _commit = fixture(
        tmp_path, ["DARK_BASE_DARKNESS"], allies=(SECOND,), wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 8, "y": 6}, SECOND: {"x": 12, "y": 6}},
    )
    state = table.state(mid)
    menu = state["menu"]
    # Keep the menu/refusal evidence visible even on a passing queued run.
    with capsys.disabled():
        print("Darkness fog setup menu:", json.dumps({
            "actions": [{
                "label": group["label"],
                "source_definition_id": group["source_definition_id"],
                "placement_picker": group.get("placement_picker", False),
                "options": [{"keys": sorted(option), "destination": option.get("destination")}
                            for option in group["options"]],
            } for group in menu["actions"]],
            "refused": state["unavailable_reasons"],
        }, sort_keys=True), flush=True)
    darkness = action_group(menu, "DARK_BASE_DARKNESS")
    # CELL menus defer the exact destination to the saved placement choice.
    assert darkness["placement_picker"]
    assert len(darkness["options"]) == 1
    root = darkness["options"][0]
    assert root["destination"] is None
    result = send(root["candidate_id"])
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == CHOICE, prompt
    square = cell_id(Position(x=6, y=6, z=0), include_altitude=True)
    assert square in {option["id"] for option in prompt["choice"]["options"]}
    result = send(root["candidate_id"], [{
        **prompt["context"], "selection": "USE", "option_ids": [square],
    }])
    assert result["status"] == "COMMITTED", result
    perception = table.state(mid, fog=True)["fog_perception"][SECOND]
    assert FOE not in perception["creatures"]
    assert [3, 6] not in perception["cells"]
    assert [2, 6] in perception["cells"]  # outside-to-outside matches the engine's endpoint policy
    assert_roundtrip(combat, tmp_path, mid)
