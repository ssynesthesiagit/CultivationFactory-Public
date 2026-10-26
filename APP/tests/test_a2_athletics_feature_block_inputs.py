"""Canonical inputs for Athletics movement consumer regressions.

The runtime loader discovers feature_blocks.d with a glob. Public CI's static
dependency export cannot infer that directory, so name the actual rule files
here and verify the rows they compile. No passive is synthesized by this test.
"""
import json
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet


APP = Path(__file__).resolve().parents[1]
# Keep literal paths: these are real inputs, including for the related table
# and roof-movement consumers, rather than optional fixture output files.
INPUTS = (
    ("combat/rules/feature_blocks.d/auto8-athletics.json", "athletics", {
        "TAL_ATHLETICS_ONE_BREATH_TEN_THOUSAND_STEPS": "one_breath",
        "TAL_ATHLETICS_SPEED_BOOST": "speed_boost",
        "TAL_ATHLETICS_SUDDEN_FLANK": "sudden_flank",
        "TAL_ATHLETICS_MIGHTY_CONDITIONING": "mighty_conditioning",
        "TAL_ATHLETICS_FLASH_STEP": "flash_step",
    }),
    ("combat/rules/feature_blocks.d/walkable-roofs.json", "athletics", {
        "TAL_ATHLETICS_SPIDER_S_TOUCH": "spider_touch",
    }),
    ("combat/rules/feature_blocks.d/athletics-second-pass.json", "athletics_grip_lungs", {
        "TAL_ATHLETICS_SURE_GRIP": "sure_grip",
    }),
)


@pytest.mark.parametrize("path,block,features", INPUTS)
def test_movement_consumers_retain_their_canonical_rule_inputs(path, block, features):
    document = json.loads((APP / path).read_text())
    for feature_id, kind in features.items():
        feature = document["features"][feature_id]
        assert feature["block"] == block
        rules = feature.get("rules", [feature])
        assert any(rule.get("kind") == kind for rule in rules)


def test_canonical_movement_passives_compile_only_for_their_owners():
    expected = {(feature_id, block, kind)
                for _, block, features in INPUTS for feature_id, kind in features.items()}
    owned_ids = sorted(feature_id for feature_id, _, _ in expected)
    owner = compile_character(sheet(owned_ids, cl=15), actor_id="actor:test.athletics_inputs")
    unowned = compile_character(sheet([], cl=15), actor_id="actor:test.no_athletics_inputs")

    def rows(bundle):
        return {(row.get("feature_id"), row.get("block"), row.get("kind"))
                for row in bundle["typed_passives"]}

    assert expected <= rows(owner)
    assert not expected & rows(unowned)
    one_breath = next(row for row in owner["typed_passives"]
                     if row.get("kind") == "one_breath")
    speed_boost = next(row for row in owner["typed_passives"]
                      if row.get("kind") == "speed_boost")
    assert one_breath["focus_ft"] == 20
    assert speed_boost["action_extra_ft"] == 10
