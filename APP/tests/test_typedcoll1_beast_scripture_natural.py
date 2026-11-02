"""Overlapping acquisition sources must not duplicate Beast Scripture reach actions."""

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ME, ROOT, sheet

IRON = "tianxia.path.body_refining.feature.iron_fist"
BEAST = "tianxia.subpath.body.hundred_beast_scripture.feature.beast_scripture_initiate"


def test_beast_scripture_overlapping_acquisitions_register_once():
    character = sheet([IRON, BEAST], cl=6)
    # Portable sheets can report the same feature through earned and source grants.
    character["path_and_subpath"]["source_granted_subpath_feature_record_ids"] = [BEAST]
    character["path_and_subpath"]["earned_feature_occurrences"] = [{"feature_id": BEAST}]
    bundle = compile_character(character, actor_id=ME)
    actions = bundle["action_catalog"]
    ids = [action["source_definition_id"] for action in actions]
    assert len(ids) == len(set(ids))
    fist = [action for action in actions if action["source_definition_id"].endswith(".natural.iron_fist")]
    reach = [action for action in actions if action["source_definition_id"].endswith(
        ".natural.iron_fist.reach_5.beast_scripture_initiate")]
    assert len(fist) == 1 and fist[0]["range_ft"] == 5
    assert len(reach) == 1 and reach[0]["range_ft"] == 10
    Gate4ControllerEngine(
        ROOT, match_seed="typedcoll1", typed_bundles=(bundle,),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}},
    )
