"""Saved modifier clocks must be explicit."""
import json

import pytest

from combat.gate3_storage import TYPED_BUNDLES_FILE, load_typed_bundles
from combat.saved_fight_format import UnsupportedSavedFight


def test_saved_modifier_requires_explicit_period(tmp_path):
    effect = {"type": "temp_hp", "flat": 1, "modifier_once": "test"}
    bundle = {
        "actor_id": "actor:test",
        "actor_template": {
            "entity_id": "actor:test", "display_name": "Test", "team_id": "team:test",
            "primary_combatant": True, "armor_class": 10, "maximum_hp": 10,
            "speed_ft": 30, "initiative_bonus": 0, "dexterity_score": 10,
            "proficiency_bonus": 2, "saving_throws": {}, "resources": [],
            "action_ids": ["action:test"], "reaction_ids": [],
        },
        "action_catalog": [{
            "source_definition_id": "action:test", "display_name": "Test",
            "owner_id": "actor:test", "economy": "ACTION", "resolution_kind": "TYPED",
            "target_kind": "SELF", "parameters": {"typed": {"effects": [effect]}},
        }],
    }
    path = tmp_path / TYPED_BUNDLES_FILE
    path.write_text(json.dumps([bundle]))
    with pytest.raises(UnsupportedSavedFight) as caught:
        load_typed_bundles(tmp_path)
    assert isinstance(caught.value.__cause__, ValueError)
    assert "modifier_once_period" in str(caught.value.__cause__)
    effect["modifier_once_period"] = "round"
    path.write_text(json.dumps([bundle]))
    assert load_typed_bundles(tmp_path) == (bundle,)
