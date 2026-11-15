"""Statuses observed from equipment, life state and typed settings have catalog rules."""
import copy
from types import SimpleNamespace

import pytest

import combat.condition_text as condition_text
from combat.condition_text import all_conditions
from combat.status_text import describe


@pytest.mark.parametrize(("condition", "source", "meaning"), [
    ("held_object", "system:starting_equipment", "hand"),
    ("shield_equipped", "system:starting_equipment", "shield"),
    ("body_scene", "system:body_modes_scene_resources", "scene"),
    ("death_finalized", "system:damage", "died"),
    ("blacksmith_current_item", "action:typed.smith.blacksmith.current_item.equipment", "workpiece"),
    ("treasure_armor_element_choice", "tianxia.treasure.armor_enhancement.sovereign_resistance_matrix", "resistance"),
])
def test_applied_status_has_catalog_rule(condition, source, meaning, monkeypatch):
    actor = SimpleNamespace(entity_id="smith", turns_started=1)
    engine = SimpleNamespace(action_catalog={}, state=SimpleNamespace(actors={"smith": actor}))
    row = {"condition_id": "condition:typed." + condition, "source_definition_id": source,
           "source_actor_id": "smith", "expires_on": "UNTIL_REMOVED"}

    # The shipped definition must exist and reach the status, even on a public
    # export where rule prose is scrambled.
    catalog = all_conditions()
    assert catalog[condition]["rule"]["_rule"].strip()
    assert catalog[condition]["reading"].strip()
    assert describe(engine, actor, row, {}, {"smith": "Smith"}, {}, condition_rules=catalog)["rule_text"].strip()

    # Use known synthetic prose to check that this particular definition, not
    # an unrelated fallback, supplies both the catalog and the status text.
    rules = copy.deepcopy(condition_text.rules())
    rules["conditions"][condition]["_rule"] = f"This status records the {meaning}."
    monkeypatch.setattr(condition_text, "rules", lambda: rules)
    catalog = all_conditions()
    assert meaning in catalog[condition]["reading"].lower()
    result = describe(engine, actor, row, {}, {"smith": "Smith"}, {}, condition_rules=catalog)
    assert meaning in result["rule_text"].lower()
