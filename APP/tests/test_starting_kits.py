"""Starting kits: printed Background kits bound to catalog items, plus Path kits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import FoundryError
from factory_authoring import starting_kits
from factory_authoring.starting_kits import resolve_starting_kit

APP = Path(__file__).resolve().parents[1]
QI = "tianxia.path.qi_cultivation"


def test_every_printed_background_kit_is_kept_verbatim() -> None:
    backgrounds = json.loads((APP / starting_kits.KIT_AUTHORITY_PATH).read_text(encoding="utf-8"))["background_kits"]
    source = json.loads((APP / "non_sphere_authority/authority/Background_Core_Authority_v1.json").read_text(encoding="utf-8"))
    assert set(backgrounds) == {row["background_id"] for row in source["backgrounds"]}
    for row in source["backgrounds"]:
        printed = starting_kits.printed_background_items(row["background_id"])
        rebuilt = "You begin with " + ", ".join(printed[:-1]) + ", and " + printed[-1] + "."
        assert rebuilt == row["starting_equipment"]["raw_authority"]


def test_explicit_weapon_pick_for_abandoned_orphan_qi_cultivator() -> None:
    kit = starting_kits.resolve_starting_kit("tianxia.background.abandoned_orphan", QI, picks={"path:1": 0})
    names = [(item["name"], item["quantity"], item["source"]) for item in kit["items"]]
    assert ("Thieves’ Tools", 1, "background") in names and ("Rations", 3, "background") in names
    assert ("Gun (Staff)", 1, "path") in names and ("Lacquered Leather", 1, "path") in names
    assert [t["text"] for t in kit["trinkets"]] == ["one keepsake from the life you lost or never had"]
    assert kit["coin_cc"] == 50 and not any(choice["fallback_used"] for choice in kit["choices"])


def test_picks_select_from_closed_menus_and_weapon_picks_never_fall_back() -> None:
    menus = starting_kits.choice_menus("tianxia.background.military_brat", QI)
    weapon_menu = next(menu for menu in menus if menu["choice_id"] == "background:1")
    pick = weapon_menu["options"].index("Gu Duo (Mace)")
    for invalid_pick in (None, 99, -1, True):
        picks = {"background:1": pick}
        if invalid_pick is not None:
            picks["path:1"] = invalid_pick
        with pytest.raises(FoundryError, match="Choose a weapon"):
            starting_kits.resolve_starting_kit("tianxia.background.military_brat", QI, picks=picks)
    kit = starting_kits.resolve_starting_kit("tianxia.background.military_brat", QI, picks={"background:1": pick, "path:1": 1})
    assert any(item["name"] == "Gu Duo (Mace)" and item["printed"] == "a simple weapon" for item in kit["items"])
    assert not any(c["fallback_used"] for c in kit["choices"])


def test_option_b_is_coin_only_and_printed_coin_is_a_seeded_1d20_gold_roll() -> None:
    kit = starting_kits.resolve_starting_kit("tianxia.background.exiled_noble", QI, path_option="option_b", seed="s1")
    again = starting_kits.resolve_starting_kit("tianxia.background.exiled_noble", QI, path_option="option_b", seed="s1")
    (roll,) = kit["printed_coin_rolls"]
    assert kit == again and roll["dice"] == "1d20" and 1 <= roll["rolls"][0] <= 20
    assert roll["amount_cc"] == roll["rolls"][0] * 100 and kit["coin_cc"] == 550 + roll["amount_cc"]
    assert not [item for item in kit["items"] if item["source"] == "path"]
    with pytest.raises(FoundryError):
        starting_kits.resolve_starting_kit("tianxia.background.merchant_clan_scion", QI)


def test_owned_typed_weapon_delivery_uses_the_shared_kind_and_family_checks() -> None:
    from factory_authoring.weapon_requirements import owned_weapon_requirements, item_fits_requirement

    mechanics = {
        "synthetic:bow": {"name": "Bow technique", "range": {"weapon_delivery": {"kind": "ranged", "family": "bow"}}},
        "synthetic:axe": {"name": "Axe technique", "weapon_delivery": {"kind": "melee", "family": "axe"}},
    }
    assert owned_weapon_requirements(mechanics=mechanics) == []
    needs = owned_weapon_requirements(["synthetic:bow", "synthetic:axe"], mechanics=mechanics)
    assert len(needs) == 2
    bow = starting_kits.item_definition("tianxia.mortal.weapon.duan_gong")
    axe = starting_kits.item_definition("tianxia.mortal.weapon.fu")
    assert [item_fits_requirement(axe, need) for need in needs] == [True, False]
    assert [item_fits_requirement(bow, need) for need in needs] == [False, True]
    # One ability's melee option must never conceal another's ranged need.
    menus = starting_kits.choice_menus(
        "tianxia.background.military_brat", QI,
        requirements=[{"name": "Melee technique", "delivery": {"kind": "melee"}}, needs[1]],
    )
    background = next(menu for menu in menus if menu["choice_id"] == "background:1")
    assert background["allowed_indices"]
    assert all("bow" in background["options"][index].lower() for index in background["allowed_indices"])


def test_printed_kit_that_cannot_fit_the_build_records_the_missing_weapon() -> None:
    from character_creation.constructed_arts.records import construct_starting_kit, starting_kit_record_text

    need = {"name": "Bow technique", "delivery": {"kind": "ranged", "family": "bow"}}
    kit = construct_starting_kit(
        background_id="tianxia.background.abandoned_orphan", path_id=QI, path_option="option_a",
        picks={"path:1": 1}, seed="no-printed-bow", weapon_requirements=[need],
    )
    assert "Bow technique" in starting_kit_record_text(kit)
    assert "cannot supply a usable weapon" in starting_kit_record_text(kit)


def test_performer_may_choose_any_instrument() -> None:
    menu = next(m for m in starting_kits.choice_menus("tianxia.background.traveling_performer", QI) if m["choice_id"] == "background:2")
    assert "Pipa (Lute)" in menu["options"] and "Guqin (Seven-String Zither)" in menu["options"] and menu["options"][-1] == "performer’s kit"


def test_wealth_varies_widely_by_background_and_fortune() -> None:
    orphan = [starting_kits.wealth_multiplier("tianxia.background.abandoned_orphan", f"s{i}")["multiplier"] for i in range(200)]
    heir = [starting_kits.wealth_multiplier("tianxia.background.clan_heir", f"s{i}")["multiplier"] for i in range(200)]
    assert max(orphan) <= 0.75 and min(heir) >= 0.4 and max(heir) == 12.0
    assert sum(heir) / len(heir) > 10 * sum(orphan) / len(orphan)


def test_preferred_gear_pins_option_a_menus_once() -> None:
    from factory_authoring.starting_kits import preferred_kit_plan

    plan = preferred_kit_plan("tianxia.background.forest_hermit", "tianxia.path.body_refining", ["tianxia.mortal.weapon.jian"])
    assert plan == {"path_option": "option_a", "picks": {"path:1": 0}}
    kit = resolve_starting_kit("tianxia.background.forest_hermit", "tianxia.path.body_refining", path_option="option_a", picks={**plan["picks"], "path:2": 0}, seed="s")
    assert [item["name"] for item in kit["items"]].count("Jian (Straight Sword)") == 1


def test_preferred_gear_not_in_kit_is_bought_with_option_b_coin() -> None:
    from factory_authoring.starting_kits import preferred_kit_plan

    armour = "tianxia.mortal.armor.ring_lamellar_harness"
    plan = preferred_kit_plan("tianxia.background.forest_hermit", "tianxia.path.body_refining", [armour])
    assert plan["path_option"] == "option_b" and plan["purchases"] == [armour]
    plain = resolve_starting_kit("tianxia.background.forest_hermit", "tianxia.path.body_refining", path_option="option_b", seed="s")
    bought = resolve_starting_kit("tianxia.background.forest_hermit", "tianxia.path.body_refining", path_option="option_b", seed="s", purchases=plan["purchases"])
    purchase = next(item for item in bought["items"] if item["source"] == "purchase")
    assert purchase["item_id"] == armour
    assert bought["coin_cc"] == plain["coin_cc"] - purchase["value_cc"]


def test_purchases_require_option_b_and_affordable_catalog_items() -> None:
    with pytest.raises(FoundryError):
        resolve_starting_kit("tianxia.background.forest_hermit", "tianxia.path.body_refining", path_option="option_a", seed="s", purchases=["tianxia.mortal.weapon.jian"])
    with pytest.raises(FoundryError):
        resolve_starting_kit("tianxia.background.forest_hermit", "tianxia.path.body_refining", path_option="option_b", seed="s", purchases=["not.an.item"])
