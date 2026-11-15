"""Saved compiled effects must be sealed before a fight can resume."""
import json

import pytest

from combat.gate3_storage import TYPED_BUNDLES_FILE, load_typed_bundles
from combat.saved_fight_format import UnsupportedSavedFight


@pytest.mark.parametrize("location", ["action", "nested", "option", "rider"])
def test_saved_effect_requires_on_hit_bonus(tmp_path, location):
    effect = {"type": "extra_damage", "deferred": True,
              "evidence": "Once per turn when you hit, deal extra damage."}
    typed = {"source": "synthetic", "effects": []}
    if location == "action":
        typed["effects"] = [effect]
    elif location == "nested":
        typed["effects"] = [{"type": "attack", "on_hit": [
            {"type": "save", "on_fail": [effect]}]}]
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
    assert "on_hit_bonus" in str(caught.value.__cause__)

    effect["on_hit_bonus"] = None
    path.write_text(json.dumps([bundle]))
    assert load_typed_bundles(tmp_path) == (bundle,)
