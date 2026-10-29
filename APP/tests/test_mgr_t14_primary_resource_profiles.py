"""Compile Sphere actions using all supported primary-resource sheet shapes."""
from copy import deepcopy
import json

import pytest

from combat.factory_compiler import compile_character, primary_resource
from test_factory_combat_compiler import SHEET


@pytest.mark.parametrize("resource,qi", [
    ("Qi", True),
    ("Stamina", False),
    ({"name": "Qi", "maximum": 40}, True),
    (json.dumps({"name": "Stamina", "maximum": 40}), False),
])
def test_compiler_sphere_qi_profile_tracks_primary_resource(resource, qi):
    sheet = deepcopy(SHEET)
    sheet["ability_scores_and_statistics"]["primary_resource"] = resource
    bundle = compile_character(sheet, actor_id="actor:profile-test")
    assert primary_resource(sheet)[2].lower() == ("qi" if qi else "stamina")
    sphere_actions = [a["parameters"]["typed"] for a in bundle["action_catalog"]
                      if a.get("parameters", {}).get("typed", {}).get("sphere")
                      and not a["parameters"]["typed"].get("attack_action")
                      and a["parameters"]["typed"].get("qi_powered") is not False]
    assert sphere_actions
    assert all(bool(action.get("qi_powered")) is qi for action in sphere_actions)
