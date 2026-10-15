"""Export parity and main's area-safety contracts for the Beast fix round."""
import json
from types import SimpleNamespace

import pytest

from combat import typed_reactions
from combat.area_recipients import harmful_area_subject_allowed, harmful_effect_scope, scoped_area
from tests.test_a2r03_fix_round import FOUNDATION_BLOCK_INPUTS, CANONICAL_SOURCE_INPUTS


def test_shipped_foundation_blocks_are_present_in_runtime_rules():
    """Fail at the missing input, rather than later at a lost combat prompt."""
    compiled_rules = typed_reactions.rules()["features"]
    for path in FOUNDATION_BLOCK_INPUTS:
        assert path.is_file(), f"Public test export omitted {path}"
        features = json.loads(path.read_text())["features"]
        assert features
        for feature_id, block in features.items():
            assert compiled_rules[feature_id] == block


def test_shipped_canonical_source_inputs_are_complete():
    records = {}
    for path in CANONICAL_SOURCE_INPUTS:
        assert path.is_file(), f"Public test export omitted {path}"
        records.update(json.loads(path.read_text())["mechanics"])
    assert {
        "TAL_BRUTE_MOUNTAIN_MOVING_PALM", "TAL_BERSERKER_BERSERK",
        "TAL_BEASTMASTERY_BEAST_TAMER", "TAL_SPIRIT_COMPANIONS_BINDING_SEAL",
    } <= records.keys()


@pytest.mark.parametrize("shape", ["sphere", "cone", "line"])
def test_integrated_main_seals_each_damage_permission_after_json_reload(shape):
    """An inclusive sibling cannot grant friendly damage to generic wording."""
    effects = [
        {"type": "damage", "flat": 5, "damage_types": ["fire"],
         "applies_to": "creatures_in_area", "evidence": "Each creature in the area takes 5 fire damage."},
        {"type": "damage", "flat": 7, "damage_types": ["fire"],
         "applies_to": "creatures_in_area", "evidence": "Creatures in the area take 7 fire damage."},
    ]
    area = scoped_area({"shape": shape, "size_ft": 30, "include_origin": True}, effects,
                       ", and ".join(e["evidence"] for e in effects))
    area, effects = json.loads(json.dumps([area, effects]))
    assert [harmful_effect_scope(area, e) for e in effects] == ["all", "hostile"]
    owner = SimpleNamespace(entity_id="owner", team_id="blue")
    ally = SimpleNamespace(entity_id="ally", team_id="blue")
    foe = SimpleNamespace(entity_id="foe", team_id="red")
    assert [harmful_area_subject_allowed(owner, ally, area, e) for e in effects] == [True, False]
    assert [harmful_area_subject_allowed(owner, foe, area, e) for e in effects] == [True, True]
    assert [harmful_area_subject_allowed(owner, owner, area, e) for e in effects] == [shape == "sphere", False]
