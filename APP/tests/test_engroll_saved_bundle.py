"""Unsealed saved roll effects must fail at the saved-bundle boundary."""
import json

import pytest

from combat.gate3_storage import TYPED_BUNDLES_FILE, load_typed_bundles
from combat.saved_fight_format import UnsupportedSavedFight


@pytest.mark.parametrize("kind", ["advantage", "disadvantage", "attack_modifier"])
@pytest.mark.parametrize("location", ["action", "nested", "option", "rider"])
def test_saved_roll_target_required_and_sealed_bundle_loads(tmp_path, kind, location):
    effect = {"type": kind, "on": "attack rolls"}
    typed = {"source": "action:synthetic", "effects": []}
    if location == "action":
        typed["effects"] = [effect]
    elif location == "nested":
        typed["effects"] = [{"type": "attack", "on_hit": [
            {"type": "save", "subjects": {"area_scope": None, "exclude_self": False},
             "on_fail": [effect]}]}]
    elif location == "option":
        typed["options"] = [{"effects": [effect]}]
    else:
        typed["riders"] = [{"effects": [effect]}]
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
            "target_kind": "SELF", "parameters": {"typed": typed},
        }],
    }
    path = tmp_path / TYPED_BUNDLES_FILE
    path.write_text(json.dumps([bundle]))
    with pytest.raises(UnsupportedSavedFight) as caught:
        load_typed_bundles(tmp_path)
    assert isinstance(caught.value.__cause__, ValueError)
    assert f"{kind} effect from actor:test requires roll_target" in str(caught.value.__cause__)

    effect["roll_target"] = None
    path.write_text(json.dumps([bundle]))
    assert load_typed_bundles(tmp_path) == (bundle,)
