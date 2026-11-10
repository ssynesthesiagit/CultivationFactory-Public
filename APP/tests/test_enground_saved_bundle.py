"""Saved modifier clocks must be explicit."""
import json

import pytest

from combat.factory_compiler import apply_modifiers, compile_character
from combat.gate3_storage import TYPED_BUNDLES_FILE, load_typed_bundles
from combat.on_hit_data import walk_effect_containers
from tests.test_typed_structure import AUTHORITY, LASH, _mechanic
import copy
from combat.saved_fight_format import UnsupportedSavedFight
from tests.h1_support import sheet


def test_real_thread_weighted_knot_compiles_with_round_clock():
    """The actual once-per-round option must carry its clock into compiled attacks."""
    bundle = compile_character(sheet(['THREAD_BASE_THREADED_STRIKE']), actor_id='actor:test')
    effects = [effect for action in bundle['action_catalog']
               for effect in walk_effect_containers(action.get('parameters', {}).get('typed', {}))
               if effect.get('modifier_once') == 'THREAD_BASE_THREADED_STRIKE']
    assert effects
    assert all(effect.get('modifier_once_period') == 'round' for effect in effects)


def test_saved_modifier_requires_explicit_period(tmp_path):
    mechanics = {
        "LASH": AUTHORITY["mechanics"]["LASH"],
        "LIMITED": _mechanic("LIMITED", "Limited Current", "passive", [], {
            "targets": ["Water Lash"], "scope": "named", "when": "hit", "optional": False,
            "limit": "once_per_round", "effects": [{"type": "extra_damage", "flat": 2, "on_hit_bonus": None}]}),
    }
    built = {"LASH": {"action_id": "a:lash", "name": "Water Lash", "economy": "action",
        "target_kind": "HOSTILE_ENTITY", "range_ft": 30, "costs": [],
        "typed": {"effects": copy.deepcopy(LASH), "riders": [], "numbers": {"pb": 4}},
        "mechanic": mechanics["LASH"], "modifiers": []}}
    apply_modifiers(built, list(mechanics), mechanics, "qi", {"qi": 10})
    typed = built["LASH"]["typed"]
    effect = next(e for e in walk_effect_containers(typed) if e.get("modifier_once") == "LIMITED")
    assert effect["modifier_once_period"] == "round"
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
    assert load_typed_bundles(tmp_path) == (bundle,)
    del effect["modifier_once_period"]
    path.write_text(json.dumps([bundle]))
    with pytest.raises(UnsupportedSavedFight) as caught:
        load_typed_bundles(tmp_path)
    assert isinstance(caught.value.__cause__, ValueError)
    assert "modifier_once_period" in str(caught.value.__cause__)
