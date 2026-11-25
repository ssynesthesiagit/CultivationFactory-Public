"""Dual Wielding names its Answering Weapon attack consistently."""
from combat.factory_compiler import compile_character

DUAL = "tianxia.sphere.dual_wielding"
TALENTS = [
    "TAL_DUAL_WIELDING_AMBIDEXTERITY",
    "TAL_DUAL_WIELDING_SYNCHRONOUS_ACCURACY",
    "TAL_DUAL_WIELDING_COMBO_MANEUVERS",
]


def catalog(sphere, talents=()):
    sheet = {
        "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Body Refining", "key_ability": "STR"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 16, "modifier": 3} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Stamina", "maximum": 60},
            "armor_class": {"base_value": 14}, "hit_points": {"maximum": 80}, "speed": {"walking_ft": 30},
        },
        "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]},
        "equipment": [{"starting_kit": {"items": [
            {"item_id": "tianxia.mortal.weapon.duan_jian", "quantity": 1},
            {"item_id": "tianxia.mortal.weapon.bi_shou", "quantity": 1},
        ]}}],
        "spheres_and_talents": {"sphere_record_ids": [sphere] if sphere else [], "learned_talent_record_ids": list(talents)},
    }
    return compile_character(sheet, actor_id="actor:test")["action_catalog"]


def test_dual_wielding_names_all_paired_strike_variants():
    rows = catalog(DUAL, TALENTS)
    by_id = {row["source_definition_id"].split(".weapon.")[-1]: row["display_name"]
             for row in rows if ".weapon." in row["source_definition_id"]}
    assert by_id["duan_jian#offhand"] == "Duan Jian (Short Sword) Paired Strike"
    assert by_id["duan_jian#offhand_ambidexterity"] == "Duan Jian (Short Sword) Paired Strike (Ambidexterity)"
    assert by_id["duan_jian#offhand_synchronous"] == "Duan Jian (Short Sword) Paired Strike x2 (Synchronous Accuracy)"


def test_light_weapons_without_sphere_keep_offhand_name():
    rows = catalog(None)
    answer = next(row for row in rows if row["source_definition_id"].endswith("duan_jian#offhand"))
    assert answer["display_name"] == "Duan Jian (Short Sword) off-hand attack"


def test_combo_maneuvers_keep_weapon_and_name_the_paired_strike():
    rows = catalog(DUAL, TALENTS)
    combos = [row for row in rows if ".combo_maneuvers." in row["source_definition_id"]]
    assert any(row["display_name"] == "Combo Maneuvers: Shove: Prone (Bi Shou)" for row in combos)
    dagger = next(row for row in combos if row["display_name"] == "Combo Maneuvers: Shove: Prone (Bi Shou)")
    assert "Combo Maneuvers: in place of the Bi Shou (Dagger) Paired Strike." in dagger["parameters"]["typed"]["riders"]
