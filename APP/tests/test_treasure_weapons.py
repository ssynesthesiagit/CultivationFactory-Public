"""Treasure weapons built by Item Book Chapter 2 and carried in the starting-kit record."""

import pytest

from app.core import FoundryError
from character_creation.constructed_arts.records import build_starting_kit_record, construct_starting_kit, validate_starting_kit_record
from character_creation.response_materialization import canonical_starting_kit
from factory_authoring.treasure_weapons import enchantment_options, material_options, resolve_treasure_weapon, weapon_grade

ORPHAN = "tianxia.background.abandoned_orphan"
HEIR = "tianxia.background.clan_heir"
JIAN = "tianxia.mortal.weapon.jian"


def _full_weapon(background_id: str, target_cl: int) -> dict:
    grade = weapon_grade(target_cl, background_id)["grade"]
    material = material_options(grade)[0]["material_id"]
    chosen: list[str] = []
    while options := enchantment_options(JIAN, material, grade, chosen):
        chosen.append(options[0]["enchantment_id"])
    return {"chassis_id": JIAN, "material_id": material, "enchantment_ids": chosen}


def test_cl18_weapon_is_at_least_saint_and_scales_with_wealth():
    assert weapon_grade(4, ORPHAN) is None
    assert weapon_grade(15, ORPHAN)["grade"] == "Saint"
    assert weapon_grade(18, ORPHAN)["grade"] == "Sovereign"
    assert weapon_grade(18, HEIR)["grade"] == "Imperial"


def test_enchantments_fill_but_never_exceed_capacity():
    weapon = _full_weapon(HEIR, 18)
    resolved = resolve_treasure_weapon(target_cl=18, background_id=HEIR, **weapon)
    assert resolved["grade"] == "Imperial"
    assert resolved["total_enchantment_value"] <= resolved["enchantment_capacity"]
    with pytest.raises(FoundryError):
        resolve_treasure_weapon(target_cl=18, background_id=ORPHAN, **weapon)


def test_kit_record_carries_and_rederives_the_weapon():
    decision = canonical_starting_kit({"path_option": "option_b", "picks": {}, "treasure_weapon": _full_weapon(ORPHAN, 18)})
    kit = construct_starting_kit(
        background_id=ORPHAN, path_id="tianxia.path.body_refining", path_option="option_b", picks={},
        seed="a" * 64, treasure_weapon={**decision["treasure_weapon"], "target_cl": 18},
    )
    record = build_starting_kit_record(kit)
    assert validate_starting_kit_record(record)["resolved"]["treasure_weapon"]["grade"] == "Sovereign"
    assert "Treasure weapon:" in record["display_projection"]["full_description"]
    with pytest.raises(FoundryError):
        canonical_starting_kit({"path_option": "option_b", "picks": {}, "treasure_weapon": {"chassis_id": JIAN}})


BODY = "tianxia.path.body_refining"
SPIRIT = "tianxia.path.spirit_awakening"


def test_armor_follows_the_path_kit_and_stays_below_a_signature_weapon():
    from factory_authoring.treasure_armor import armor_grade, chassis_options

    assert chassis_options(SPIRIT) == []
    assert {row["armor_category"] for row in chassis_options(BODY)} == {"light", "medium", "shield"}
    assert weapon_grade(18, HEIR)["grade"] == "Imperial"
    assert armor_grade(18, HEIR)["grade"] == "Sovereign"


def test_purchases_respect_budget_signature_grade_and_attunement():
    from factory_authoring.treasure_catalog import (
        ATTUNEMENT_SLOTS, consumable_options, resolve_treasure_catalog, treasure_plan, wondrous_options,
    )

    plan = treasure_plan(18, HEIR, BODY)
    wondrous: list[str] = []
    while options := wondrous_options(plan, wondrous):
        wondrous.append(options[-1]["treasure_id"])
    consumables: list[str] = []
    while options := consumable_options(plan, consumables):
        consumables.append(options[-1]["consumable_id"])
    resolved = resolve_treasure_catalog(target_cl=18, background_id=HEIR, path_id=BODY, wondrous_ids=wondrous, consumable_ids=consumables)
    assert all(row["grade"] != "Imperial" for row in resolved["wondrous"])
    assert plan["attunement_used"] + sum(row["attunement_slots"] for row in resolved["wondrous"]) <= ATTUNEMENT_SLOTS
    assert resolved["wondrous_value_gt"] <= plan["wondrous_budget_gt"]
    assert resolved["consumable_value_gt"] <= plan["consumable_budget_gt"]
    with pytest.raises(FoundryError):
        resolve_treasure_catalog(target_cl=18, background_id=ORPHAN, path_id=BODY, wondrous_ids=wondrous, consumable_ids=[])


def test_heaven_mark_capacity_bonus_applies_only_to_new_capacity_rules():
    from factory_authoring.treasure_weapons import CAPACITY_RULES_CURRENT

    heaven_mark = "tianxia.treasure.material.heaven_mark_violet_gold"
    grade = weapon_grade(18, HEIR)["grade"]
    chosen: list[str] = []
    while options := enchantment_options(JIAN, heaven_mark, grade, chosen):
        chosen.append(max(options, key=lambda row: row["equivalent_bonus"])["enchantment_id"])
    new = resolve_treasure_weapon(target_cl=18, background_id=HEIR, chassis_id=JIAN, material_id=heaven_mark,
                                  enchantment_ids=chosen, capacity_rules=CAPACITY_RULES_CURRENT)
    assert new["enchantment_capacity"] == 11
    # Kits built before the rule keep re-deriving with grade capacity only.
    with pytest.raises(FoundryError):
        resolve_treasure_weapon(target_cl=18, background_id=HEIR, chassis_id=JIAN, material_id=heaven_mark, enchantment_ids=chosen)


def test_treasure_weapon_menu_follows_the_weapon_spheres():
    from factory_authoring.treasure_weapons import sphere_fit_chassis

    names = lambda known: [row["item_id"].rsplit(".", 1)[1] for row in sphere_fit_chassis(known)]
    # Owner 2026-09-24: a Sabers + Dual Wielding character was given a dagger.
    assert names({"tianxia.sphere.sabers", "tianxia.sphere.dual_wielding"}) == ["duan_dao", "hu_die_dao", "dao"]
    assert "bi_shou" not in names({"tianxia.sphere.sabers"})
    assert all(name != "qiang" for name in names({"tianxia.sphere.dual_wielding"}))
    assert len(names({"tianxia.sphere.air"})) == 32


def test_without_a_weapon_sphere_the_path_s_trained_weapons_come_first():
    """Owner 2026-09-26: 13 finished characters got a treasure weapon they could not use."""
    from factory_authoring.starting_kits import _authorities
    from factory_authoring.treasure_weapons import sphere_fit_chassis

    catalog = _authorities()[1]
    qi = sphere_fit_chassis(set(), path_id="tianxia.path.qi_cultivation")
    assert qi and {catalog[row["item_id"]]["proficiency"] for row in qi} == {"simple"}
    body = sphere_fit_chassis(set(), path_id="tianxia.path.body_refining")
    assert {catalog[row["item_id"]]["proficiency"] for row in body} == {"simple", "martial"}
    assert [row["item_id"] for row in sphere_fit_chassis({"tianxia.sphere.sabers"}, path_id="tianxia.path.qi_cultivation")] == \
        [row["item_id"] for row in sphere_fit_chassis({"tianxia.sphere.sabers"})]  # a weapon Sphere still decides


def test_heavy_weapons_come_last_for_a_character_without_strength_13():
    """Owner 2026-09-26: the picker ignored Heavy -- 2024 Heavy attacks have Disadvantage below Strength (Dexterity) 13."""
    from factory_authoring.treasure_weapons import _properties, sphere_fit_chassis

    weak = sphere_fit_chassis([], scores={"STR": 10, "DEX": 14})
    strong = sphere_fit_chassis([], scores={"Strength": 16, "Dexterity": 14})
    heavy = [row["item_id"] for row in weak if "Heavy" in _properties(row) and "Ammunition" not in _properties(row)]
    assert heavy and all(row["item_id"] in heavy for row in weak[-len(heavy):])  # at the end of the weak character's list
    assert [row["item_id"] for row in strong] == [row["item_id"] for row in sphere_fit_chassis([])]  # 16 Strength: unchanged
