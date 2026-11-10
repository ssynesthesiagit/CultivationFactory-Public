"""Saved fights require the same recipient seal as newly built effects."""
import json

import pytest

from combat.gate3_storage import TYPED_BUNDLES_FILE, load_typed_bundles
from combat.saved_fight_format import UnsupportedSavedFight
from factory_authoring.effect_subjects import derive_effect_subjects


@pytest.mark.parametrize("location", ["action", "nested", "option", "rider"])
@pytest.mark.parametrize("kind", ["other", "save", "ally"])
def test_saved_effect_requires_complete_subjects(tmp_path, location, kind):
    effect = {
        "other": {"type": "condition", "condition": "prone"},
        "save": {"type": "save", "ability": "dex"},
        "ally": {"type": "speed", "applies_to": "ally"},
    }[kind]
    typed = {"source": "synthetic.source", "effects": []}
    if location == "action":
        typed["effects"] = [effect]
    elif location == "nested":
        typed["effects"] = [{"type": "attack", "on_hit": [{"type": "save", "on_fail": [effect]}]}]
    elif location == "option":
        typed["options"] = [{"effects": [effect]}]
    else:
        typed["riders"] = [{"effects": [effect]}]
    derive_effect_subjects(typed)
    bundle = {
        "actor_id": "actor:synthetic.source",
        "actor_template": {
            "entity_id": "actor:synthetic.source", "display_name": "Test", "team_id": "team:test",
            "primary_combatant": True, "armor_class": 10, "maximum_hp": 10,
            "speed_ft": 30, "initiative_bonus": 0, "dexterity_score": 10,
            "proficiency_bonus": 2, "saving_throws": {}, "resources": [],
            "action_ids": ["action:test"], "reaction_ids": [],
        },
        "action_catalog": [{
            "source_definition_id": "action:test", "display_name": "Test",
            "owner_id": "actor:synthetic.source", "economy": "ACTION", "resolution_kind": "TYPED",
            "target_kind": "SELF", "parameters": {"typed": typed},
        }],
    }
    path = tmp_path / TYPED_BUNDLES_FILE
    sealed = effect.pop("subjects")
    path.write_text(json.dumps([bundle]))
    with pytest.raises(UnsupportedSavedFight) as caught:
        load_typed_bundles(tmp_path)
    assert isinstance(caught.value.__cause__, ValueError)
    assert "subjects" in str(caught.value.__cause__)
    assert effect["type"] in str(caught.value.__cause__)
    assert "synthetic.source" in str(caught.value.__cause__)

    if kind != "other":
        effect["subjects"] = {**sealed}
        del effect["subjects"]["exclude_self" if kind == "save" else "or_self"]
        path.write_text(json.dumps([bundle]))
        with pytest.raises(UnsupportedSavedFight) as partial:
            load_typed_bundles(tmp_path)
        assert isinstance(partial.value.__cause__, ValueError)
        assert "subjects" in str(partial.value.__cause__)

    effect["subjects"] = sealed
    path.write_text(json.dumps([bundle]))
    assert load_typed_bundles(tmp_path) == (bundle,)
