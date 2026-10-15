"""Owned ability opt-ins must survive compilation in the shipped test tree.

The full table regressions live in the three A2 files. These checks distinguish
missing shipped rule data from a failure in their combat execution.
"""

import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet


@pytest.mark.parametrize("talents,block,kind", [
    (["TAL_ATHLETICS_CAPOEIRA_SPIN"], "athletics", "capoeira_spin"),
    (["TAL_ATHLETICS_SUDDEN_FLANK"], "athletics", "sudden_flank"),
    (["TAL_ATHLETICS_WHIRLWIND_FLIP"], "athletics", "whirlwind_flip"),
    (["TAL_SMOKE_BLACKEN_THE_FLAME"], "smoke_fire_soot", "soot_fire_damage"),
    (["TAL_THE_HIDDEN_EYE_WIND_READER"], "riders14_eye", "wind_reader"),
    (["TAL_THE_HIDDEN_EYE_COOPERATIVE_STEALTH"], "hidden_eye", "cooperative_stealth"),
    (["TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES", "TAL_THE_HIDDEN_EYE_FOLKLORIST"],
     "riders14_eye", "analysis_limits"),
    (["TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES", "TAL_THE_HIDDEN_EYE_FOLKLORIST"],
     "riders14_eye", "folklorist"),
    (["TAL_THE_HIDDEN_EYE_PHYSICAL_EXAMINATION"], "hidden_eye", "physical_examination"),
])
def test_owned_ability_compiles_its_runtime_opt_in(talents, block, kind):
    bundle = compile_character(sheet(talents, cl=17), actor_id="actor:factory.mainreg1")
    rows = bundle["typed_passives"]
    assert any(row.get("block") == block and row.get("kind") == kind for row in rows), (
        talents, rows, bundle.get("diagnostics"))


def test_wind_reader_scenario_uses_an_explicit_ranged_weapon_profile():
    from combat.attack_delivery import is_ranged
    from tests.test_a2_the_hidden_eye_second_pass import wind_setup

    bundle = compile_character(sheet([], cl=17), actor_id="actor:factory.mainreg1")
    wind_setup()([bundle])
    action = next(row for row in bundle["action_catalog"] if row["display_name"] == "Ranged Test Weapon")
    typed = action["parameters"]["typed"]
    assert is_ranged(typed["effects"][0]["attack_kind"], typed["range_ft"], typed["weapon"])
