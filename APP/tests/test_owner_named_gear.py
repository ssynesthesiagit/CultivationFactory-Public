from __future__ import annotations

import pytest

from app.core import FoundryError
from character_creation.service import CharacterCreationExecutionService, _provider_payload
from factory_authoring.starting_kits import (
    owner_named_gear,
    preferred_kit_plan,
    resolve_starting_kit,
)


BG = "tianxia.background.abandoned_orphan"
PATH = "tianxia.path.body_refining"
METEOR_HAMMER = "tianxia.mortal.weapon.liu_xing_chui"
MAUL = "tianxia.mortal.weapon.da_chui"


@pytest.mark.parametrize(("phrase", "groups", "advisory"), [
    ("A fighter who carries a meteor hammer or a maul", [], True),
    ("A fighter who carries a meteor hammer or maul", [], True),
    ("A fighter who carries a meteor hammer / a maul", [], True),
    ("A fighter who carries a meteor hammer/maul", [], True),
    ("A fighter who carries either a maul or a meteor hammer", [], True),
    ("A fighter using a meteor hammer or wielding a maul", [], True),
    ("A fighter wielding a maul or using a meteor hammer", [], True),
    ("A fighter using either a meteor hammer or carrying a maul", [], True),
    ("A fighter either using a meteor hammer or wielding a maul", [], True),
    ("A fighter using a meteor hammer / wielding a maul", [], True),
    ("A fighter without armor and with a meteor hammer", [{METEOR_HAMMER}], False),
    ("A fighter without armor and wielding a meteor hammer", [{METEOR_HAMMER}], False),
    ("A fighter with no shield but carries a spear", [], True),
    ("A fighter with no armor and no shield", [], False),
    ("A fighter without armor or shields", [], False),
    ("A fighter without armor, shields, and mauls", [], False),
    ("A fighter who doesn't wear armor or carry a shield", [], False),
    ("A fighter who doesn’t wear armor and carry a shield", [], False),
    ("A fighter who does not wear armor, carry a shield, or use a staff", [], False),
    ("A fighter who fights without using a staff or wielding a maul", [], False),
    ("A fighter without using a meteor hammer and carrying a chain whip", [], False),
    ("A fighter never using a staff, wielding a maul, or carrying a sickle", [], False),
    ("A fighter who avoids using a staff and wielding a maul", [], False),
    ("A fighter who never uses a staff or carries a sickle", [], False),
    ("A fighter without using a staff or wielding a maul but with a meteor hammer", [{METEOR_HAMMER}], False),
    ("A fighter without using a staff and with a meteor hammer", [{METEOR_HAMMER}], False),
    ("A fighter without using a staff with a maul", [{MAUL}], False),
    ("A fighter without using a staff and he carries a sickle", [{"tianxia.mortal.weapon.lian"}], False),
    ("A fighter without armor and without a meteor hammer", [], False),
    ("A fighter who uses no mauls, meteor hammers, or spears", [], False),
    ("A fighter who uses no mauls, meteor hammers, or spears, wielding a staff", [{"tianxia.mortal.weapon.gun"}], False),
    ("A fighter without armor; carrying a staff", [{"tianxia.mortal.weapon.gun"}], False),
    ("A fighter carrying a staff and sickle", [{"tianxia.mortal.weapon.gun"}, {"tianxia.mortal.weapon.lian"}], False),
    ("A fighter carrying a staff, sickle", [{"tianxia.mortal.weapon.gun"}, {"tianxia.mortal.weapon.lian"}], False),
    ("A fighter carrying a staff or sickle", [], True),
    ("A fighter carrying a staff, sickle, and maul", [{"tianxia.mortal.weapon.gun"}, {"tianxia.mortal.weapon.lian"}, {MAUL}], False),
    ("A fighter carrying a meteor hammer and chain whip", [{METEOR_HAMMER}, {"tianxia.mortal.weapon.jie_bian"}], False),
    ("A fighter carrying a meteor hammer or chain whip", [], True),
    ("A fighter carrying a meteor hammer, chain whip, and sickle", [{METEOR_HAMMER}, {"tianxia.mortal.weapon.jie_bian"}, {"tianxia.mortal.weapon.lian"}], False),
    ("A fighter with a meteor hammer or a maul and a staff", [{"tianxia.mortal.weapon.gun"}], True),
    ("A fighter who wields not only a staff but also a sickle", [{"tianxia.mortal.weapon.gun"}, {"tianxia.mortal.weapon.lian"}], False),
])
def test_owner_gear_clause_polarity_and_catalog_lists(phrase, groups, advisory) -> None:
    gear = owner_named_gear(phrase)
    assert [{row["item_id"]} for row in gear["items"]] == groups
    assert len(gear["item_ids"]) == len(groups)
    assert len(gear["warnings"]) == int(advisory)


@pytest.mark.parametrize("phrase", [
    "A fighter who carries a meteor hammer or a maul",
    "A fighter who carries a meteor hammer or maul",
    "A fighter who carries a meteor hammer / a maul",
    "A fighter who carries a meteor hammer/maul",
    "A fighter who carries either a maul or a meteor hammer",
])
def test_explicit_owner_alternatives_are_advisory(phrase) -> None:
    gear = owner_named_gear(phrase)
    assert gear["items"] == []
    assert gear["item_ids"] == []
    assert len(gear["warnings"]) == 1
    assert "meteor hammer" in gear["warnings"][0].lower()
    assert "maul" in gear["warnings"][0].lower()
    assert "Optional gear suggestion" in gear["warnings"][0]


@pytest.mark.parametrize(("phrase", "expected"), [
    ("A fighter without armor and with a meteor hammer", {METEOR_HAMMER}),
    ("A fighter without armor and wielding a meteor hammer", {METEOR_HAMMER}),
    ("A fighter with no shield but carries a spear", set()),
    ("A fighter without armor or shields", set()),
    ("A fighter without armor, shields, and mauls", set()),
    ("A fighter without armor and without a meteor hammer", set()),
])
def test_exclusion_scope_ends_only_at_new_positive_clause(phrase, expected) -> None:
    gear = owner_named_gear(phrase)
    assert {row["item_id"] for row in gear["items"]} == expected
    assert bool(gear["warnings"]) == ("spear" in phrase)


@pytest.mark.parametrize(("phrase", "groups"), [
    ("A fighter with a meteor hammer or a maul and a staff", [{"tianxia.mortal.weapon.gun"}]),
    ("A fighter with a meteor hammer and a maul", [{METEOR_HAMMER}, {MAUL}]),
])
def test_advisory_does_not_absorb_conjunctive_requirements(phrase, groups) -> None:
    gear = owner_named_gear(phrase)
    assert [{row["item_id"]} for row in gear["items"]] == groups


@pytest.mark.parametrize("phrase", [
    "A fighter carrying a meteor hammer or a stormglass glaive",
    "A fighter carrying a stormglass glaive or maul",
    "A fighter carrying a stormglass glaive/maul",
    "A fighter using a stormglass glaive or wielding a maul",
    "A fighter using a meteor hammer or expertly wielding a maul",
    "A fighter using either a stormglass glaive or wielding a maul",
    "A fighter using a meteor hammer / expertly wielding a maul",
    "A fighter using either a meteor hammer or expertly wielding a maul",
    "A fighter using either a meteor hammer and a maul",
])
def test_unresolved_alternative_does_not_require_recognized_subset(phrase) -> None:
    gear = owner_named_gear(phrase)
    assert gear["items"] == []
    assert gear["item_ids"] == []
    assert len(gear["warnings"]) == 1
    assert "Optional gear suggestion" in gear["warnings"][0]


def _intent(starting_kit: dict, *, background_id: str = BG, path_id: str = PATH) -> dict:
    return {
        "acquisition_intent": {"starting_kit": starting_kit},
        "selected_by_slot": {"background_choice": [background_id], "path_choice": [path_id]},
        "bounded_choices": {},
    }


def test_owner_named_meteor_hammer_is_resolved_to_catalog_gear_and_kit_purchase() -> None:
    gear = owner_named_gear("A brutal fighter using a meteor hammer.")
    assert gear["item_ids"] == [METEOR_HAMMER]
    plan = preferred_kit_plan(BG, PATH, gear["item_ids"])
    assert plan is not None
    kit = resolve_starting_kit(
        BG, PATH, path_option=plan["path_option"], picks=plan["picks"],
        purchases=plan.get("purchases"), seed="concept-weapon-test",
    )
    assert METEOR_HAMMER in {row["item_id"] for row in kit["items"]}


def test_owner_named_gear_is_in_prompt_and_omission_is_rejected_with_repairable_error() -> None:
    gear = owner_named_gear("Meteor hammer", "Heaven-Anvil Maul Cultivator")
    ids = gear["item_ids"]
    assert set(ids) == {METEOR_HAMMER, MAUL}

    prompt = _provider_payload(
        {"request": {"owner_gear_requirements": gear["items"]}},
        cue_limit=0,
        display_limit=0,
    )
    assert prompt["owner_gear_requirements"] == gear["items"]
    assert any("Owner-named catalog gear is required" in line for line in prompt["instructions"])

    with pytest.raises(FoundryError) as error:
        CharacterCreationExecutionService._starting_kit_construction(
            _intent({"path_option": "option_a", "picks": {}}),
            "concept-weapon-test",
            10,
            owner_gear_preferences=ids,
        )
    assert error.value.code == "CG1_OWNER_NAMED_GEAR_MISSING"
    assert {row["item_id"] for row in error.value.details["required_items"]} == set(ids)
    without_kit = _intent({"path_option": "option_a", "picks": {}})
    without_kit["acquisition_intent"] = {}
    with pytest.raises(FoundryError) as missing_kit:
        CharacterCreationExecutionService._starting_kit_construction(
            without_kit, "concept-weapon-test", 10, owner_gear_preferences=ids,
        )
    assert missing_kit.value.code == "CG1_OWNER_NAMED_GEAR_MISSING"

    repaired = preferred_kit_plan(BG, PATH, ids)
    assert repaired is not None
    decision = {**repaired, "treasure_weapon": {"chassis_id": METEOR_HAMMER, "material_id": "tianxia.treasure.material.five_phase_alloy", "enchantment_ids": []}}
    kit, _record = CharacterCreationExecutionService._starting_kit_construction(
        _intent(decision), "concept-weapon-test", 10, owner_gear_preferences=ids,
    )
    assert set(ids) <= {row["item_id"] for row in kit["resolved"]["items"]}


def test_uncatalogued_weapon_name_returns_plain_warning() -> None:
    gear = owner_named_gear("He carries a stormglass glaive.")
    assert gear["item_ids"] == []
    assert gear["warnings"] == [
        "We couldn't match 'stormglass glaive' to catalog gear, so it wasn't added to the starting gear. "
        "Choose a catalog item or add this gear by hand."
    ]


def test_ambiguous_spear_alias_is_advisory() -> None:
    gear = owner_named_gear("A spear fighter")
    assert gear["items"] == []
    assert gear["item_ids"] == []
    assert len(gear["warnings"]) == 1
    assert "Duan Qiang (Spear)" in gear["warnings"][0]
    assert "Qiang (Spear)" in gear["warnings"][0]


@pytest.mark.parametrize(("phrase", "expected_id"), [
    ("a lance", "tianxia.mortal.weapon.mao"),
    ("a broadsword", "tianxia.mortal.weapon.dao"),
    ("a chain whip", "tianxia.mortal.weapon.jie_bian"),
    ("Dao (Saber / Broadsword)", "tianxia.mortal.weapon.dao"),
])
def test_slash_separated_catalog_aliases_resolve_individually(phrase: str, expected_id: str) -> None:
    gear = owner_named_gear(f"A fighter carrying {phrase}")
    assert gear["item_ids"] == [expected_id]
    assert gear["warnings"] == []


def test_explicitly_excluded_weapon_does_not_become_required() -> None:
    gear = owner_named_gear("A fighter who never uses a meteor hammer")
    assert gear["item_ids"] == []
    assert gear["items"] == []
    assert gear["warnings"] == []


def test_coordinated_explicit_weapon_exclusions_do_not_become_requirements() -> None:
    gear = owner_named_gear("A fighter who uses no swords or spears")
    assert gear["item_ids"] == []
    assert gear["items"] == []
    assert gear["warnings"] == []


def test_exclusion_scope_covers_later_coordinated_item() -> None:
    gear = owner_named_gear("A fighter who never uses a meteor hammer or a maul")
    assert gear["item_ids"] == []
    assert gear["items"] == []
    assert gear["warnings"] == []


@pytest.mark.parametrize("phrase", [
    "A fighter who never uses a maul or a meteor hammer",
    "A fighter who never uses a meteor hammer or a maul",
    "A fighter who uses no swords or spears",
])
def test_exclusions_follow_text_order_for_coordinated_gear(phrase: str) -> None:
    gear = owner_named_gear(phrase)
    assert gear["item_ids"] == []
    assert gear["items"] == []


@pytest.mark.parametrize(("phrase", "expected_ids"), [
    ("A fighter who uses no mauls, meteor hammers, or spears", []),
    ("A fighter who uses no mauls, meteor hammers, or spears, but carries a staff",
     ["tianxia.mortal.weapon.gun"]),
    ("A fighter who uses no mauls, meteor hammers, or spears, wielding a staff",
     ["tianxia.mortal.weapon.gun"]),
])
def test_comma_exclusion_list_stops_at_positive_clause(phrase, expected_ids) -> None:
    gear = owner_named_gear(phrase)
    assert gear["item_ids"] == expected_ids
    assert gear["warnings"] == []


@pytest.mark.parametrize("phrase", [
    "A fighter who wields not only a staff but also a sickle",
    "A fighter who does not only use a staff but also a sickle",
])
def test_not_only_is_affirmative_owner_gear(phrase: str) -> None:
    gear = owner_named_gear(phrase)
    assert set(gear["item_ids"]) == {"tianxia.mortal.weapon.gun", "tianxia.mortal.weapon.lian"}
    assert gear["warnings"] == []


@pytest.mark.parametrize(("path_option", "picks", "purchases"), [
    ("option_b", {"background:1": 2}, ["tianxia.mortal.weapon.nu_gong"]),
    ("option_b", {"background:1": 0}, ["tianxia.mortal.weapon.nu_gong"]),
    ("option_a", {"background:1": 2, "path:0": 1}, []),
])
def test_replanning_checks_satisfied_requirements_together(path_option, picks, purchases) -> None:
    gear = owner_named_gear("A fighter with a staff, a sickle, and a crossbow")
    run = {"request": {}, "_derived_owner_gear_warnings": []}
    kit, _record = CharacterCreationExecutionService._starting_kit_construction(
        _intent({"path_option": path_option, "picks": picks, "purchases": purchases},
                background_id="tianxia.background.village_child", path_id="tianxia.path.spirit_awakening"),
        "concept-replan-all-requirements", 1, owner_gear_preferences=gear["item_ids"],
        owner_gear_requirements=gear["items"], run=run,
    )
    actual = {row["item_id"] for row in kit["resolved"]["items"]}
    assert actual & set(gear["item_ids"])
    assert run["_derived_owner_gear_warnings"]
    assert not kit["resolved"].get("treasure_weapon")


def test_replanning_retains_purchased_requirements_without_charging_twice(monkeypatch) -> None:
    from factory_authoring import starting_kits

    background = "tianxia.background.merchant_clan_scion"
    shell = "tianxia.mortal.armor.mountain_pattern_grand_shell"
    original_background = starting_kits.background_kit
    def fixed_coin(background_id):
        kit = original_background(background_id)
        for entry in kit["entries"]:
            if entry["kind"] == "coin":
                entry["roll"] = {"count": 5, "sides": 1}
        return kit
    monkeypatch.setattr(starting_kits, "background_kit", fixed_coin)
    seed = "concept-retained-fixed-purchase"
    gear = owner_named_gear("A fighter with a Mountain-Pattern Grand Shell and a staff")
    run = {"request": {}, "_derived_owner_gear_warnings": []}
    with pytest.raises(FoundryError) as omitted:
        CharacterCreationExecutionService._starting_kit_construction(
            _intent({"path_option": "option_b", "picks": {}, "purchases": [shell]}, background_id=background),
            seed, 1, owner_gear_preferences=gear["item_ids"], owner_gear_requirements=gear["items"], run=run,
        )
    assert omitted.value.code == "CG1_OWNER_NAMED_GEAR_MISSING"
    assert omitted.value.details["required_items"] == [{"name": "Gun (Staff)", "item_id": "tianxia.mortal.weapon.gun"}]
    assert run["_derived_owner_gear_warnings"] == []


@pytest.mark.parametrize(("phrase", "expected"), [
    ("A fighter who wields two daggers", "tianxia.mortal.weapon.bi_shou"),
    ("A fighter who carries spears", None),
    ("A fighter with a spear, no swords", None),
])
def test_ordinary_positive_plural_gear_is_recognized(phrase: str, expected: str | None) -> None:
    gear = owner_named_gear(phrase)
    if expected:
        assert gear["item_ids"] == [expected]
        assert gear["warnings"] == []
    else:
        assert gear["items"] == []
        assert gear["item_ids"] == []
        assert len(gear["warnings"]) == 1
    if "no swords" in phrase:
        assert not any("sword" in item_id for item_id in gear["item_ids"])
    if "two daggers" in phrase:
        assert "two daggers; one is required" in gear["advisories"][0]


@pytest.mark.parametrize("quantity_phrase", ["two daggers", "a pair of sabers", "3 daggers", "3 knives", "12 daggers", "seven daggers"])
def test_explicit_quantity_is_non_blocking_advice(quantity_phrase: str) -> None:
    gear = owner_named_gear(f"A fighter carrying {quantity_phrase}")
    assert len(gear["items"]) == 1
    assert gear["warnings"] == []
    assert gear["advisories"] == [
        f"Your concept asks for {quantity_phrase}; one is required. The quantity isn't enforced automatically; add more by hand if you want them."
    ]


@pytest.mark.parametrize("phrase", [
    "a small knife", "a hunting knife", "two hunting knives", "a pair of small knives",
    "two gathering knives", "two river knives", "two work knives",
])
def test_printed_knife_aliases(phrase: str) -> None:
    gear = owner_named_gear(f"A fighter carrying {phrase}")
    assert gear["items"] == [{"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)"}]
    assert gear["warnings"] == []
    assert gear["advisories"] == ([] if phrase.startswith("a ") and "pair" not in phrase else [
        f"Your concept asks for {phrase}; one is required. The quantity isn't enforced automatically; add more by hand if you want them."
    ])


def test_irregular_staff_plural_is_resolved() -> None:
    gear = owner_named_gear("A fighter carrying two staves")
    assert gear["item_ids"] == ["tianxia.mortal.weapon.gun"]
    assert gear["warnings"] == []
    assert "two staves; one is required" in gear["advisories"][0]


@pytest.mark.parametrize("phrase", ["two stormglass knives", "two stormglass staves", "two stormglass quarterstaves"])
def test_unresolved_irregular_plural_gets_readable_advice(phrase: str) -> None:
    gear = owner_named_gear(f"A fighter carrying {phrase}")
    assert gear["items"] == []
    assert len(gear["warnings"]) == 1
    assert phrase in gear["warnings"][0]
    assert "Choose a catalog item or add this gear by hand" in gear["warnings"][0]


def test_concept_weapon_chassis_satisfies_named_requirement_without_mundane_purchase() -> None:
    decision = {"path_option": "option_a", "picks": {}, "treasure_weapon": {
        "chassis_id": METEOR_HAMMER,
        "material_id": "tianxia.treasure.material.five_phase_alloy",
        "enchantment_ids": [],
    }}
    gear = owner_named_gear("A fighter who wields a meteor hammer")
    kit, _record = CharacterCreationExecutionService._starting_kit_construction(
        _intent(decision), "concept-weapon-chassis-only", 10,
        owner_gear_preferences=gear["item_ids"], owner_gear_requirements=gear["items"],
    )
    assert kit["resolved"]["treasure_weapon"]["chassis"]["item_id"] == METEOR_HAMMER


def test_concept_armor_chassis_satisfies_named_requirement_without_mundane_purchase() -> None:
    armor = "tianxia.mortal.armor.lacquered_leather"
    gear = owner_named_gear("A scout wearing lacquered leather armor")
    decision = {"path_option": "option_a", "picks": {}, "treasure_armor": {
        "chassis_id": armor,
        "material_id": "tianxia.treasure.armor_material.cloud_silk",
        "enhancement_ids": [],
    }}
    kit, _record = CharacterCreationExecutionService._starting_kit_construction(
        _intent(decision), "concept-armor-chassis-only", 10,
        owner_gear_preferences=gear["item_ids"], owner_gear_requirements=gear["items"],
    )
    assert kit["resolved"]["treasure_armor"]["chassis"]["item_id"] == armor


def test_lucky_funds_leave_omission_advisory_and_actual_purchase_accepted() -> None:
    from factory_authoring.starting_kits import seeded_roll

    background = "tianxia.background.merchant_clan_scion"
    shell = "tianxia.mortal.armor.mountain_pattern_grand_shell"
    seed = next(
        f"concept-shell-seed-{index}"
        for index in range(200)
        if seeded_roll(f"concept-shell-seed-{index}", f"coin:{background}:a purse of mixed coin:0", 20) >= 5
    )
    gear = owner_named_gear("A fighter wearing a Mountain-Pattern Grand Shell")
    plan = {"path_option": "option_b", "picks": {}, "purchases": [shell]}
    no_purchase_run = {"request": {}, "_derived_owner_gear_warnings": []}
    CharacterCreationExecutionService._starting_kit_construction(
        _intent({"path_option": "option_b", "picks": {}}, background_id=background, path_id=PATH), seed, 10,
        owner_gear_preferences=gear["item_ids"], owner_gear_requirements=gear["items"],
        run=no_purchase_run,
    )
    assert "optional" in no_purchase_run["_derived_owner_gear_warnings"][0]

    run = {"request": {}, "_derived_owner_gear_warnings": []}
    kit, _record = CharacterCreationExecutionService._starting_kit_construction(
        _intent(plan, background_id=background, path_id=PATH), seed, 10, owner_gear_preferences=gear["item_ids"],
        owner_gear_requirements=gear["items"], run=run,
    )
    assert shell in {row["item_id"] for row in kit["resolved"]["items"]}
    assert run["_derived_owner_gear_warnings"] == []


def test_lucky_alternative_kit_does_not_make_gear_mandatory() -> None:
    from factory_authoring.starting_kits import seeded_roll

    background = "tianxia.background.merchant_clan_scion"
    shell = "tianxia.mortal.armor.mountain_pattern_grand_shell"
    seed = next(
        f"concept-shell-alternative-{index}"
        for index in range(200)
        if seeded_roll(f"concept-shell-alternative-{index}", f"coin:{background}:a purse of mixed coin:0", 20) >= 5
    )
    gear = owner_named_gear("A fighter wearing a Mountain-Pattern Grand Shell")
    run = {"request": {}, "_derived_owner_gear_warnings": []}
    CharacterCreationExecutionService._starting_kit_construction(
        _intent({"path_option": "option_a", "picks": {}}, background_id=background, path_id=PATH), seed, 10,
        owner_gear_preferences=gear["item_ids"], owner_gear_requirements=gear["items"], run=run,
    )
    assert gear["items"][0]["name"] in run["_derived_owner_gear_warnings"][0]
    assert "optional" in run["_derived_owner_gear_warnings"][0]


def test_requirements_share_funds_and_cannot_double_spend_one_choice(monkeypatch) -> None:
    from factory_authoring import starting_kits

    background = "tianxia.background.merchant_clan_scion"
    jian = "tianxia.mortal.weapon.jian"
    dao = "tianxia.mortal.weapon.dao"
    monkeypatch.setattr(starting_kits, "background_kit", lambda _bg: {"entries": []})
    monkeypatch.setattr(starting_kits, "_path_entries", lambda _path, _option: ([{
        "kind": "choice",
        "options": [
            {"kind": "item", "item_id": jian},
            {"kind": "item", "item_id": dao},
        ],
    }], 0))
    required = [jian, dao]
    # One legal menu can supply either weapon, while the shared budget cannot buy both.
    assert not starting_kits.owner_gear_requirements_affordable(
        background, PATH, "option_a", required, remaining_coin_cc=0,
    )


@pytest.mark.parametrize(("budget", "retained", "expected"), [
    (100, [], True), (99, [], False), (0, [MAUL], True),
    (100, [METEOR_HAMMER], True), (99, [METEOR_HAMMER], False),
])
def test_repeated_mandatory_items_price_distinct_acquisitions(budget, retained, expected) -> None:
    from factory_authoring.starting_kits import owner_gear_requirements_affordable

    assert owner_gear_requirements_affordable(
        BG, PATH, "option_b",
        [MAUL, MAUL],
        remaining_coin_cc=budget, retained_item_ids=retained,
    ) is expected


def test_multiple_owner_gear_requirements_exceed_one_seeded_budget() -> None:
    background = "tianxia.background.merchant_clan_scion"
    shell = "tianxia.mortal.armor.mountain_pattern_grand_shell"
    seed = next(
        f"concept-gear-budget-{index}"
        for index in range(200)
        if resolve_starting_kit(
            background, PATH, path_option="option_b", seed=f"concept-gear-budget-{index}"
        )["coin_cc"] == 2050
    )
    gear = owner_named_gear("A fighter wearing a Mountain-Pattern Grand Shell, a meteor hammer, and a maul")
    run = {"request": {}, "_derived_owner_gear_warnings": []}
    kit, _record = CharacterCreationExecutionService._starting_kit_construction(
        _intent({"path_option": "option_b", "picks": {}, "purchases": [shell]}, background_id=background),
        seed, 10, owner_gear_preferences=gear["item_ids"], owner_gear_requirements=gear["items"], run=run,
    )
    assert shell in {row["item_id"] for row in kit["resolved"]["items"]}
    assert len(kit["resolved"].get("purchases") or []) == 1
    expected_names = ", ".join(group["name"] for group in gear["items"] if "shell" not in group["name"].casefold())
    assert run["_derived_owner_gear_warnings"] == [
        f"{expected_names} couldn't all be added because the legal starting-kit choices and remaining guaranteed coin don't cover them together. These items are optional; either starting kit is allowed."
    ]


@pytest.mark.parametrize("concept_alias", ["concept", "owner_descriptive_fields.concept", "character.identity.concept"])
def test_creation_request_reads_each_sealed_concept_alias(catalog_environment, concept_alias) -> None:
    from character_builder import CharacterBuilderService
    from character_creation.service import CharacterCreationExecutionService
    from project_store.service import ProjectStore
    from stage1.service import Stage1ClipboardService

    owner_concept = "A fighter with a meteor hammer" if concept_alias == "concept" else ""
    project = CharacterBuilderService(catalog_environment["db"]).create_project(
        working_name=f"Named gear alias {concept_alias}", concept=owner_concept, target_cl=1, power_band="standard",
        source_reference=None, creation_mode="detailed", ability_scores={}, selections={},
    )
    store = ProjectStore(catalog_environment["db"])
    if concept_alias != "concept":
        store.append_user_locks(project["project_id"], [{"field": concept_alias, "value": "A fighter with a meteor hammer"}])
    creator = CharacterCreationExecutionService(
        catalog_environment["db"], stage1=Stage1ClipboardService(catalog_environment["db"]),
        provider=None, project_store=store,
    )
    request = creator._complete_request(project["project_id"], execution_mode="MANUAL_CHAT", idempotency_key=f"concept-alias:{concept_alias}")
    assert request["owner_gear_requirements"] == [{"item_id": METEOR_HAMMER, "name": "Liu Xing Chui (Meteor Hammer)"}]


@pytest.mark.parametrize(("concept", "expected"), [
    ("A fighter who carries a meteor hammer or a maul", set()),
    ("A fighter who carries a meteor hammer/maul", set()),
    ("A fighter using a meteor hammer or wielding a maul", set()),
    ("A fighter without armor and with a meteor hammer", {METEOR_HAMMER}),
    ("A fighter with no shield but carries a spear", set()),
])
def test_sealed_request_preserves_advisories_and_positive_resets(catalog_environment, concept, expected) -> None:
    from character_builder import CharacterBuilderService
    from project_store.service import ProjectStore
    from stage1.service import Stage1ClipboardService

    db = catalog_environment["db"]
    project = CharacterBuilderService(db).create_project(
        working_name="Owner gear clauses", concept=concept, target_cl=1, power_band="standard",
        source_reference=None, creation_mode="detailed", ability_scores={}, selections={},
    )
    creator = CharacterCreationExecutionService(db, stage1=Stage1ClipboardService(db), provider=None,
                                                project_store=ProjectStore(db))
    request = creator._complete_request(project["project_id"], execution_mode="MANUAL_CHAT",
                                       idempotency_key=f"gear-clauses:{project['project_id']}")
    assert {row["item_id"] for row in request.get("owner_gear_requirements", [])} == expected
    assert request.get("owner_gear_preferences", []) == list(expected)
    assert bool(request.get("owner_gear_warnings")) == (not expected)
    assert creator.request_payload_sha256(request) == request["request_sha256"]


@pytest.mark.parametrize(("concept", "title", "expected"), [
    ("A fighter using a stormglass glaive or wielding a maul", "", []),
    ("A fighter using either a meteor hammer or expertly wielding a maul", "", []),
    ("A fighter using a meteor hammer or maul", "Maul master", [{MAUL}]),
])
def test_sealed_request_keeps_advisory_separate_from_named_title(catalog_environment, concept, title, expected) -> None:
    from character_builder import CharacterBuilderService
    from project_store.service import ProjectStore
    from stage1.service import Stage1ClipboardService

    db = catalog_environment["db"]
    project = CharacterBuilderService(db).create_project(
        working_name="Owner gear confidence", concept=concept, target_cl=1, power_band="standard",
        source_reference=None, creation_mode="detailed", ability_scores={}, selections={},
    )
    store = ProjectStore(db)
    if title:
        store.append_user_locks(project["project_id"], [{"field": "owner_descriptive_fields.identity.title", "value": title}])
    creator = CharacterCreationExecutionService(db, stage1=Stage1ClipboardService(db), provider=None, project_store=store)
    request = creator._complete_request(project["project_id"], execution_mode="MANUAL_CHAT",
                                       idempotency_key=f"gear-confidence:{project['project_id']}")
    assert [{row["item_id"]} for row in request.get("owner_gear_requirements", [])] == expected
    assert len(request["owner_gear_warnings"]) == 1
    assert "Optional gear suggestion" in request["owner_gear_warnings"][0]
    if not expected:
        assert not request.get("owner_gear_preferences")
    assert creator.request_payload_sha256(request) == request["request_sha256"]
